# -*- coding: utf-8 -*-
"""Main plugin wiring for Image Mate."""

from pathlib import Path
import json
import tempfile
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import urlopen

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from .controllers.search_controller import SearchController
from .services.auth_service import AuthService
from .services.local_tile_proxy import LocalTileProxy
from .services.settings_service import SettingsService
from .services.source_service import SourceService
from .ui.main_dock import ImageMateMainDock
from .ui.settings_dialog import SettingsDialog


class ImageMatePlugin:
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
        self._close_dock()
        if self.local_tile_proxy is not None:
            self.local_tile_proxy.stop()
        self._log_info("Plugin unloaded")

    def show_dock(self):
        if self.dock is None:
            self.dock = ImageMateMainDock(self.iface.mainWindow())
            self.dock.setObjectName("imageMateMainDock")
            self.dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
            self.dock.destroyed.connect(self._on_dock_destroyed)
            self.dock.validate_requested.connect(self.validate_setup)
            self.dock.settings_requested.connect(self.open_settings)
            self.dock.search_requested.connect(self.handle_search_request)
            self.dock.result_selected.connect(self.handle_result_selected)
            self.dock.source_combo.currentIndexChanged.connect(self._on_source_changed)
            self.dock.set_runtime_summary(self._runtime_summary_text())
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

    def open_settings(self):
        dialog = SettingsDialog(self.provider_settings, self.iface.mainWindow())
        if dialog.exec_() != dialog.Accepted:
            return
        self.provider_settings = dialog.apply_to(self.provider_settings)
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

    def handle_search_request(self, payload):
        request_payload = None
        if self.dock is not None:
            self.dock.set_search_enabled(False)
        if self.dock is not None:
            self.dock.append_search_log("Starting search against provider...")
        try:
            remove_existing_layers = bool(payload.get("remove_existing_layers"))
            if remove_existing_layers:
                removed_count = self._remove_existing_image_mate_layers()
                if self.dock is not None:
                    self.dock.append_search_log(f"Removed {removed_count} existing Image Mate layer(s).")
            geometry = self._current_extent_geometry_wgs84()
            request_payload = self.search_controller.build_search_request(payload, geometry)
            if self.dock is not None:
                self.dock.append_search_log(json.dumps(request_payload, indent=2))
            self._last_search_request = dict(request_payload)
            items = self._search_with_satellogic_detail_parity(request_payload)
            self.search_items = {str(item.get("id") or ""): item for item in items or []}
            self._render_search_results_layer(items)
            self._last_auto_stream_item_id = ""
            self._last_auto_stream_at = 0.0
            self._on_map_extent_changed()
            if self.dock is not None:
                self.dock.set_results(items)
                self.dock.append_search_log(
                    f"Search returned {len(items)} items for source={request_payload.get('source_id')} collection={request_payload.get('collection_id')}"
                )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Search completed: {len(items)} items",
                level=Qgis.Success,
                duration=5,
            )
        except Exception as exc:
            if self.dock is not None:
                if request_payload:
                    self.dock.append_search_log(json.dumps(request_payload, indent=2))
                self.dock.append_search_log(f"Search failed: {exc}")
            self.iface.messageBar().pushMessage("Image Mate", f"Search failed: {exc}", level=Qgis.Critical, duration=10)
        finally:
            if self.dock is not None:
                self.dock.set_search_enabled(True)

    def handle_result_selected(self, item_id):
        item_key = str(item_id or "").strip()
        if not item_key:
            return
        item = self.search_items.get(item_key)
        if not item:
            return
        source_id = str(item.get("source_id") or "").strip().lower()
        detail_mode = self._is_detail_zoom()

        self._stop_stream_progress_monitor()
        if self.dock is not None:
            self.dock.append_search_log(f"Loading imagery for selection: {item_key}")
            self.dock.set_stream_status(f"Stream status: preparing {source_id or 'source'} item {item_key}")
        try:
            stream_item = item
            if source_id == "satellogic" and detail_mode:
                stream_item = self._resolve_satellogic_stream_item(item)
            if stream_item is not item and self.dock is not None:
                self.dock.append_search_log(
                    "Resolved selection to l1d-sr detail item "
                    f"{stream_item.get('id')} (from {item.get('id')})."
                )
            layer = self._build_stream_layer_for_item(stream_item)
            if layer is not None:
                self._replace_preview_layer(layer)
                if self.dock is not None:
                    self.dock.append_search_log(f"Loaded streaming raster layer: {layer.name()}")
                self._last_auto_stream_item_id = item_key
                if source_id == "satellogic":
                    self._start_stream_progress_monitor(item_key)
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
            self._replace_preview_layer(layer)
            if self.dock is not None:
                self.dock.append_search_log(f"Loaded raster layer: {layer.name()}")
            self._last_auto_stream_item_id = item_key
            self._set_stream_status(f"Stream status: fallback download loaded for {item_key}")
            self.iface.messageBar().pushMessage("Image Mate", f"Imagery loaded for {item_key}", level=Qgis.Success, duration=5)
        except Exception as exc:
            if self.dock is not None:
                self.dock.append_search_log(f"Imagery load failed for {item_key}: {exc}")
            self._set_stream_status(f"Stream status: failed for {item_key} ({exc})")
            self.iface.messageBar().pushMessage("Image Mate", f"Imagery load failed: {exc}", level=Qgis.Warning, duration=8)

    def _close_dock(self):
        self._stop_stream_progress_monitor()
        if self.dock is None:
            return

        self.iface.removeDockWidget(self.dock)
        self.dock.deleteLater()
        self.dock = None

    def _on_dock_destroyed(self, _obj=None):
        self.dock = None

    def _bind_dock_data(self):
        if self.dock is None:
            return
        default_dates = self.search_controller.default_dates()
        self.dock.set_default_dates(default_dates["start_date"], default_dates["end_date"])
        sources = self.source_service.list_sources()
        self.dock.set_sources(sources)
        self.dock.set_contract_id(self.source_service.default_contract_id())
        self._on_source_changed()
        if self.local_tile_proxy.is_running():
            self.dock.set_stream_status(f"Stream status: idle (proxy {self.local_tile_proxy.base_url})")
        else:
            self.dock.set_stream_status("Stream status: idle (local proxy unavailable)")
        self.dock.set_runtime_summary(self._runtime_summary_text())

    def _on_source_changed(self):
        if self.dock is None:
            return
        source_id = self.dock.current_source_id() or "satellogic"
        self.dock.set_collections(self.source_service.list_collections(source_id))
        self.dock.set_contract_enabled(source_id == "satellogic")

    def _runtime_summary_text(self, extra_line=None):
        runtime = self.source_service.runtime_summary()
        lines = [
            f"Repo root used: {runtime.get('repo_root_used') or 'not resolved'}",
            f"Env file used: {runtime.get('env_file_used') or 'not found'}",
            f"Backend API base URL: {self._backend_api_base_url()}",
            f"Local tile proxy: {self.local_tile_proxy.base_url if self.local_tile_proxy.is_running() else 'unavailable'}",
            f"Satellogic auth mode: {runtime['satellogic_auth_mode']}",
            f"Satellogic contract configured: {'yes' if runtime['satellogic_contract_configured'] else 'no'}",
            f"Satellogic credentials detected (.env/backend): {'yes' if runtime.get('satellogic_credentials_detected') else 'no'}",
            f"Satellogic authcfg configured: {'yes' if runtime['satellogic_authcfg_configured'] else 'no'}",
            f"CDSE enabled: {'yes' if runtime['cdse_enabled'] else 'no'}",
            f"CDSE WMTS configured: {'yes' if runtime['cdse_wmts_configured'] else 'no'}",
            f"CDSE credentials detected (.env/backend): {'yes' if runtime.get('cdse_credentials_detected') else 'no'}",
            f"CDSE authcfg configured: {'yes' if runtime['cdse_authcfg_configured'] else 'no'}",
            f"Backend provider modules ready: {'yes' if runtime.get('backend_ready') else 'no'}",
        ]
        if runtime.get("backend_error"):
            lines.append(f"Backend init error: {runtime['backend_error']}")
        if self._local_tile_proxy_error:
            lines.append(f"Local tile proxy error: {self._local_tile_proxy_error}")
        if extra_line:
            lines.append(f"Validation: {extra_line}")
        return "\n".join(lines)

    def _set_stream_status(self, text):
        if self.dock is not None:
            self.dock.set_stream_status(str(text or "").strip() or "Stream status: idle")

    @staticmethod
    def _normalize_collection_id(collection_id):
        return str(collection_id or "").strip().lower().replace("_", "-")

    @staticmethod
    def _item_outcome_key(item):
        return str(item.get("outcome_id") or "").strip()

    @staticmethod
    def _item_datetime_key(item):
        value = str(item.get("datetime") or "").strip()
        return value[:19] if len(value) >= 19 else value

    def _search_with_satellogic_detail_parity(self, request_payload):
        source_id = str(request_payload.get("source_id") or "").strip().lower()
        if source_id != "satellogic":
            self._sat_detail_items = []
            self._sat_detail_index = {"by_id": {}, "by_outcome": {}, "by_datetime": {}, "by_day": {}}
            self._sat_detail_fetch_key = ""
            self._sat_detail_fetch_at = 0.0
            return self.source_service.search(request_payload)

        primary_items = self.source_service.search(request_payload)
        primary_collection = self._normalize_collection_id(request_payload.get("collection_id"))
        detail_items = []
        if primary_collection == "l1d-sr":
            detail_items = list(primary_items)
        else:
            detail_request = dict(request_payload)
            detail_request["collection_id"] = "l1d-sr"
            detail_request["limit"] = max(300, int(request_payload.get("limit") or 250))
            try:
                detail_items = self.source_service.search(detail_request)
                if self.dock is not None:
                    self.dock.append_search_log(
                        f"Detail parity fetch (l1d-sr) returned {len(detail_items)} items for streaming."
                    )
            except Exception as exc:
                detail_items = []
                if self.dock is not None:
                    self.dock.append_search_log(
                        f"Detail parity fetch (l1d-sr) failed, using primary collection only: {exc}"
                    )

        self._sat_detail_items = list(detail_items or [])
        self._rebuild_sat_detail_index()
        self._sat_detail_fetch_key = ""
        self._sat_detail_fetch_at = 0.0
        return primary_items

    def _rebuild_sat_detail_index(self):
        by_id = {}
        by_outcome = {}
        by_datetime = {}
        by_day = {}
        for row in self._sat_detail_items or []:
            item_id = str(row.get("id") or "").strip()
            if item_id and item_id not in by_id:
                by_id[item_id] = row

            outcome = self._item_outcome_key(row)
            if outcome:
                by_outcome.setdefault(outcome, []).append(row)

            dt = self._item_datetime_key(row)
            if dt:
                by_datetime.setdefault(dt, []).append(row)
                by_day.setdefault(dt[:10], []).append(row)

        for bucket in (by_outcome, by_datetime, by_day):
            for key in list(bucket.keys()):
                bucket[key] = sorted(
                    bucket[key],
                    key=lambda item: str(item.get("datetime") or "").strip(),
                    reverse=True,
                )

        self._sat_detail_index = {
            "by_id": by_id,
            "by_outcome": by_outcome,
            "by_datetime": by_datetime,
            "by_day": by_day,
        }

    def _resolve_satellogic_stream_item(self, item):
        if str(item.get("source_id") or "").strip().lower() != "satellogic":
            return item
        if self._normalize_collection_id(item.get("collection")) == "l1d-sr":
            return item
        if not self._sat_detail_items:
            return item

        by_outcome = self._sat_detail_index.get("by_outcome", {})
        by_id = self._sat_detail_index.get("by_id", {})
        by_datetime = self._sat_detail_index.get("by_datetime", {})
        by_day = self._sat_detail_index.get("by_day", {})

        outcome = self._item_outcome_key(item)
        if outcome and by_outcome.get(outcome):
            return by_outcome[outcome][0]

        item_id = str(item.get("id") or "").strip()
        if item_id and item_id in by_id:
            return by_id[item_id]

        dt = self._item_datetime_key(item)
        if dt and by_datetime.get(dt):
            return by_datetime[dt][0]
        if dt and len(dt) >= 10 and by_day.get(dt[:10]):
            return by_day[dt[:10]][0]

        target_geom = self._geometry_from_geojson(item.get("geometry") if isinstance(item.get("geometry"), dict) else None)
        if target_geom is not None and not target_geom.isEmpty():
            intersecting = []
            for candidate in self._sat_detail_items:
                candidate_geom_payload = candidate.get("geometry")
                if not isinstance(candidate_geom_payload, dict):
                    continue
                candidate_geom = self._geometry_from_geojson(candidate_geom_payload)
                if candidate_geom is None or candidate_geom.isEmpty():
                    continue
                if candidate_geom.intersects(target_geom):
                    intersecting.append(candidate)
            if intersecting:
                intersecting.sort(key=lambda row: str(row.get("datetime") or "").strip(), reverse=True)
                return intersecting[0]

        return item

    def _refresh_satellogic_detail_pool_for_viewport(self):
        request_payload = self._last_search_request or {}
        if str(request_payload.get("source_id") or "").strip().lower() != "satellogic":
            return
        if self._normalize_collection_id(request_payload.get("collection_id")) == "l1d-sr":
            return

        now = datetime.now(tz=timezone.utc).timestamp()
        if now - float(self._sat_detail_fetch_at or 0.0) < 1.5:
            return

        canvas = self.iface.mapCanvas()
        if canvas is None:
            return
        extent = canvas.extent()
        extent_key = ",".join(
            [
                f"{float(extent.xMinimum()):.4f}",
                f"{float(extent.yMinimum()):.4f}",
                f"{float(extent.xMaximum()):.4f}",
                f"{float(extent.yMaximum()):.4f}",
                str(int(canvas.scale())) if float(canvas.scale() or 0) > 0 else "0",
            ]
        )
        fetch_key = "|".join(
            [
                extent_key,
                str(request_payload.get("start_date") or ""),
                str(request_payload.get("end_date") or ""),
                str(request_payload.get("contract_id") or ""),
            ]
        )
        if fetch_key == self._sat_detail_fetch_key and now - float(self._sat_detail_fetch_at or 0.0) < 10.0:
            return

        detail_request = dict(request_payload)
        detail_request["geometry"] = self._current_extent_geometry_wgs84()
        detail_request["collection_id"] = "l1d-sr"
        detail_request["limit"] = max(300, int(request_payload.get("limit") or 250))

        self._sat_detail_fetch_key = fetch_key
        self._sat_detail_fetch_at = now
        try:
            detail_items = self.source_service.search(detail_request)
            self._sat_detail_items = list(detail_items or [])
            self._rebuild_sat_detail_index()
            if self.dock is not None:
                self.dock.append_search_log(
                    f"Viewport detail refresh (l1d-sr) loaded {len(self._sat_detail_items)} items."
                )
        except Exception as exc:
            if self.dock is not None:
                self.dock.append_search_log(f"Viewport detail refresh failed: {exc}")

    def _current_extent_geometry_wgs84(self):
        canvas = self.iface.mapCanvas()
        extent = canvas.extent()
        src_crs = canvas.mapSettings().destinationCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        extent_wgs84 = extent
        if src_crs.isValid() and src_crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(src_crs, target_crs, QgsProject.instance())
            extent_wgs84 = transform.transformBoundingBox(extent)
        return self.search_controller.extent_to_geometry(extent_wgs84)

    def _render_search_results_layer(self, items):
        self._remove_layer_by_id(self.search_layer_id)
        layer = QgsVectorLayer("MultiPolygon?crs=EPSG:4326", "Image Mate Search Results", "memory")
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("item_id", QVariant.String),
                QgsField("source_id", QVariant.String),
                QgsField("datetime", QVariant.String),
                QgsField("collection", QVariant.String),
                QgsField("cloud", QVariant.Double),
                QgsField("gsd", QVariant.Double),
            ]
        )
        layer.updateFields()

        features = []
        for item in items or []:
            geometry_payload = item.get("geometry")
            if not isinstance(geometry_payload, dict):
                continue
            geom = self._geometry_from_geojson(geometry_payload)
            if geom is None or geom.isEmpty():
                continue
            feat = QgsFeature(layer.fields())
            feat.setGeometry(geom)
            feat.setAttributes(
                [
                    str(item.get("id") or ""),
                    str(item.get("source_id") or ""),
                    str(item.get("datetime") or ""),
                    str(item.get("collection") or ""),
                    float(item.get("cloud_cover")) if item.get("cloud_cover") is not None else None,
                    float(item.get("gsd")) if item.get("gsd") is not None else None,
                ]
            )
            features.append(feat)

        if features:
            provider.addFeatures(features)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        self.search_layer_id = layer.id()

    def _load_item_imagery_layer(self, item):
        source_id = str(item.get("source_id") or "").strip() or None
        contract_id = str(item.get("contract_id") or "").strip() or None
        assets = item.get("assets") or {}
        candidates = [
            ("preview", str(assets.get("preview") or "").strip()),
            ("thumbnail", str(assets.get("thumbnail") or "").strip()),
            ("visual", str(assets.get("visual") or "").strip()),
            ("visual_fullres", str(assets.get("visual_fullres") or "").strip()),
            ("analytic", str(assets.get("analytic") or "").strip()),
        ]
        errors = []
        for key, url in candidates:
            if not url:
                continue
            try:
                data = self.source_service.download_asset(url, source_hint=source_id, contract_id=contract_id)
                path = self._write_temp_asset(item, url, data, preferred_key=key)
                layer_name = self._asset_layer_name(item, key)
                layer = QgsRasterLayer(str(path), layer_name)
                if not layer.isValid():
                    raise RuntimeError(f"QGIS could not open downloaded asset ({path.name})")
                return layer
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                continue
        if errors:
            raise RuntimeError("; ".join(errors))
        raise RuntimeError("No usable imagery assets were available for this item")

    def _write_temp_asset(self, item, url, data, preferred_key):
        item_id = str(item.get("id") or "item").replace(":", "_").replace("/", "_")
        ext = self._guess_asset_extension(url, data)
        file_name = f"{item_id}_{preferred_key}{ext}"
        path = self.temp_dir / file_name
        path.write_bytes(data)
        return path

    def _build_stream_layer_for_item(self, item):
        source_id = str(item.get("source_id") or "").strip().lower()
        if source_id == "merlin-s2":
            layer = self._build_merlin_wmts_stream_layer(item)
            if layer is not None:
                return layer
        if source_id == "satellogic":
            layer = self._build_satellogic_proxy_stream_layer(item)
            if layer is not None:
                return layer
        return None

    def _build_merlin_wmts_stream_layer(self, item):
        base_url = str(self.provider_settings.cdse_wmts_base_url or "").strip().rstrip("/")
        instance_id = str(self.provider_settings.cdse_wmts_instance_id or "").strip()
        layer_id = str(self.provider_settings.cdse_wmts_layer_id or "TRUE-COLOR").strip() or "TRUE-COLOR"
        if not base_url or not instance_id:
            return None

        day = self._item_day(item)
        time_param = f"{day}/{day}" if day else ""
        params = [
            ("SERVICE", "WMTS"),
            ("REQUEST", "GetTile"),
            ("VERSION", "1.0.0"),
            ("LAYER", layer_id),
            ("STYLE", ""),
            ("TILEMATRIXSET", "PopularWebMercator256"),
            ("TILEMATRIX", "{z}"),
            ("TILEROW", "{y}"),
            ("TILECOL", "{x}"),
            ("FORMAT", "image/png"),
        ]
        if time_param:
            params.append(("TIME", time_param))
        query = urlencode(params)
        query = query.replace("%7Bz%7D", "{z}").replace("%7By%7D", "{y}").replace("%7Bx%7D", "{x}")
        xyz_url = f"{base_url}/{instance_id}?{query}"
        layer_name = self._asset_layer_name(item, "wmts")
        layer = self._make_xyz_layer(xyz_url, layer_name, zmin=0, zmax=19)
        return layer if layer is not None and layer.isValid() else None

    def _build_satellogic_proxy_stream_layer(self, item):
        assets = item.get("assets") or {}
        source_url = self._extract_cog_source_url(
            str(assets.get("visual_fullres") or "").strip()
            or str(assets.get("visual") or "").strip()
            or str(assets.get("analytic") or "").strip()
        )
        if not source_url:
            return None
        stream_base = self._satellogic_stream_base_url()
        if not stream_base:
            return None
        scale = self._satellogic_tile_scale()
        contract_id = str(item.get("contract_id") or "").strip() or self.source_service.default_contract_id()
        params = [
            ("url", source_url),
            ("tileMatrixSetId", "WebMercatorQuad"),
            ("format", "png"),
            ("scale", str(scale)),
            ("buffer", "1"),
            ("render_layer", "raw"),
            ("bidx", "1"),
            ("bidx", "2"),
            ("bidx", "3"),
        ]
        if contract_id:
            params.append(("contract_id", contract_id))
        query = urlencode(params, doseq=True, safe=":/")
        is_local_proxy = self.local_tile_proxy.is_running() and stream_base == self.local_tile_proxy.base_url
        if is_local_proxy:
            xyz_url = f"{stream_base}/satellogic/cog/tiles/{{z}}/{{x}}/{{y}}?{query}"
        else:
            base = stream_base.rstrip("/")
            if base.endswith("/api"):
                xyz_url = f"{base}/raster/cog/tiles/{{z}}/{{x}}/{{y}}?{query}"
            else:
                xyz_url = f"{base}/api/raster/cog/tiles/{{z}}/{{x}}/{{y}}?{query}"
        layer_name = self._asset_layer_name(item, "stream")
        layer = self._make_xyz_layer(xyz_url, layer_name, zmin=0, zmax=22)
        return layer if layer is not None and layer.isValid() else None

    @staticmethod
    def _make_xyz_layer(xyz_url, layer_name, zmin=0, zmax=22):
        encoded = quote(str(xyz_url or ""), safe=":/?&=%,{}")
        uri = f"type=xyz&url={encoded}&zmin={int(zmin)}&zmax={int(zmax)}"
        layer = QgsRasterLayer(uri, layer_name, "wms")
        if not layer.isValid():
            return None
        return layer

    def _backend_api_base_url(self):
        return str(getattr(self.provider_settings, "backend_api_base_url", "") or "http://localhost:8000").strip().rstrip("/")

    def _backend_streaming_available(self):
        now = datetime.now(tz=timezone.utc).timestamp()
        checked_at = float(self._backend_health.get("checked_at") or 0.0)
        if now - checked_at < 20.0:
            return bool(self._backend_health.get("ok"))
        base = self._backend_api_base_url()
        ok = False
        try:
            with urlopen(f"{base}/api/health", timeout=1.5) as resp:
                ok = int(getattr(resp, "status", 0)) == 200
        except Exception:
            ok = False
        self._backend_health = {"checked_at": now, "ok": ok}
        return ok

    def _satellogic_stream_base_url(self):
        if self.local_tile_proxy.is_running():
            return self.local_tile_proxy.base_url
        if self._backend_streaming_available():
            return self._backend_api_base_url()
        return ""

    @staticmethod
    def _extract_cog_source_url(raw_url):
        value = str(raw_url or "").strip()
        if not value:
            return ""
        if value.startswith("s3://"):
            return value
        try:
            parsed = urlparse(value)
            source = str((parse_qs(parsed.query or "").get("s") or [""])[0]).strip()
            if source.startswith("s3://"):
                return source
            return value
        except Exception:
            return value

    def _current_canvas_zoom_level(self):
        canvas = self.iface.mapCanvas()
        if canvas is None:
            return None
        try:
            if hasattr(canvas, "zoomLevel"):
                return int(canvas.zoomLevel())
        except Exception:
            return None
        return None

    def _satellogic_tile_scale(self):
        zoom_level = self._current_canvas_zoom_level()
        if zoom_level is None:
            # Conservative default for performance when zoom level is unknown.
            return 1
        return 2 if zoom_level >= int(self._satellogic_highres_zoom_threshold) else 1

    def _is_detail_zoom(self):
        zoom_level = self._current_canvas_zoom_level()
        if zoom_level is not None:
            return zoom_level >= int(self._auto_stream_zoom_threshold)
        canvas = self.iface.mapCanvas()
        if canvas is None:
            return False
        try:
            return float(canvas.scale() or 0.0) <= 250000
        except Exception:
            return False

    def _start_stream_progress_monitor(self, item_id):
        if not self.local_tile_proxy.is_running():
            self._set_stream_status("Stream status: streaming via external backend (progress unavailable)")
            return
        self._stream_progress_active = True
        self._stream_progress_item_id = str(item_id or "").strip()
        self._stream_progress_started_at = datetime.now(tz=timezone.utc).timestamp()
        self._stream_progress_baseline = self.local_tile_proxy.stats_snapshot()
        self._stream_progress_last_tuple = None
        self._stream_progress_idle_ticks = 0
        if not self._stream_progress_timer.isActive():
            self._stream_progress_timer.start()
        self._set_stream_status(f"Stream status: starting tile stream for {self._stream_progress_item_id}")

    def _stop_stream_progress_monitor(self, final_text=None):
        was_active = bool(self._stream_progress_active)
        self._stream_progress_active = False
        self._stream_progress_item_id = ""
        self._stream_progress_started_at = 0.0
        self._stream_progress_baseline = {}
        self._stream_progress_last_tuple = None
        self._stream_progress_idle_ticks = 0
        if self._stream_progress_timer.isActive():
            self._stream_progress_timer.stop()
        if final_text:
            self._set_stream_status(final_text)
        elif was_active:
            self._set_stream_status("Stream status: idle")

    def _poll_stream_progress(self):
        if not self._stream_progress_active:
            self._stop_stream_progress_monitor()
            return
        if not self.local_tile_proxy.is_running():
            self._stop_stream_progress_monitor("Stream status: local proxy unavailable")
            return

        stats = self.local_tile_proxy.stats_snapshot()
        base = self._stream_progress_baseline or {}
        dreq = max(0, int(stats.get("requests_total") or 0) - int(base.get("requests_total") or 0))
        dhit = max(0, int(stats.get("cache_hits") or 0) - int(base.get("cache_hits") or 0))
        dsuccess = max(0, int(stats.get("served_success") or 0) - int(base.get("served_success") or 0))
        dstale = max(0, int(stats.get("served_stale") or 0) - int(base.get("served_stale") or 0))
        derr = max(0, int(stats.get("upstream_errors") or 0) - int(base.get("upstream_errors") or 0))
        inflight = max(0, int(stats.get("inflight") or 0))

        if dreq <= 0:
            self._set_stream_status(f"Stream status: waiting for tile requests ({self._stream_progress_item_id})")
        else:
            self._set_stream_status(
                "Stream status: "
                f"{self._stream_progress_item_id} | tiles={dsuccess} stale={dstale} "
                f"cache_hits={dhit} errors={derr} in_flight={inflight}"
            )

        current_tuple = (dreq, dhit, dsuccess, dstale, derr, inflight)
        if current_tuple == self._stream_progress_last_tuple and inflight == 0 and dreq > 0:
            self._stream_progress_idle_ticks += 1
        else:
            self._stream_progress_idle_ticks = 0
        self._stream_progress_last_tuple = current_tuple

        now = datetime.now(tz=timezone.utc).timestamp()
        if now - float(self._stream_progress_started_at or 0.0) > 90:
            self._stop_stream_progress_monitor(
                f"Stream status: active with slow network ({self._stream_progress_item_id})"
            )
            return
        if dreq > 0 and inflight == 0 and self._stream_progress_idle_ticks >= 2:
            self._stop_stream_progress_monitor(
                "Stream status: complete "
                f"({self._stream_progress_item_id}, tiles={dsuccess}, cache_hits={dhit}, errors={derr})"
            )

    def _on_map_extent_changed(self):
        if not self._auto_stream_enabled:
            return
        if not self.search_items:
            return
        if not self._is_detail_zoom():
            return
        now = datetime.now(tz=timezone.utc).timestamp()
        if now - float(self._last_auto_stream_at or 0.0) < 1.0:
            return
        self._last_auto_stream_at = now
        self._refresh_satellogic_detail_pool_for_viewport()

        item_id = self._latest_visible_item_id()
        if not item_id or item_id == self._last_auto_stream_item_id:
            return
        item = self.search_items.get(item_id)
        if not item:
            return
        stream_item = self._resolve_satellogic_stream_item(item)
        layer = self._build_stream_layer_for_item(stream_item)
        if layer is None:
            return
        self._replace_preview_layer(layer)
        self._last_auto_stream_item_id = item_id
        self._set_stream_status(f"Stream status: auto-streamed latest visible item {item_id}")
        if self.dock is not None:
            self.dock.append_search_log(f"Auto-streamed visible item: {item_id}")

    def _latest_visible_item_id(self):
        extent_geojson = self._current_extent_geometry_wgs84()
        extent_geom = self._geometry_from_geojson(extent_geojson)
        if extent_geom is None or extent_geom.isEmpty():
            return ""
        visible = []
        for item in self.search_items.values():
            geometry_payload = item.get("geometry")
            if not isinstance(geometry_payload, dict):
                continue
            item_geom = self._geometry_from_geojson(geometry_payload)
            if item_geom is None or item_geom.isEmpty():
                continue
            if not item_geom.intersects(extent_geom):
                continue
            item_id = str(item.get("id") or "").strip()
            if item_id:
                visible.append(item)
        if not visible:
            return ""
        visible.sort(key=lambda row: str(row.get("datetime") or "").strip(), reverse=True)
        return str(visible[0].get("id") or "").strip()

    @staticmethod
    def _item_day(item):
        value = str(item.get("datetime") or "").strip()
        if len(value) >= 10:
            return value[:10]
        return ""

    @staticmethod
    def _guess_asset_extension(url, data):
        suffix = Path(urlparse(str(url or "")).path).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".jp2", ".webp"}:
            return suffix
        sample = bytes(data[:16] if data else b"")
        if sample.startswith(b"\x89PNG"):
            return ".png"
        if sample.startswith(b"\xff\xd8"):
            return ".jpg"
        if sample.startswith(b"II*\x00") or sample.startswith(b"MM\x00*"):
            return ".tif"
        if sample.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n") or sample[4:8] == b"jP  ":
            return ".jp2"
        return ".bin"

    @staticmethod
    def _asset_layer_name(item, key):
        source_id = str(item.get("source_id") or "").strip() or "source"
        dt = str(item.get("datetime") or "").strip() or "time"
        item_id = str(item.get("id") or "").strip() or "item"
        return f"Image Mate {source_id} {dt} [{key}] {item_id}"

    def _replace_preview_layer(self, new_layer):
        self._remove_layer_by_id(self.preview_layer_id)
        QgsProject.instance().addMapLayer(new_layer)
        self.preview_layer_id = new_layer.id()

    @staticmethod
    def _remove_layer_by_id(layer_id):
        if not layer_id:
            return
        project = QgsProject.instance()
        layer = project.mapLayer(layer_id)
        if layer is not None:
            project.removeMapLayer(layer_id)

    def _remove_existing_image_mate_layers(self):
        project = QgsProject.instance()
        remove_ids = []
        for layer_id, layer in project.mapLayers().items():
            layer_name = str(layer.name() or "").strip()
            if layer_name.startswith("Image Mate"):
                remove_ids.append(layer_id)
        for layer_id in remove_ids:
            project.removeMapLayer(layer_id)
        self.search_layer_id = None
        self.preview_layer_id = None
        return len(remove_ids)

    @staticmethod
    def _geometry_from_geojson(geometry_payload):
        if not isinstance(geometry_payload, dict):
            return None

        # Prefer native parser when available in current QGIS build.
        try:
            if hasattr(QgsGeometry, "fromGeoJson"):
                parsed = QgsGeometry.fromGeoJson(json.dumps(geometry_payload))
                if parsed is not None and not parsed.isEmpty():
                    return parsed
        except Exception:
            pass

        geom_type = str(geometry_payload.get("type") or "").strip()
        coords = geometry_payload.get("coordinates")

        def pt(pair):
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                return None
            try:
                return QgsPointXY(float(pair[0]), float(pair[1]))
            except Exception:
                return None

        try:
            if geom_type == "Point":
                p = pt(coords)
                return QgsGeometry.fromPointXY(p) if p is not None else None
            if geom_type == "MultiPoint" and isinstance(coords, list):
                pts = [p for p in (pt(row) for row in coords) if p is not None]
                return QgsGeometry.fromMultiPointXY(pts) if pts else None
            if geom_type == "LineString" and isinstance(coords, list):
                line = [p for p in (pt(row) for row in coords) if p is not None]
                return QgsGeometry.fromPolylineXY(line) if len(line) >= 2 else None
            if geom_type == "MultiLineString" and isinstance(coords, list):
                lines = []
                for row in coords:
                    if not isinstance(row, list):
                        continue
                    line = [p for p in (pt(pair) for pair in row) if p is not None]
                    if len(line) >= 2:
                        lines.append(line)
                return QgsGeometry.fromMultiPolylineXY(lines) if lines else None
            if geom_type == "Polygon" and isinstance(coords, list):
                rings = []
                for ring in coords:
                    if not isinstance(ring, list):
                        continue
                    pts = [p for p in (pt(pair) for pair in ring) if p is not None]
                    if len(pts) >= 3:
                        rings.append(pts)
                return QgsGeometry.fromPolygonXY(rings) if rings else None
            if geom_type == "MultiPolygon" and isinstance(coords, list):
                polys = []
                for poly in coords:
                    if not isinstance(poly, list):
                        continue
                    rings = []
                    for ring in poly:
                        if not isinstance(ring, list):
                            continue
                        pts = [p for p in (pt(pair) for pair in ring) if p is not None]
                        if len(pts) >= 3:
                            rings.append(pts)
                    if rings:
                        polys.append(rings)
                return QgsGeometry.fromMultiPolygonXY(polys) if polys else None
        except Exception:
            return None
        return None

    @staticmethod
    def _log_info(message):
        QgsMessageLog.logMessage(message, "ImageMate", Qgis.Info)
