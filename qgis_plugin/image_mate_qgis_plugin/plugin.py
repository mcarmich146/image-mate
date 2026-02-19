# -*- coding: utf-8 -*-
"""Main plugin wiring for Image Mate."""

from pathlib import Path
import json
import tempfile
import re

from qgis import processing
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import (
    QgsApplication,
    Qgis,
    QgsProject,
    QgsRasterLayer,
)

from .controllers.search_controller import SearchController
from .services.auth_service import AuthService
from .services.local_tile_proxy import LocalTileProxy
from .services.settings_service import SettingsService
from .services.source_service import SourceService
from .ui.main_dock import ImageMateMainDock
from .mixins import SearchStreamingMixin
from .mixins import WorkflowExecutionMixin


class ImageMatePlugin(WorkflowExecutionMixin, SearchStreamingMixin):
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self.temp_dir = Path(tempfile.gettempdir()) / "image_mate_qgis_plugin"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.action = None
        self.dock = None
        self.settings_service = SettingsService()
        self.provider_settings = self.settings_service.load()
        self.source_service = SourceService(self.provider_settings)
        self.local_tile_proxy = LocalTileProxy(self.source_service)
        self._local_tile_proxy_error = ""
        try:
            self.local_tile_proxy.start()
        except Exception as exc:
            self._local_tile_proxy_error = str(exc)
        self.auth_service = AuthService()
        self.search_controller = SearchController()
        self.search_items = {}
        self.search_layer_id = None
        self.preview_layer_id = None
        self._backend_health = {"checked_at": 0.0, "ok": False}
        self._auto_stream_enabled = True
        self._auto_stream_zoom_threshold = 13
        self._satellogic_highres_zoom_threshold = 17
        self._satellogic_max_stream_sources = 8
        self._last_auto_stream_at = 0.0
        self._last_auto_stream_item_id = ""
        self._map_extent_signal_connected = False
        self._stream_progress_timer = QTimer()
        self._stream_progress_timer.setInterval(900)
        self._stream_progress_timer.timeout.connect(self._poll_stream_progress)
        self._stream_progress_active = False
        self._stream_progress_item_id = ""
        self._stream_progress_started_at = 0.0
        self._stream_progress_baseline = {}
        self._stream_progress_last_tuple = None
        self._stream_progress_idle_ticks = 0
        self._stream_progress_last_summary_key = ""
        self._stream_progress_last_summary_at = 0.0
        self._stream_progress_last_error_key = ""
        self._stream_progress_last_error_at = 0.0
        self._stream_last_setup_key = ""
        self._last_snap_log_key = ""
        self._last_search_request = None
        self._sat_detail_items = []
        self._sat_detail_index = {
            "by_id": {},
            "by_outcome": {},
            "by_datetime": {},
            "by_day": {},
        }
        self._sat_detail_fetch_key = ""
        self._sat_detail_fetch_at = 0.0
        self._sat_capture_group_fetch_state = {}
        self._disk_log_path = ""
        self._disk_log_fp = None
        self._show_debug_on_screen = False
        self._show_search_log_on_screen = False
        self._message_log_connected = False
        self._workflow_worker = None
        self._workflow_thread = None
        self._workflow_running = False
        self._workflow_run_started_at = 0.0
        self._workflow_total_nodes = 0
        self._workflow_node_types = {}
        self.local_tile_proxy.set_event_logger(self._on_local_proxy_event)

    def initGui(self):
        icon_path = str(self.plugin_dir / "icons" / "image_mate.svg")
        self.action = QAction(QIcon(icon_path), "Image Mate", self.iface.mainWindow())
        self.action.setObjectName("imageMateOpenDockAction")
        self.action.triggered.connect(self.show_dock)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Image Mate", self.action)
        canvas = self.iface.mapCanvas()
        if canvas is not None and not self._map_extent_signal_connected:
            canvas.extentsChanged.connect(self._on_map_extent_changed)
            self._map_extent_signal_connected = True
        self._init_disk_log()
        if not self._message_log_connected:
            try:
                QgsApplication.messageLog().messageReceived.connect(self._on_qgis_message_logged)
                self._message_log_connected = True
            except Exception:
                self._message_log_connected = False
        self._log_info("Plugin initialized")

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu("&Image Mate", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

        canvas = self.iface.mapCanvas()
        if canvas is not None and self._map_extent_signal_connected:
            try:
                canvas.extentsChanged.disconnect(self._on_map_extent_changed)
            except Exception:
                pass
            self._map_extent_signal_connected = False

        self._stop_stream_progress_monitor()
        self._stop_workflow_execution(timeout_ms=2000)
        self._close_dock()
        if self.local_tile_proxy is not None:
            self.local_tile_proxy.stop()
        if self._message_log_connected:
            try:
                QgsApplication.messageLog().messageReceived.disconnect(self._on_qgis_message_logged)
            except Exception:
                pass
            self._message_log_connected = False
        self._log_info("Plugin unloaded")
        self._close_disk_log()

    def show_dock(self):
        if self.dock is None:
            self.dock = ImageMateMainDock(self.iface.mainWindow())
            self.dock.setObjectName("imageMateMainDock")
            self.dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
            self.dock.setFeatures(
                self.dock.DockWidgetMovable
                | self.dock.DockWidgetFloatable
                | self.dock.DockWidgetClosable
            )
            self.dock.destroyed.connect(self._on_dock_destroyed)
            self.dock.validate_requested.connect(self.validate_setup)
            self.dock.settings_saved.connect(self.save_settings_from_dock)
            self.dock.search_requested.connect(self.handle_search_request)
            self.dock.location_jump_requested.connect(self.handle_location_jump_request)
            self.dock.location_suggestions_requested.connect(self.handle_location_suggestions_request)
            self.dock.result_selected.connect(self.handle_result_selected)
            self.dock.execute_workflow_requested.connect(self.handle_execute_workflow_request)
            self.dock.create_vrt_requested.connect(self.handle_create_vrt_request)
            self.dock.sharpen_image_requested.connect(self.handle_sharpen_image_request)
            self.dock.source_combo.currentIndexChanged.connect(self._on_source_changed)
            self.dock.set_runtime_summary(self._runtime_summary_text())
            self.dock.load_settings(self.provider_settings)
            self._bind_dock_data()
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)

        self.dock.show()
        self.dock.raise_()
        self._log_info("Dock opened")

    def validate_setup(self):
        auth_result = self.auth_service.validate_configuration(self.provider_settings)
        sources = self.source_service.list_sources()
        source_line = ", ".join(
            [f"{row['source_id']}={'on' if row['enabled'] else 'off'}" for row in sources]
        )
        message = (
            f"{auth_result.get('message', 'validation completed')} | "
            f"sources: {source_line}"
        )
        if self.dock is not None:
            self.dock.set_runtime_summary(self._runtime_summary_text(extra_line=message))
        self.iface.messageBar().pushMessage("Image Mate", message, level=Qgis.Info, duration=6)

    def save_settings_from_dock(self):
        if self.dock is None:
            return
        self.provider_settings = self.dock.apply_settings_to(self.provider_settings)
        self.settings_service.save(self.provider_settings)
        self.source_service = SourceService(self.provider_settings)
        try:
            self.local_tile_proxy.set_source_service(self.source_service)
            if not self.local_tile_proxy.is_running():
                self.local_tile_proxy.start()
            self._local_tile_proxy_error = ""
        except Exception as exc:
            self._local_tile_proxy_error = str(exc)
        self._bind_dock_data()
        self.validate_setup()

    def handle_create_vrt_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        layer_ids_raw = request.get("layer_ids") if isinstance(request.get("layer_ids"), list) else []
        layer_ids = []
        for value in layer_ids_raw:
            layer_id = str(value or "").strip()
            if layer_id and layer_id not in layer_ids:
                layer_ids.append(layer_id)

        output_path_value = str(request.get("output_path") or "").strip()
        if not layer_ids or not output_path_value:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Create VRT request is missing layers or output path.",
                level=Qgis.Warning,
                duration=8,
            )
            return
        if not output_path_value.lower().endswith(".vrt"):
            output_path_value = f"{output_path_value}.vrt"

        output_path = Path(output_path_value)
        if output_path.parent and not output_path.parent.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            raster_layers = []
            for layer_id in layer_ids:
                layer = self._project_raster_layer_by_id(layer_id)
                if layer is None:
                    raise RuntimeError(f"Raster layer not found in project: {layer_id}")
                raster_layers.append(layer)

            params = {
                "INPUT": raster_layers,
                "RESOLUTION": 0,
                "SEPARATE": False,
                "PROJ_DIFFERENCE": False,
                "ADD_ALPHA": False,
                "OUTPUT": str(output_path),
            }
            self._append_debug_log(
                "Create VRT request: "
                f"layers={len(raster_layers)} output={output_path}"
            )
            result = processing.run("gdal:buildvirtualraster", params)
            result_path = str(result.get("OUTPUT") or output_path).strip()
            if not result_path:
                raise RuntimeError("gdal:buildvirtualraster returned an empty output path")
            if not Path(result_path).exists():
                raise RuntimeError(f"VRT output file was not created: {result_path}")

            vrt_layer = QgsRasterLayer(result_path, f"Image Mate VRT {Path(result_path).stem}")
            if not vrt_layer.isValid():
                raise RuntimeError(f"Generated VRT is invalid: {result_path}")

            self._add_layer_to_image_mate_group(vrt_layer)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"VRT created and added to project: {result_path}",
                level=Qgis.Success,
                duration=8,
            )
            self._append_debug_log(f"VRT created successfully: {result_path}")
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Create VRT failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            self._append_debug_log(f"Create VRT failed: {exc}", level=Qgis.Warning)

    def handle_sharpen_image_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        layer_id = str(request.get("layer_id") or "").strip()
        output_path_value = str(request.get("output_path") or "").strip()

        try:
            factor = float(request.get("factor") or 1.0)
        except Exception:
            factor = 1.0
        if factor <= 0:
            factor = 1.0

        if not layer_id or not output_path_value:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Sharpen Image request is missing input layer or output path.",
                level=Qgis.Warning,
                duration=8,
            )
            return
        if not output_path_value.lower().endswith((".tif", ".tiff")):
            output_path_value = f"{output_path_value}.tif"

        output_path = Path(output_path_value)
        if output_path.parent and not output_path.parent.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            layer = self._project_raster_layer_by_id(layer_id)
            if layer is None:
                raise RuntimeError(f"Raster layer not found in project: {layer_id}")
            input_path = self._resolve_local_raster_source_path(layer)
            if not input_path:
                raise RuntimeError(
                    "Selected raster layer is not a local file-based raster source compatible with unsharp mask."
                )

            self._append_debug_log(
                "Sharpen request: "
                f"layer={layer.name()} input={input_path} factor={factor:.2f} output={output_path}"
            )
            self._apply_unsharp_mask_to_raster(
                input_path=str(input_path),
                output_path=str(output_path),
                amount=float(factor),
            )

            sharpened_layer = QgsRasterLayer(str(output_path), f"Image Mate Sharpen {output_path.stem}")
            if not sharpened_layer.isValid():
                raise RuntimeError(f"Sharpened output raster is invalid: {output_path}")

            self._add_layer_to_image_mate_group(sharpened_layer)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Sharpened image created and added to project: {output_path}",
                level=Qgis.Success,
                duration=8,
            )
            self._append_debug_log(f"Sharpened image created successfully: {output_path}")
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Sharpen Image failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            self._append_debug_log(f"Sharpen Image failed: {exc}", level=Qgis.Warning)

    @staticmethod
    def _project_raster_layer_by_id(layer_id):
        layer_key = str(layer_id or "").strip()
        if not layer_key:
            return None
        layer = QgsProject.instance().mapLayer(layer_key)
        if layer is None or not isinstance(layer, QgsRasterLayer):
            return None
        return layer

    @staticmethod
    def _resolve_local_raster_source_path(layer):
        if layer is None:
            return ""
        source = str(layer.source() or "").strip()
        if not source:
            return ""

        base_source = source.split("|", 1)[0].strip()
        base_lower = base_source.lower()
        if base_lower.startswith(("http://", "https://", "wms:", "wmts:", "xyz:")):
            return ""

        if base_source.upper().startswith(("NETCDF:", "HDF5:")):
            quoted_match = re.search(r'"([^"]+)"', base_source)
            if quoted_match:
                base_source = str(quoted_match.group(1) or "").strip()

        base_source = base_source.strip().strip('"').strip("'")
        if not base_source:
            return ""

        source_path = Path(base_source)
        if not source_path.exists():
            return ""
        return str(source_path)

    def _apply_unsharp_mask_to_raster(self, *, input_path, output_path, amount):
        try:
            import numpy as np
        except Exception as exc:
            raise RuntimeError(f"NumPy is required for sharpening but is not available: {exc}") from exc

        try:
            from osgeo import gdal
        except Exception as exc:
            raise RuntimeError(f"GDAL Python bindings are unavailable: {exc}") from exc

        src_ds = gdal.Open(str(input_path), gdal.GA_ReadOnly)
        if src_ds is None:
            raise RuntimeError(f"Could not open input raster: {input_path}")

        dst_ds = None
        try:
            width = int(src_ds.RasterXSize or 0)
            height = int(src_ds.RasterYSize or 0)
            band_count = int(src_ds.RasterCount or 0)
            if width <= 0 or height <= 0 or band_count <= 0:
                raise RuntimeError("Input raster has invalid dimensions or no bands.")

            first_band = src_ds.GetRasterBand(1)
            if first_band is None:
                raise RuntimeError("Input raster band 1 is unavailable.")
            gdal_dtype = first_band.DataType

            driver = gdal.GetDriverByName("GTiff")
            if driver is None:
                raise RuntimeError("GDAL GTiff driver is unavailable.")

            create_opts = ["TILED=YES", "COMPRESS=LZW", "BIGTIFF=IF_SAFER"]
            dst_ds = driver.Create(str(output_path), width, height, band_count, gdal_dtype, options=create_opts)
            if dst_ds is None:
                raise RuntimeError(f"Failed to create output raster: {output_path}")

            geo_transform = src_ds.GetGeoTransform()
            projection = src_ds.GetProjection()
            if geo_transform:
                dst_ds.SetGeoTransform(geo_transform)
            if projection:
                dst_ds.SetProjection(projection)

            metadata = src_ds.GetMetadata()
            if metadata:
                dst_ds.SetMetadata(metadata)

            for band_index in range(1, band_count + 1):
                src_band = src_ds.GetRasterBand(band_index)
                dst_band = dst_ds.GetRasterBand(band_index)
                if src_band is None or dst_band is None:
                    raise RuntimeError(f"Raster band {band_index} is unavailable.")

                data = src_band.ReadAsArray()
                if data is None:
                    raise RuntimeError(f"Failed reading raster band {band_index}.")
                original_dtype = data.dtype
                values = data.astype(np.float32, copy=False)

                nodata = src_band.GetNoDataValue()
                valid_mask = np.isfinite(values)
                if nodata is not None:
                    valid_mask = valid_mask & (values != float(nodata))

                if np.any(valid_mask):
                    blurred = self._box_blur_3x3(values, valid_mask, np)
                    sharpened = values + float(amount) * (values - blurred)
                else:
                    sharpened = values

                if nodata is not None:
                    sharpened = np.where(valid_mask, sharpened, float(nodata))
                else:
                    sharpened = np.where(valid_mask, sharpened, values)

                casted = self._cast_array_to_dtype(sharpened, original_dtype, np)
                dst_band.WriteArray(casted)

                if nodata is not None:
                    try:
                        dst_band.SetNoDataValue(float(nodata))
                    except Exception:
                        pass
                try:
                    dst_band.SetColorInterpretation(src_band.GetColorInterpretation())
                except Exception:
                    pass
                dst_band.FlushCache()

            dst_ds.FlushCache()
        finally:
            src_ds = None
            dst_ds = None

    @staticmethod
    def _box_blur_3x3(values, valid_mask, np):
        data = np.where(valid_mask, values, 0.0).astype(np.float32, copy=False)
        weights = valid_mask.astype(np.float32, copy=False)
        padded_data = np.pad(data, ((1, 1), (1, 1)), mode="edge")
        padded_weights = np.pad(weights, ((1, 1), (1, 1)), mode="edge")

        sum_data = (
            padded_data[:-2, :-2]
            + padded_data[:-2, 1:-1]
            + padded_data[:-2, 2:]
            + padded_data[1:-1, :-2]
            + padded_data[1:-1, 1:-1]
            + padded_data[1:-1, 2:]
            + padded_data[2:, :-2]
            + padded_data[2:, 1:-1]
            + padded_data[2:, 2:]
        )
        sum_weights = (
            padded_weights[:-2, :-2]
            + padded_weights[:-2, 1:-1]
            + padded_weights[:-2, 2:]
            + padded_weights[1:-1, :-2]
            + padded_weights[1:-1, 1:-1]
            + padded_weights[1:-1, 2:]
            + padded_weights[2:, :-2]
            + padded_weights[2:, 1:-1]
            + padded_weights[2:, 2:]
        )
        return np.where(sum_weights > 0.0, sum_data / sum_weights, values)

    @staticmethod
    def _cast_array_to_dtype(values, dtype, np):
        dtype_obj = np.dtype(dtype)
        if np.issubdtype(dtype_obj, np.integer):
            info = np.iinfo(dtype_obj)
            clipped = np.clip(np.rint(values), info.min, info.max)
            return clipped.astype(dtype_obj)
        if np.issubdtype(dtype_obj, np.floating):
            return values.astype(dtype_obj)
        return values.astype(dtype_obj)

    def handle_search_request(self, payload):
        request_payload = None
        if self.dock is not None:
            self.dock.set_search_enabled(False)
        self._append_search_log("Starting search against provider...")
        try:
            remove_existing_layers = bool(payload.get("remove_existing_layers"))
            if remove_existing_layers:
                removed_count = self._remove_existing_image_mate_layers()
                self._append_search_log(f"Removed {removed_count} existing Image Mate layer(s).")
            geometry = self._current_extent_geometry_wgs84()
            request_payload = self.search_controller.build_search_request(payload, geometry)
            
            # Log AOI bounds for debugging
            bounds_info = self._extract_bounds_summary(geometry)
            self._append_search_log(f"Search AOI bounds: {bounds_info}")
            self._append_search_log(f"Date range: {request_payload.get('start_date')} to {request_payload.get('end_date')}")
            self._append_search_log(f"Collection: {request_payload.get('collection_id')}")
            self._append_search_log(f"Full request payload:\n{json.dumps(request_payload, indent=2)}")
            self._last_search_request = dict(request_payload)
            items = self._search_with_satellogic_detail_parity(request_payload)
            self.search_items = {str(item.get("id") or ""): item for item in items or []}
            self._render_search_results_layer(items)
            self._last_auto_stream_item_id = ""
            self._last_auto_stream_at = 0.0
            self._on_map_extent_changed()
            if self.dock is not None:
                self.dock.set_results(items)
            self._append_search_log(
                f"Search returned {len(items)} items for source={request_payload.get('source_id')} collection={request_payload.get('collection_id')}"
            )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Search completed: {len(items)} items",
                level=Qgis.Success,
                duration=5,
            )
        except Exception as exc:
            error_msg = str(exc)
            if request_payload:
                bounds_info = self._extract_bounds_summary(request_payload.get("geometry", {}))
                self._append_search_log(f"Search failed with AOI: {bounds_info}", level=Qgis.Warning)
                self._append_search_log(f"Failed request payload:\n{json.dumps(request_payload, indent=2)}", level=Qgis.Warning)
            
            # Check for common error patterns
            if "500 Server Error" in error_msg:
                self._append_search_log(f"Search failed: {exc}\n\nHint: 500 Server Error may indicate invalid date range (future dates?) or geometry issues.", level=Qgis.Warning)
            else:
                self._append_search_log(f"Search failed: {exc}", level=Qgis.Warning)
            
            self.iface.messageBar().pushMessage("Image Mate", f"Search failed: {exc}", level=Qgis.Critical, duration=10)
        finally:
            if self.dock is not None:
                self.dock.set_search_enabled(True)

    def handle_location_jump_request(self, query_text):
        query = str(query_text or "").strip()
        if not query:
            return
        try:
            lat, lon, location_label, resolution = self._resolve_location_query(query)
            self._center_canvas_on_wgs84(lat=lat, lon=lon)
            coord_text = f"{lat:.6f}, {lon:.6f}"
            if resolution == "coordinates":
                log_line = f"Map jumped to coordinates: {coord_text}"
            else:
                log_line = f"Map jumped to '{location_label}' at {coord_text}"
            self._append_search_log(log_line)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Map moved to {coord_text}",
                level=Qgis.Success,
                duration=5,
            )
        except Exception as exc:
            self._append_search_log(
                f"Location jump failed for '{query}': {exc}",
                level=Qgis.Warning,
            )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Location jump failed: {exc}",
                level=Qgis.Warning,
                duration=8,
            )

    def handle_location_suggestions_request(self, query_text):
        if self.dock is None:
            return
        query = str(query_text or "").strip()
        if len(query) < 2:
            self.dock.set_location_suggestions([], for_query=query)
            return
        try:
            suggestions = self._geocode_location_suggestions(query, limit=8)
        except Exception:
            suggestions = []
        self.dock.set_location_suggestions(suggestions, for_query=query)

    def handle_result_selected(self, item_id):
        item_key = str(item_id or "").strip()
        if not item_key:
            return
        item = self.search_items.get(item_key)
        if not item:
            return
        source_id = str(item.get("source_id") or "").strip().lower()
        detail_mode = self._is_detail_zoom()
        create_new_layer_on_select = bool(
            self.dock is not None and self.dock.create_new_layer_on_selection_enabled()
        )

        self._stop_stream_progress_monitor()
        self._append_search_log(f"Loading imagery for selection: {item_key}")
        if self.dock is not None:
            self.dock.set_stream_status(f"Stream status: preparing {source_id or 'source'} item {item_key}")
        try:
            stream_item = item
            if source_id == "satellogic" and detail_mode:
                stream_item = self._resolve_satellogic_stream_item(item)
            stream_source_urls = None
            stream_source_items = None
            if source_id == "satellogic":
                stream_source_urls, stream_source_items = self._satellogic_stream_sources_and_items(
                    stream_item,
                    overview_item=item,
                )
                if len(stream_source_urls or []) > 1:
                    self._append_debug_log(
                        "Satellogic stream candidates resolved: "
                        f"item={item.get('id')} strips={len(stream_source_urls)}"
                    )
            if stream_item is not item:
                self._append_search_log(
                    "Resolved selection to l1d-sr detail item "
                    f"{stream_item.get('id')} (from {item.get('id')})."
                )
            layer = self._build_stream_layer_for_item(
                stream_item,
                source_urls=stream_source_urls,
                source_items=stream_source_items,
            )
            if layer is not None:
                self._replace_preview_layer(layer, replace_existing=not create_new_layer_on_select)
                if create_new_layer_on_select:
                    self._append_search_log(f"Loaded streaming raster layer (new layer): {layer.name()}")
                else:
                    self._append_search_log(f"Loaded streaming raster layer: {layer.name()}")
                self._last_auto_stream_item_id = item_key
                if source_id == "satellogic":
                    using_local_proxy = (
                        self.local_tile_proxy.is_running()
                        and self.local_tile_proxy.base_url in str(layer.source() or "")
                    )
                    if using_local_proxy:
                        self._start_stream_progress_monitor(item_key)
                    else:
                        self._set_stream_status("Stream status: active (satellogic via backend proxy)")
                else:
                    self._set_stream_status(f"Stream status: active ({source_id})")
                self.iface.messageBar().pushMessage(
                    "Image Mate",
                    f"Streaming imagery loaded for {item_key}",
                    level=Qgis.Success,
                    duration=5,
                )
                return

            layer = self._load_item_imagery_layer(item)
            self._replace_preview_layer(layer, replace_existing=not create_new_layer_on_select)
            if create_new_layer_on_select:
                self._append_search_log(f"Loaded raster layer (new layer): {layer.name()}")
            else:
                self._append_search_log(f"Loaded raster layer: {layer.name()}")
            self._last_auto_stream_item_id = item_key
            self._set_stream_status(f"Stream status: fallback download loaded for {item_key}")
            self.iface.messageBar().pushMessage("Image Mate", f"Imagery loaded for {item_key}", level=Qgis.Success, duration=5)
        except Exception as exc:
            self._append_search_log(f"Imagery load failed for {item_key}: {exc}", level=Qgis.Warning)
            self._set_stream_status(f"Stream status: failed for {item_key} ({exc})")
            self.iface.messageBar().pushMessage("Image Mate", f"Imagery load failed: {exc}", level=Qgis.Warning, duration=8)
