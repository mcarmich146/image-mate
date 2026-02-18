# -*- coding: utf-8 -*-
"""Main plugin wiring for Image Mate."""

from pathlib import Path
import json
import tempfile
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import urlopen
import math
import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtCore import QStandardPaths
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import (
    QgsApplication,
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsRasterLayer,
    QgsVectorLayer,
)

from .controllers.search_controller import SearchController
from .services.auth_service import AuthService
from .services.local_tile_proxy import LocalTileProxy
from .services.settings_service import SettingsService
from .services.source_service import SourceService
from .services.streaming_utils import (
    build_satellogic_xyz_url,
    extract_cog_source_url,
    satellogic_item_cog_source_url,
)
from .ui.main_dock import ImageMateMainDock


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
            self.dock.result_selected.connect(self.handle_result_selected)
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
            f"Debug log file: {self._disk_log_path or 'not initialized'}",
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

    def _append_search_log(self, text, level=Qgis.Info):
        message = str(text or "").strip()
        if not message:
            return
        self._write_disk_log(message, level=level, tag="search")
        if self._show_search_log_on_screen and self.dock is not None:
            self.dock.append_search_log(message)

    def _append_debug_log(self, text, level=Qgis.Info):
        message = str(text or "").strip()
        if not message:
            return
        self._write_disk_log(message, level=level, tag="debug")

    def _init_disk_log(self):
        if self._disk_log_fp is not None:
            return
        base_dir = str(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or "").strip()
        if not base_dir:
            base_dir = str(self.temp_dir)
        log_dir = Path(base_dir) / "image_mate_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = log_dir / f"image_mate_qgis_{stamp}.log"
        self._disk_log_fp = log_path.open("a", encoding="utf-8")
        self._disk_log_path = str(log_path)
        self._prune_disk_logs(log_dir, keep_count=20)
        self._write_disk_log("disk log initialized", level=Qgis.Info, tag="plugin")

    def _close_disk_log(self):
        fp = self._disk_log_fp
        self._disk_log_fp = None
        if fp is None:
            return
        try:
            fp.flush()
        except Exception:
            pass
        try:
            fp.close()
        except Exception:
            pass

    @staticmethod
    def _prune_disk_logs(log_dir, keep_count=20):
        try:
            files = sorted(
                [path for path in Path(log_dir).glob("image_mate_qgis_*.log") if path.is_file()],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for stale in files[int(max(1, keep_count)):]:
                try:
                    stale.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    @staticmethod
    def _level_name(level):
        try:
            value = int(level)
        except Exception:
            return "INFO"
        if value == int(Qgis.Warning):
            return "WARN"
        if value == int(Qgis.Critical):
            return "CRIT"
        if value == int(Qgis.Success):
            return "OK"
        return "INFO"

    def _write_disk_log(self, message, *, level=Qgis.Info, tag="plugin"):
        text = str(message or "").rstrip()
        if not text:
            return
        if self._disk_log_fp is None:
            try:
                self._init_disk_log()
            except Exception:
                return
        now = datetime.now(tz=timezone.utc).isoformat()
        level_name = self._level_name(level)
        safe_tag = str(tag or "plugin").strip() or "plugin"
        line = f"{now} [{level_name}] [{safe_tag}] {text}"
        try:
            self._disk_log_fp.write(line + "\n")
            self._disk_log_fp.flush()
        except Exception:
            pass

        if self.dock is not None:
            try:
                self.dock.append_debug_log(line)
            except Exception:
                pass

    def _on_qgis_message_logged(self, message, tag, level):
        source_tag = str(tag or "").strip() or "qgis"
        # Capture actionable warnings/errors and WMS diagnostics to disk for offline debugging.
        if source_tag == "ImageMate":
            return
        keep = source_tag == "WMS"
        if not keep:
            try:
                keep = int(level) >= int(Qgis.Warning)
            except Exception:
                keep = False
        if keep:
            self._write_disk_log(str(message or "").strip(), level=level, tag=source_tag)

    def _on_local_proxy_event(self, message, level="info"):
        text = str(message or "").strip()
        if not text:
            return
        lvl = Qgis.Warning if str(level).strip().lower() in {"warn", "warning", "error", "critical"} else Qgis.Info
        self._write_disk_log(text, level=lvl, tag="local-proxy")

    @staticmethod
    def _normalize_collection_id(collection_id):
        return str(collection_id or "").strip().lower().replace("_", "-")

    @classmethod
    def _is_strip_collection(cls, collection_id):
        normalized = cls._normalize_collection_id(collection_id)
        return normalized in {"quickview-visual-thumb"}

    @staticmethod
    def _item_outcome_key(item):
        return str(item.get("outcome_id") or "").strip()

    @staticmethod
    def _item_datetime_key(item):
        value = str(item.get("datetime") or "").strip()
        return value[:19] if len(value) >= 19 else value

    @staticmethod
    def _item_capture_key(item):
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            return ""
        match = re.search(r"(\d{8}_\d{6}_\d+_SN\d+)", item_id)
        return str(match.group(1)) if match else ""

    def _search_with_satellogic_detail_parity(self, request_payload):
        source_id = str(request_payload.get("source_id") or "").strip().lower()
        if source_id != "satellogic":
            self._sat_detail_items = []
            self._sat_detail_index = {"by_id": {}, "by_outcome": {}, "by_datetime": {}, "by_day": {}}
            self._sat_detail_fetch_key = ""
            self._sat_detail_fetch_at = 0.0
            self._sat_capture_group_fetch_state = {}
            return self.source_service.search(request_payload)

        primary_items = self.source_service.search(request_payload)
        primary_collection = self._normalize_collection_id(request_payload.get("collection_id"))
        detail_items = []
        if primary_collection == "l1d-sr":
            detail_items = list(primary_items)
        elif self._is_strip_collection(primary_collection):
            detail_items = []
        else:
            detail_request = dict(request_payload)
            detail_request["collection_id"] = "l1d-sr"
            detail_request["limit"] = max(300, int(request_payload.get("limit") or 250))
            try:
                detail_items = self.source_service.search(detail_request)
                self._append_search_log(
                    f"Detail parity fetch (l1d-sr) returned {len(detail_items)} items for streaming."
                )
            except Exception as exc:
                detail_items = []
                self._append_search_log(
                    f"Detail parity fetch (l1d-sr) failed, using primary collection only: {exc}",
                    level=Qgis.Warning,
                )

        self._sat_detail_items = list(detail_items or [])
        self._rebuild_sat_detail_index()
        self._sat_detail_fetch_key = ""
        self._sat_detail_fetch_at = 0.0
        self._sat_capture_group_fetch_state = {}
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
        if self._is_strip_collection(item.get("collection")):
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

    def _satellogic_detail_candidates_for_item(self, item):
        if not isinstance(item, dict):
            return []
        if str(item.get("source_id") or "").strip().lower() != "satellogic":
            return []
        if self._is_strip_collection(item.get("collection")):
            return []
        if not self._sat_detail_items:
            return []

        # Get the collection from the item to filter candidates
        item_collection = self._normalize_collection_id(item.get("collection"))

        by_outcome = self._sat_detail_index.get("by_outcome", {})
        by_datetime = self._sat_detail_index.get("by_datetime", {})

        candidates = []

        outcome = self._item_outcome_key(item)
        if outcome and by_outcome.get(outcome):
            candidates = list(by_outcome.get(outcome) or [])
        else:
            dt = self._item_datetime_key(item)
            if dt and by_datetime.get(dt):
                candidates = list(by_datetime.get(dt) or [])

        if item_collection == "l1d-sr":
            self._enrich_l1d_sr_capture_group(item, candidates)
            by_outcome = self._sat_detail_index.get("by_outcome", {})
            by_datetime = self._sat_detail_index.get("by_datetime", {})
            if outcome and by_outcome.get(outcome):
                candidates = list(by_outcome.get(outcome) or [])
            elif not candidates:
                dt = self._item_datetime_key(item)
                if dt and by_datetime.get(dt):
                    candidates = list(by_datetime.get(dt) or [])

        # Filter candidates to only include items from the same collection
        if candidates and item_collection:
            candidates = [
                c for c in candidates
                if self._normalize_collection_id(c.get("collection")) == item_collection
            ]

        return candidates

    def _enrich_l1d_sr_capture_group(self, item, seed_candidates):
        if self._normalize_collection_id(item.get("collection")) != "l1d-sr":
            return

        outcome = self._item_outcome_key(item)
        capture_key = self._item_capture_key(item)
        group_key = f"outcome:{outcome}" if outcome else (f"capture:{capture_key}" if capture_key else "")
        if not group_key:
            return
        if self._sat_capture_group_fetch_state.get(group_key):
            return
        self._sat_capture_group_fetch_state[group_key] = True

        seed_items = list(seed_candidates or [])
        if not seed_items:
            seed_items = [item]
        rect = self._satellogic_extent_from_items(seed_items)
        if rect is None or rect.isEmpty():
            self._append_debug_log(
                f"L1D SR capture-group enrichment skipped for {group_key}: no seed extent (seed_items={len(seed_items)}).",
                level=Qgis.Warning,
            )
            return

        try:
            minx = float(rect.xMinimum())
            miny = float(rect.yMinimum())
            maxx = float(rect.xMaximum())
            maxy = float(rect.yMaximum())
        except Exception:
            return
        width = max(1e-6, maxx - minx)
        height = max(1e-6, maxy - miny)
        pad_x = max(width * 2.0, 0.02)
        pad_y = max(height * 2.0, 0.02)
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [minx - pad_x, miny - pad_y],
                [maxx + pad_x, miny - pad_y],
                [maxx + pad_x, maxy + pad_y],
                [minx - pad_x, maxy + pad_y],
                [minx - pad_x, miny - pad_y],
            ]],
        }

        detail_request = dict(self._last_search_request or {})
        detail_request["source_id"] = "satellogic"
        detail_request["collection_id"] = "l1d-sr"
        detail_request["geometry"] = geometry
        detail_request["limit"] = max(500, int(detail_request.get("limit") or 250))

        item_contract = str(item.get("contract_id") or "").strip()
        if item_contract and not str(detail_request.get("contract_id") or "").strip():
            detail_request["contract_id"] = item_contract

        dt_value = str(item.get("datetime") or "").strip()
        if dt_value:
            try:
                parsed_dt = datetime.fromisoformat(dt_value.replace("Z", "+00:00"))
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
                parsed_dt = parsed_dt.astimezone(timezone.utc)
                detail_request["start_date"] = (parsed_dt - timedelta(minutes=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
                detail_request["end_date"] = (parsed_dt + timedelta(minutes=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass

        try:
            fetched = self.source_service.search(detail_request)
        except Exception as exc:
            self._append_debug_log(
                f"L1D SR capture-group enrichment failed for {group_key}: {exc}",
                level=Qgis.Warning,
            )
            return

        matched = []
        for row in fetched or []:
            if not isinstance(row, dict):
                continue
            if outcome and self._item_outcome_key(row) == outcome:
                matched.append(row)
                continue
            if capture_key and self._item_capture_key(row) == capture_key:
                matched.append(row)

        if not matched:
            self._append_debug_log(
                f"L1D SR capture-group enrichment for {group_key}: fetched={len(fetched or [])} matched=0 added=0."
            )
            return

        existing_ids = {str(row.get("id") or "").strip() for row in self._sat_detail_items or []}
        added = 0
        for row in matched:
            row_id = str(row.get("id") or "").strip()
            if not row_id or row_id in existing_ids:
                continue
            self._sat_detail_items.append(row)
            existing_ids.add(row_id)
            added += 1

        if added > 0:
            self._rebuild_sat_detail_index()
            self._append_debug_log(
                f"Expanded L1D SR capture group {group_key}: +{added} strip(s), total={len(matched)}."
            )
        else:
            self._append_debug_log(
                f"L1D SR capture-group enrichment for {group_key}: fetched={len(fetched or [])} matched={len(matched)} added=0."
            )

    def _satellogic_item_cog_source_url(self, item):
        return satellogic_item_cog_source_url(item)

    def _satellogic_stream_sources_and_items(self, stream_item, overview_item=None):
        if str(stream_item.get("source_id") or "").strip().lower() != "satellogic":
            return [], []

        urls = []
        seen = set()
        items = []
        seen_items = set()
        item_sources = []

        def append_from(candidate):
            if not isinstance(candidate, dict):
                return
            item_id = str(candidate.get("id") or "").strip()
            if item_id and item_id not in seen_items:
                seen_items.add(item_id)
                items.append(candidate)
            source_url = self._satellogic_item_cog_source_url(candidate)
            if source_url and source_url not in seen:
                seen.add(source_url)
                urls.append(source_url)
                item_sources.append((candidate, source_url))

        append_from(stream_item)
        if isinstance(overview_item, dict):
            if self._normalize_collection_id(overview_item.get("collection")) == self._normalize_collection_id(
                stream_item.get("collection")
            ):
                append_from(overview_item)

        candidates = self._satellogic_detail_candidates_for_item(overview_item if isinstance(overview_item, dict) else stream_item)
        if not candidates and isinstance(overview_item, dict):
            candidates = self._satellogic_detail_candidates_for_item(stream_item)

        if candidates:
            extent_geom = self._geometry_from_geojson(self._current_extent_geometry_wgs84())
            intersecting = []
            others = []
            for candidate in candidates:
                geom_payload = candidate.get("geometry")
                candidate_geom = self._geometry_from_geojson(geom_payload) if isinstance(geom_payload, dict) else None
                if (
                    extent_geom is not None
                    and not extent_geom.isEmpty()
                    and candidate_geom is not None
                    and not candidate_geom.isEmpty()
                    and candidate_geom.intersects(extent_geom)
                ):
                    intersecting.append(candidate)
                else:
                    others.append(candidate)
            for candidate in intersecting + others:
                append_from(candidate)

        configured_max_sources = max(1, int(self._satellogic_max_stream_sources or 1))
        is_l1d_sr_stream = self._normalize_collection_id(stream_item.get("collection")) == "l1d-sr"
        max_sources = len(urls) if is_l1d_sr_stream else configured_max_sources
        if len(urls) > max_sources:
            self._append_debug_log(
                f"Capped Satellogic stream candidates from {len(urls)} to {max_sources} for responsive tile loading."
            )
            urls = urls[:max_sources]
        elif is_l1d_sr_stream and len(urls) > configured_max_sources:
            self._append_debug_log(
                f"Bypassed source cap for l1d-sr coverage: using {len(urls)} strips (cap={configured_max_sources})."
            )

        if item_sources and urls:
            url_set = set(urls)
            items = [item for item, source in item_sources if source in url_set]

        return urls, items

    def _satellogic_stream_source_urls(self, stream_item, overview_item=None):
        urls, _items = self._satellogic_stream_sources_and_items(stream_item, overview_item=overview_item)
        return urls

    def _satellogic_extent_from_items(self, items):
        if not items:
            return None
        rect = None
        for item in items:
            if self._normalize_collection_id(item.get("collection")) == "l1d-sr":
                raster_rect = self._raster_bounds_rect_wgs84(item)
                if raster_rect is not None and not raster_rect.isEmpty():
                    if rect is None:
                        rect = QgsRectangle(raster_rect)
                    else:
                        rect.combineExtentWith(raster_rect)
                    continue
            geom_payload = item.get("geometry")
            if not isinstance(geom_payload, dict):
                continue
            geom = self._geometry_from_geojson(geom_payload)
            if geom is None or geom.isEmpty():
                continue
            bbox = geom.boundingBox()
            if rect is None:
                rect = QgsRectangle(bbox)
            else:
                rect.combineExtentWith(bbox)
        return rect

    def _raster_bounds_rect_wgs84(self, item):
        raw = item.get("raw") if isinstance(item, dict) else None
        if not isinstance(raw, dict):
            return None
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        shape = props.get("proj:shape") or raw.get("proj:shape")
        transform = props.get("proj:transform") or raw.get("proj:transform")
        epsg = props.get("proj:epsg") or raw.get("proj:epsg")
        if not shape or not transform or not epsg:
            return None
        if not isinstance(shape, (list, tuple)) or len(shape) < 2:
            return None
        if not isinstance(transform, (list, tuple)) or len(transform) < 6:
            return None
        try:
            height = int(shape[0])
            width = int(shape[1])
            if width <= 0 or height <= 0:
                return None
            a, b, c, d, e, f = (float(val) for val in transform[:6])
            x0 = c
            y0 = f
            x1 = (a * width) + (b * height) + c
            y1 = (d * width) + (e * height) + f
            minx = min(x0, x1)
            maxx = max(x0, x1)
            miny = min(y0, y1)
            maxy = max(y0, y1)
            src_crs = QgsCoordinateReferenceSystem(f"EPSG:{int(epsg)}")
            if not src_crs.isValid():
                return None
            rect = QgsRectangle(minx, miny, maxx, maxy)
            transform_ctx = QgsCoordinateTransform(src_crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
            return transform_ctx.transformBoundingBox(rect)
        except Exception:
            return None

    @staticmethod
    def _tile_xy_float(lat: float, lon: float, zoom: int) -> tuple[float, float]:
        n = 2 ** zoom
        x_float = (lon + 180.0) / 360.0 * n
        lat = max(-85.05112878, min(85.05112878, lat))
        lat_rad = math.radians(lat)
        y_float = (1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * n
        return x_float, y_float

    @staticmethod
    def _tile_x_to_lon(tile_x: float, zoom: int) -> float:
        n = 2 ** zoom
        return (float(tile_x) / n) * 360.0 - 180.0

    @staticmethod
    def _tile_y_to_lat(tile_y: float, zoom: int) -> float:
        n = 2 ** zoom
        y = float(tile_y)
        lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
        return math.degrees(lat_rad)

    def _snap_extent_to_tile_grid(self, rect, zoom: int):
        if rect is None:
            return None
        try:
            minx = float(rect.xMinimum())
            maxx = float(rect.xMaximum())
            miny = float(rect.yMinimum())
            maxy = float(rect.yMaximum())
        except Exception:
            return rect

        x_min_f, y_min_f = self._tile_xy_float(maxy, minx, zoom)
        x_max_f, y_max_f = self._tile_xy_float(miny, maxx, zoom)

        # Snap min edges inward; keep max edges inclusive.
        x_min = math.floor(min(x_min_f, x_max_f))
        x_max = math.ceil(max(x_min_f, x_max_f))
        y_min = math.floor(min(y_min_f, y_max_f))
        y_max = math.ceil(max(y_min_f, y_max_f))

        # Expand by one tile to avoid edge gaps caused by rounding/coverage jitter.
        n = 2 ** int(zoom)
        pad = 1
        x_min = max(0, x_min - pad)
        y_min = max(0, y_min - pad)
        x_max = min(n, x_max + pad)
        y_max = min(n, y_max + pad)

        log_key = f"{int(zoom)}:{minx:.6f}:{miny:.6f}:{maxx:.6f}:{maxy:.6f}"
        if log_key != self._last_snap_log_key:
            self._last_snap_log_key = log_key
            self._append_debug_log(
                "Snap extent: "
                f"zoom={int(zoom)} x_f=({x_min_f:.3f},{x_max_f:.3f}) y_f=({y_min_f:.3f},{y_max_f:.3f}) "
                f"tiles=({x_min},{x_max})/({y_min},{y_max})"
            )

        if x_min >= x_max or y_min >= y_max:
            return rect

        snapped_minx = self._tile_x_to_lon(x_min, zoom)
        snapped_maxx = self._tile_x_to_lon(x_max, zoom)
        snapped_maxy = self._tile_y_to_lat(y_min, zoom)
        snapped_miny = self._tile_y_to_lat(y_max, zoom)

        rect.setXMinimum(snapped_minx)
        rect.setXMaximum(snapped_maxx)
        rect.setYMinimum(snapped_miny)
        rect.setYMaximum(snapped_maxy)
        return rect

    def _apply_stream_layer_extent(self, layer, items):
        if layer is None or not items:
            return
        rect = self._satellogic_extent_from_items(items)
        if rect is None:
            return
        zoom_level = self._current_canvas_zoom_level()
        if zoom_level is not None:
            rect = self._snap_extent_to_tile_grid(rect, zoom_level)
        src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        dst_crs = layer.crs() if layer.crs().isValid() else QgsCoordinateReferenceSystem("EPSG:3857")
        try:
            transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            rect = transform.transformBoundingBox(rect)
        except Exception:
            return
        layer.setExtent(rect)

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
            self._append_search_log(
                f"Viewport detail refresh (l1d-sr) loaded {len(self._sat_detail_items)} items."
            )
        except Exception as exc:
            self._append_search_log(f"Viewport detail refresh failed: {exc}", level=Qgis.Warning)

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

    def _extract_bounds_summary(self, geometry):
        """Extract a human-readable bounds summary from a GeoJSON geometry."""
        if not isinstance(geometry, dict):
            return "invalid geometry"
        try:
            coords = geometry.get("coordinates", [])
            if not coords:
                return "no coordinates"
            
            # Extract all coordinate pairs
            lons, lats = [], []
            def extract_coords(obj):
                if isinstance(obj, list):
                    if len(obj) >= 2 and isinstance(obj[0], (int, float)) and isinstance(obj[1], (int, float)):
                        lons.append(obj[0])
                        lats.append(obj[1])
                    else:
                        for item in obj:
                            extract_coords(item)
            extract_coords(coords)
            
            if not lons or not lats:
                return "no valid coordinates"
            
            min_lon, max_lon = min(lons), max(lons)
            min_lat, max_lat = min(lats), max(lats)
            center_lon = (min_lon + max_lon) / 2
            center_lat = (min_lat + max_lat) / 2
            
            return f"[{min_lon:.6f}, {min_lat:.6f}] to [{max_lon:.6f}, {max_lat:.6f}] (center: {center_lat:.6f}, {center_lon:.6f})"
        except Exception:
            return "bounds extraction failed"

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

    def _build_stream_layer_for_item(self, item, source_urls=None, source_items=None):
        source_id = str(item.get("source_id") or "").strip().lower()
        if source_id == "merlin-s2":
            layer = self._build_merlin_wmts_stream_layer(item)
            if layer is not None:
                return layer
        if source_id == "satellogic":
            layer = self._build_satellogic_proxy_stream_layer(
                item,
                source_urls=source_urls,
                source_items=source_items,
            )
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

    def _build_satellogic_proxy_stream_layer(self, item, source_urls=None, source_items=None):
        resolved_sources = []
        seen_sources = set()

        for value in source_urls or []:
            source = self._extract_cog_source_url(str(value or "").strip())
            if source and source not in seen_sources:
                seen_sources.add(source)
                resolved_sources.append(source)

        if not resolved_sources:
            source = self._satellogic_item_cog_source_url(item)
            if source:
                resolved_sources.append(source)

        if not resolved_sources:
            return None

        stream_base = self._satellogic_stream_base_url()
        if len(resolved_sources) > 1 and self.local_tile_proxy.is_running():
            stream_base = self.local_tile_proxy.base_url
        if len(resolved_sources) > 1 and stream_base != self.local_tile_proxy.base_url:
            resolved_sources = resolved_sources[:1]
        if not stream_base:
            return None
        scale = self._satellogic_tile_scale()
        raw_contract_id = str(item.get("contract_id") or "").strip() or self.source_service.default_contract_id()
        contract_id = self.source_service.resolve_contract_id(raw_contract_id)
        params = [
            ("tileMatrixSetId", "WebMercatorQuad"),
            ("format", "png"),
            ("scale", str(scale)),
            ("buffer", "1"),
            ("render_layer", "raw"),
            ("bidx", "1"),
            ("bidx", "2"),
            ("bidx", "3"),
        ]
        for source in resolved_sources:
            params.append(("url", source))
        if contract_id:
            params.append(("contract_id", contract_id))
        query = urlencode(params, doseq=True, safe=":/")
        # QGIS datasource URI parsing splits on '&' at the provider URI level.
        # Escape nested query separators so they remain inside the XYZ URL value.
        query = query.replace("&", "%26")
        is_local_proxy = self.local_tile_proxy.is_running() and stream_base == self.local_tile_proxy.base_url
        if is_local_proxy:
            xyz_url = f"{stream_base}/satellogic/cog/tiles/{{z}}/{{x}}/{{y}}?{query}"
        else:
            base = stream_base.rstrip("/")
            if base.endswith("/api"):
                xyz_url = f"{base}/raster/cog/tiles/{{z}}/{{x}}/{{y}}?{query}"
            else:
                xyz_url = f"{base}/api/raster/cog/tiles/{{z}}/{{x}}/{{y}}?{query}"
        setup_key = "|".join(
            [
                str(stream_base),
                str(scale),
                str(contract_id or ""),
                f"{len(resolved_sources)}:{resolved_sources[0]}:{resolved_sources[-1]}",
                "local" if is_local_proxy else "backend",
            ]
        )
        if setup_key != self._stream_last_setup_key:
            self._stream_last_setup_key = setup_key
            source_short = resolved_sources[0]
            if len(source_short) > 180:
                source_short = f"{source_short[:180]}..."
            self._append_debug_log(
                "Tile stream setup: "
                f"mode={'local_proxy' if is_local_proxy else 'backend_proxy'} "
                f"base={stream_base} scale={scale} contract={'set' if contract_id else 'missing'} "
                f"sources={len(resolved_sources)} source={source_short}"
            )
        layer_name = self._asset_layer_name(item, "stream")
        layer = self._make_xyz_layer(xyz_url, layer_name, zmin=0, zmax=22)
        if layer is None or not layer.isValid():
            return None
        self._apply_stream_layer_extent(layer, source_items or [item])
        return layer

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
        # Keep parity with working frontend path: prefer backend COG tile proxy first.
        if self._backend_streaming_available():
            return self._backend_api_base_url()
        if self.local_tile_proxy.is_running():
            return self.local_tile_proxy.base_url
        return ""

    @staticmethod
    def _extract_cog_source_url(raw_url):
        return extract_cog_source_url(raw_url)

    def _current_canvas_zoom_level(self):
        canvas = self.iface.mapCanvas()
        if canvas is None:
            return None
        try:
            map_settings = canvas.mapSettings()
            units_per_pixel = float(getattr(map_settings, "mapUnitsPerPixel", lambda: 0.0)() or 0.0)
            extent = map_settings.extent()
            if extent.isEmpty():
                return None
            if units_per_pixel <= 0:
                output_size = map_settings.outputSize()
                width_px = max(1, int(output_size.width()))
                height_px = max(1, int(output_size.height()))
                units_per_pixel = max(extent.width() / width_px, extent.height() / height_px)
            if units_per_pixel <= 0:
                return None
            crs = map_settings.destinationCrs()
            meters_per_pixel = units_per_pixel
            if crs.isValid() and crs.authid() == "EPSG:4326":
                center_lat = extent.center().y()
                meters_per_degree = 111319.49079327357 * math.cos(math.radians(center_lat))
                meters_per_pixel = units_per_pixel * max(1e-9, abs(meters_per_degree))
            zoom = math.log(156543.03392804097 / meters_per_pixel, 2)
            if not math.isfinite(zoom):
                return None
            return int(round(zoom))
        except Exception:
            return None

    def _satellogic_tile_scale(self):
        zoom_level = self._current_canvas_zoom_level()
        if zoom_level is None:
            return 1
        return 2 if zoom_level >= int(self._satellogic_highres_zoom_threshold or 17) else 1

    def _is_detail_zoom(self):
        zoom_level = self._current_canvas_zoom_level()
        if zoom_level is None:
            return False
        return zoom_level >= int(self._auto_stream_zoom_threshold or 13)

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
        self._stream_progress_last_summary_key = ""
        self._stream_progress_last_summary_at = 0.0
        self._stream_progress_last_error_key = ""
        self._stream_progress_last_error_at = 0.0
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
        self._stream_progress_last_summary_key = ""
        self._stream_progress_last_summary_at = 0.0
        self._stream_progress_last_error_key = ""
        self._stream_progress_last_error_at = 0.0
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
        dempty = max(0, int(stats.get("served_empty") or 0) - int(base.get("served_empty") or 0))
        dstale = max(0, int(stats.get("served_stale") or 0) - int(base.get("served_stale") or 0))
        derr = max(0, int(stats.get("upstream_errors") or 0) - int(base.get("upstream_errors") or 0))
        inflight = max(0, int(stats.get("inflight") or 0))
        last_status = int(stats.get("last_status") or 0)
        last_error = str(stats.get("last_error") or "").strip()

        if dreq <= 0:
            self._set_stream_status(f"Stream status: waiting for tile requests ({self._stream_progress_item_id})")
        else:
            self._set_stream_status(
                "Stream status: "
                f"{self._stream_progress_item_id} | tiles={dsuccess} empty={dempty} stale={dstale} "
                f"cache_hits={dhit} errors={derr} in_flight={inflight}"
            )

        current_tuple = (dreq, dhit, dsuccess, dempty, dstale, derr, inflight)
        if current_tuple == self._stream_progress_last_tuple and inflight == 0 and dreq > 0:
            self._stream_progress_idle_ticks += 1
        else:
            self._stream_progress_idle_ticks = 0
        self._stream_progress_last_tuple = current_tuple

        now = datetime.now(tz=timezone.utc).timestamp()
        summary_key = f"{dreq}|{dhit}|{dsuccess}|{dempty}|{dstale}|{derr}|{inflight}"
        if dreq > 0 and (
            summary_key != self._stream_progress_last_summary_key
            and now - float(self._stream_progress_last_summary_at or 0.0) >= 2.5
        ):
            self._stream_progress_last_summary_key = summary_key
            self._stream_progress_last_summary_at = now
            self._append_debug_log(
                "Tile stream progress: "
                f"item={self._stream_progress_item_id} requests={dreq} success={dsuccess} empty={dempty} "
                f"stale={dstale} cache_hits={dhit} errors={derr} inflight={inflight}"
            )

        if last_error:
            error_key = f"{last_status}|{last_error}|{derr}|{dempty}"
            if (
                error_key != self._stream_progress_last_error_key
                or now - float(self._stream_progress_last_error_at or 0.0) >= 8.0
            ):
                self._stream_progress_last_error_key = error_key
                self._stream_progress_last_error_at = now
                self._append_debug_log(
                    "Tile stream diagnostic: "
                    f"item={self._stream_progress_item_id} last_status={last_status} last_error={last_error} "
                    f"errors={derr} empty={dempty}",
                    level=Qgis.Warning,
                )

        if now - float(self._stream_progress_started_at or 0.0) > 90:
            self._stop_stream_progress_monitor(
                f"Stream status: active with slow network ({self._stream_progress_item_id})"
            )
            return
        if dreq > 0 and inflight == 0 and self._stream_progress_idle_ticks >= 2:
            self._stop_stream_progress_monitor(
                "Stream status: complete "
                f"({self._stream_progress_item_id}, tiles={dsuccess}, empty={dempty}, cache_hits={dhit}, errors={derr})"
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
        stream_source_urls, stream_source_items = self._satellogic_stream_sources_and_items(
            stream_item,
            overview_item=item,
        )
        layer = self._build_stream_layer_for_item(
            stream_item,
            source_urls=stream_source_urls,
            source_items=stream_source_items,
        )
        if layer is None:
            return
        self._replace_preview_layer(layer)
        self._last_auto_stream_item_id = item_id
        self._set_stream_status(f"Stream status: auto-streamed latest visible item {item_id}")
        self._append_search_log(f"Auto-streamed visible item: {item_id}")

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

    def _replace_preview_layer(self, new_layer, *, replace_existing=True):
        if replace_existing:
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

    def _log_info(self, message):
        self._write_disk_log(str(message or "").strip(), level=Qgis.Info, tag="plugin")
        if self._show_debug_on_screen:
            QgsMessageLog.logMessage(str(message or "").strip(), "ImageMate", Qgis.Info)
