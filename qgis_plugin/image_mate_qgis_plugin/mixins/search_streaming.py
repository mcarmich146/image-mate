# -*- coding: utf-8 -*-
"""Search, streaming, and map/layer helper mixin for Image Mate plugin."""

from pathlib import Path
import json
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen
import math
import re

from qgis.PyQt.QtCore import QStandardPaths
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtGui import QImage
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFillSymbol,
    QgsField,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)

from ..services.streaming_utils import (
    build_satellogic_xyz_url,
    extract_cog_source_url,
    satellogic_item_cog_source_url,
)


class SearchStreamingMixin:
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
        source_norm = str(source_id or "").strip().lower()
        self.dock.set_collections(self.source_service.list_collections(source_id))
        self.dock.set_contract_enabled(source_norm == "satellogic")
        if hasattr(self.dock, "min_coverage_filter_combo"):
            combo = self.dock.min_coverage_filter_combo
            mode = str(combo.currentData() or "").strip().lower()
            if source_norm == "merlin-s2" and mode == "full":
                half_index = int(combo.findData("half"))
                if half_index >= 0:
                    combo.setCurrentIndex(half_index)
                self._append_search_log(
                    "Coverage filter auto-adjusted to Half Coverage for Sentinel-2. "
                    "Use overlap results for tile-based collections.",
                    level=Qgis.Info,
                )
            combo.setToolTip(
                "Minimum AOI coverage required per result. "
                "Touching disables overlap threshold; Half Coverage keeps at least 50% AOI overlap."
            )
        elif hasattr(self.dock, "require_full_aoi_overlap"):
            if source_norm == "merlin-s2" and bool(self.dock.require_full_aoi_overlap.isChecked()):
                self.dock.require_full_aoi_overlap.setChecked(False)
                self._append_search_log(
                    "Coverage filter auto-disabled for Sentinel-2. "
                    "Use overlap results for tile-based collections.",
                    level=Qgis.Info,
                )
            self.dock.require_full_aoi_overlap.setToolTip(
                "When enabled, search results must fully contain the current AOI. "
                "Sentinel-2 typically works better with this disabled."
            )
        if source_norm == "merlin-s2" and hasattr(self.dock, "max_gsd"):
            try:
                current_max_gsd = float(self.dock.max_gsd.value() or 0.0)
            except Exception:
                current_max_gsd = 0.0
            if 0.0 < current_max_gsd < 10.0:
                self.dock.max_gsd.setValue(0.0)
                self._append_search_log(
                    "Max Resolution filter reset to 'none' for Sentinel-2 "
                    "(values below 10 m/px can exclude all Sentinel-2 scenes).",
                    level=Qgis.Info,
                )
        if hasattr(self, "handle_tasking_refresh_request"):
            try:
                self.handle_tasking_refresh_request()
            except Exception:
                pass
        if hasattr(self, "handle_mosaic_refresh_projects_request"):
            try:
                self.handle_mosaic_refresh_projects_request()
            except Exception:
                pass
        if hasattr(self, "handle_monitoring_refresh_request"):
            try:
                self.handle_monitoring_refresh_request({"source_id": source_id})
            except Exception:
                pass

    def _runtime_summary_text(self, extra_line=None):
        runtime = self.source_service.runtime_summary()
        wmts_ready = bool(
            runtime.get("cdse_enabled")
            and runtime.get("cdse_wmts_configured")
            and runtime.get("cdse_credentials_detected")
        )
        campaign_uid = str(getattr(self, "current_campaign_uid", "") or "").strip()
        campaign_root = ""
        if campaign_uid and hasattr(self, "campaign_storage"):
            try:
                campaign_root = str(self.campaign_storage.campaign_root(campaign_uid))
            except Exception:
                campaign_root = ""
        lines = [
            f"Repo root used: {runtime.get('repo_root_used') or 'not resolved'}",
            f"Env file used: {runtime.get('env_file_used') or 'not found'}",
            f"Debug log file: {self._disk_log_path or 'not initialized'}",
            f"Backend API base URL: {self._backend_api_base_url()}",
            f"Local tile proxy: {self.local_tile_proxy.base_url if self.local_tile_proxy.is_running() else 'unavailable'}",
            f"Campaign UID: {campaign_uid or 'none'}",
            f"Campaign root: {campaign_root or 'unavailable'}",
            f"Managed campaign storage: {'yes' if bool(getattr(self, '_campaign_storage_enabled', lambda: False)()) else 'no'}",
            f"NewSat Constellation auth mode: {runtime['satellogic_auth_mode']}",
            f"NewSat Constellation access profile configured: {'yes' if runtime['satellogic_contract_configured'] else 'no'}",
            f"NewSat Constellation credentials detected (.env/backend): {'yes' if runtime.get('satellogic_credentials_detected') else 'no'}",
            f"NewSat Constellation authcfg configured: {'yes' if runtime['satellogic_authcfg_configured'] else 'no'}",
            f"CDSE enabled: {'yes' if runtime['cdse_enabled'] else 'no'}",
            f"CDSE WMTS configured: {'yes' if runtime['cdse_wmts_configured'] else 'no'}",
            f"CDSE WMTS readiness: {'ready' if wmts_ready else 'not_ready'}",
            f"CDSE WMTS backend proxy preferred: {'yes' if runtime.get('cdse_wmts_use_backend_proxy', True) else 'no'}",
            f"CDSE credentials detected (.env/backend): {'yes' if runtime.get('cdse_credentials_detected') else 'no'}",
            f"CDSE authcfg configured: {'yes' if runtime['cdse_authcfg_configured'] else 'no'}",
            f"Backend provider modules ready: {'yes' if runtime.get('backend_ready') else 'no'}",
        ]
        asset_intel_service = getattr(self, "asset_intel_service", None)
        if asset_intel_service is not None:
            asset_db_path = str(getattr(asset_intel_service, "db_path", "") or "").strip()
            lines.append(f"Asset Intel DB path: {asset_db_path or 'not configured'}")
            try:
                lines.append(
                    f"Asset Intel DB ready: {'yes' if bool(asset_intel_service.is_ready()) else 'no'}"
                )
            except Exception:
                lines.append("Asset Intel DB ready: no")
        if runtime.get("backend_error"):
            lines.append(f"Backend init error: {runtime['backend_error']}")
        if self._local_tile_proxy_error:
            lines.append(f"Local tile proxy error: {self._local_tile_proxy_error}")
        asset_intel_error = str(getattr(self, "_asset_intel_error", "") or "").strip()
        if asset_intel_error:
            lines.append(f"Asset Intel error: {asset_intel_error}")
        campaign_storage_error = str(getattr(self, "_campaign_storage_error", "") or "").strip()
        if campaign_storage_error:
            lines.append(f"Campaign storage init error: {campaign_storage_error}")
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
        log_dir = None
        storage_enabled_fn = getattr(self, "_campaign_storage_enabled", None)
        if callable(storage_enabled_fn) and bool(storage_enabled_fn()):
            campaign_uid = str(getattr(self, "current_campaign_uid", "") or "").strip()
            campaign_storage = getattr(self, "campaign_storage", None)
            if campaign_uid and campaign_storage is not None:
                try:
                    log_dir = campaign_storage.campaign_logs_dir(campaign_uid)
                except Exception:
                    log_dir = None
        if log_dir is None:
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

    @staticmethod
    def _satellogic_scene_id_from_item(item):
        row = item if isinstance(item, dict) else {}
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        raw_props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        candidates = [
            row.get("scene_id"),
            row.get("id"),
            raw.get("scene_id"),
            raw.get("id"),
            raw_props.get("scene_id"),
            raw_props.get("satl:scene_id"),
        ]
        for value in candidates:
            text = str(value or "").strip()
            if not text:
                continue
            if ":" in text and text.count(":") == 1:
                text = text.split(":", 1)[1].strip()
            text = Path(urlparse(text).path).name or text
            # L1D item ids can include trailing tile indices (e.g. "..._2_0_1")
            # while Telluric expects canonical scene ids.
            l1d_suffix = re.match(r"^(?P<base>.+)_\d+_\d+_\d+$", text)
            if l1d_suffix and "_L1D_" in text:
                text = str(l1d_suffix.group("base") or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def _satellogic_tif_name_from_href(href):
        raw = str(href or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw)
        path_name = Path(parsed.path).name
        if path_name.lower().endswith((".tif", ".tiff")):
            return path_name

        params = parse_qs(parsed.query or "", keep_blank_values=False)
        for key in ("s", "url", "href"):
            for value in params.get(key) or []:
                nested = str(value or "").strip()
                if not nested:
                    continue
                nested_parsed = urlparse(nested)
                nested_name = Path(nested_parsed.path).name
                if nested_name.lower().endswith((".tif", ".tiff")):
                    return nested_name
        return ""

    @staticmethod
    def _satellogic_scene_id_from_asset_href(href):
        raw = str(href or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw)
        path_parts = [part for part in str(parsed.path or "").split("/") if part]
        if "deliverables" in path_parts:
            idx = path_parts.index("deliverables")
            if idx + 1 < len(path_parts):
                scene = str(path_parts[idx + 1] or "").strip()
                if scene:
                    return scene

        params = parse_qs(parsed.query or "", keep_blank_values=False)
        for key in ("s", "url", "href"):
            for value in params.get(key) or []:
                nested = str(value or "").strip()
                if not nested:
                    continue
                nested_parsed = urlparse(nested)
                nested_parts = [part for part in str(nested_parsed.path or "").split("/") if part]
                if len(nested_parts) < 2:
                    continue
                leaf = str(nested_parts[-1] or "").strip()
                parent = str(nested_parts[-2] or "").strip()
                if leaf.lower().endswith((".tif", ".tiff")) and parent:
                    return parent
        return ""

    @staticmethod
    def _satellogic_scene_id_from_tif_name(tif_name):
        raw = str(tif_name or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw)
        name = Path(parsed.path).name or raw
        stem = Path(name).stem
        lowered = stem.lower()
        for suffix in ("_visual_fullres", "_visual", "_analytic", "_preview", "_thumbnail", "_browse"):
            if lowered.endswith(suffix):
                return stem[: -len(suffix)]
        return ""

    def _satellogic_telluric_scene_raster_from_item(self, item):
        row = item if isinstance(item, dict) else {}
        if str(row.get("source_id") or "").strip().lower() != "satellogic":
            return "", ""

        scene_id = self._satellogic_scene_id_from_item(row)
        assets = row.get("assets") if isinstance(row.get("assets"), dict) else {}
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        raw_assets = raw.get("assets") if isinstance(raw.get("assets"), dict) else {}

        for key in ("visual_fullres", "visual", "analytic", "preview", "thumbnail"):
            href = str(assets.get(key) or "").strip()
            tif_name = self._satellogic_tif_name_from_href(href)
            if tif_name:
                scene_from_href = self._satellogic_scene_id_from_asset_href(href)
                scene_from_tif = self._satellogic_scene_id_from_tif_name(tif_name)
                return scene_from_href or scene_from_tif or scene_id, tif_name

        for key in ("visual_fullres", "visual", "analytic", "preview", "thumbnail"):
            raw_asset = raw_assets.get(key)
            if isinstance(raw_asset, dict):
                tif_name = self._satellogic_tif_name_from_href(raw_asset.get("href"))
                if tif_name:
                    scene_from_href = self._satellogic_scene_id_from_asset_href(raw_asset.get("href"))
                    scene_from_tif = self._satellogic_scene_id_from_tif_name(tif_name)
                    return scene_from_href or scene_from_tif or scene_id, tif_name
                alternate = raw_asset.get("alternate")
                if isinstance(alternate, dict):
                    for row_alt in alternate.values():
                        if not isinstance(row_alt, dict):
                            continue
                        tif_name = self._satellogic_tif_name_from_href(row_alt.get("href"))
                        if tif_name:
                            scene_from_href = self._satellogic_scene_id_from_asset_href(row_alt.get("href"))
                            scene_from_tif = self._satellogic_scene_id_from_tif_name(tif_name)
                            return scene_from_href or scene_from_tif or scene_id, tif_name

        if scene_id and "_L1D_" in scene_id and scene_id.count("_") >= 3:
            return scene_id, f"{scene_id}_visual.tif"
        return scene_id, ""

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
                f"Capped NewSat Constellation stream candidates from {len(urls)} to {max_sources} for responsive tile loading."
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

    def _source_bbox_token_for_item(self, item):
        if not isinstance(item, dict):
            return ""
        rect = None
        if self._normalize_collection_id(item.get("collection")) == "l1d-sr":
            rect = self._raster_bounds_rect_wgs84(item)
        if rect is None or rect.isEmpty():
            geom_payload = item.get("geometry")
            if isinstance(geom_payload, dict):
                geom = self._geometry_from_geojson(geom_payload)
                if geom is not None and not geom.isEmpty():
                    rect = geom.boundingBox()
        if rect is None or rect.isEmpty():
            return ""
        try:
            minx = float(min(rect.xMinimum(), rect.xMaximum()))
            maxx = float(max(rect.xMinimum(), rect.xMaximum()))
            miny = float(min(rect.yMinimum(), rect.yMaximum()))
            maxy = float(max(rect.yMinimum(), rect.yMaximum()))
        except Exception:
            return ""
        if maxx <= minx or maxy <= miny:
            return ""
        return f"{minx:.7f},{miny:.7f},{maxx:.7f},{maxy:.7f}"

    def _satellogic_source_bbox_tokens(self, items):
        mapping = {}
        for candidate in items or []:
            if not isinstance(candidate, dict):
                continue
            source_url = self._satellogic_item_cog_source_url(candidate)
            if not source_url or source_url in mapping:
                continue
            token = self._source_bbox_token_for_item(candidate)
            if token:
                mapping[source_url] = token
        return mapping

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

    def _resolve_location_query(self, query):
        parsed = self._parse_lat_lon_query(query)
        if parsed is not None:
            lat, lon = parsed
            return lat, lon, f"{lat:.6f}, {lon:.6f}", "coordinates"
        lat, lon, label = self._geocode_location_query(query)
        return lat, lon, label, "geocoded"

    @staticmethod
    def _parse_lat_lon_query(query):
        text = str(query or "").strip()
        if not text:
            return None

        lat_match = re.search(
            r"\blat(?:itude)?\s*[:=]?\s*([-+]?\d+(?:\.\d+)?)",
            text,
            flags=re.IGNORECASE,
        )
        lon_match = re.search(
            r"\b(?:lon(?:gitude)?|lng)\s*[:=]?\s*([-+]?\d+(?:\.\d+)?)",
            text,
            flags=re.IGNORECASE,
        )
        if lat_match and lon_match:
            lat = float(lat_match.group(1))
            lon = float(lon_match.group(1))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                return lat, lon
            return None

        matches = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
        if len(matches) < 2:
            return None

        first = float(matches[0])
        second = float(matches[1])
        if not (-180.0 <= first <= 180.0 and -180.0 <= second <= 180.0):
            return None

        if -90.0 <= first <= 90.0 and -180.0 <= second <= 180.0:
            return first, second
        if -180.0 <= first <= 180.0 and -90.0 <= second <= 90.0:
            return second, first
        return None

    def _geocode_location_query(self, query):
        hits = self._nominatim_search(query, limit=1)
        if not hits:
            raise RuntimeError("location not found")
        top = hits[0] if isinstance(hits[0], dict) else {}
        try:
            lat = float(top.get("lat"))
            lon = float(top.get("lon"))
        except Exception as exc:
            raise RuntimeError("geocoding response did not include coordinates") from exc
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise RuntimeError("geocoding response returned invalid coordinates")
        label = str(top.get("display_name") or str(query or "").strip()).strip() or str(query or "").strip()
        return lat, lon, label

    def _geocode_location_suggestions(self, query, limit=8):
        q = str(query or "").strip()
        if not q:
            return []

        parsed = self._parse_lat_lon_query(q)
        suggestions = []
        if parsed is not None:
            lat, lon = parsed
            suggestions.append(f"{lat:.6f}, {lon:.6f}")

        hits = self._nominatim_search(q, limit=limit)
        seen = set(suggestions)
        for row in hits:
            if not isinstance(row, dict):
                continue
            label = str(row.get("display_name") or "").strip()
            if not label or label in seen:
                continue
            seen.add(label)
            suggestions.append(label)
            if len(suggestions) >= int(limit):
                break
        return suggestions

    @staticmethod
    def _nominatim_search(query, *, limit):
        q = str(query or "").strip()
        if not q:
            raise RuntimeError("location query is empty")
        url = "https://nominatim.openstreetmap.org/search?" + urlencode(
            {"q": q, "format": "jsonv2", "limit": max(1, int(limit or 1))}
        )
        request = Request(
            url,
            headers={
                "User-Agent": "ImageMateQGISPlugin/1.0",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, list) else []

    def _center_canvas_on_wgs84(self, *, lat, lon):
        canvas = self.iface.mapCanvas() if self.iface is not None else None
        if canvas is None:
            raise RuntimeError("map canvas is unavailable")

        src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        dst_crs = canvas.mapSettings().destinationCrs()
        target_point = QgsPointXY(float(lon), float(lat))
        if dst_crs.isValid() and dst_crs.authid() != "EPSG:4326":
            transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            transformed = transform.transform(target_point)
            target_point = QgsPointXY(float(transformed.x()), float(transformed.y()))

        extent = canvas.extent()
        if extent.isEmpty() or float(extent.width()) <= 0 or float(extent.height()) <= 0:
            seed_rect = QgsRectangle(
                float(lon) - 0.2,
                float(lat) - 0.2,
                float(lon) + 0.2,
                float(lat) + 0.2,
            )
            if dst_crs.isValid() and dst_crs.authid() != "EPSG:4326":
                transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
                seed_rect = transform.transformBoundingBox(seed_rect)
            canvas.setExtent(seed_rect)

        canvas.setCenter(target_point)
        canvas.refresh()

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
        fill_color = QColor(255, 255, 153, 64)
        outline_color = QColor(255, 255, 153, 255)
        symbol = QgsFillSymbol.createSimple(
            {
                "color": f"{fill_color.red()},{fill_color.green()},{fill_color.blue()},{fill_color.alpha()}",
                "outline_color": f"{outline_color.red()},{outline_color.green()},{outline_color.blue()},{outline_color.alpha()}",
                "outline_width": "0.6",
                "outline_style": "solid",
            }
        )
        if symbol is not None:
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.updateExtents()
        self._add_layer_to_image_mate_group(layer, insert_on_top=False)
        layer_node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if layer_node is not None:
            layer_node.setItemVisibilityChecked(False)
        self.search_layer_id = layer.id()

    def _load_item_imagery_layer(self, item):
        source_id = str(item.get("source_id") or "").strip() or None
        contract_id = str(item.get("contract_id") or "").strip() or None
        collection_id = str(item.get("collection") or "").strip()
        item_id = str(item.get("id") or "").strip() or "unknown-item"
        candidates = self._imagery_asset_candidates_for_item(item)
        attempted_keys = []
        errors = []
        first_error = ""
        for key, url in candidates:
            if not url:
                continue
            attempted_keys.append(key)
            auth_route = self._asset_auth_route_for_download(source_id=source_id, asset_url=url)
            try:
                expected_size = self._asset_expected_size_bytes(
                    item=item,
                    asset_key=key,
                    asset_url=url,
                )
                cached_path = self._find_cached_temp_asset_path(
                    item=item,
                    preferred_key=key,
                    asset_url=url,
                    expected_size=expected_size,
                )
                if cached_path is not None:
                    layer_name = self._asset_layer_name(item, key)
                    cached_layer = QgsRasterLayer(str(cached_path), layer_name)
                    if cached_layer.isValid():
                        if key in {"preview", "thumbnail"} and not self._layer_has_georeference(cached_layer):
                            if self._georeference_image_asset_from_item_bounds(item=item, image_path=cached_path):
                                refreshed_layer = QgsRasterLayer(str(cached_path), layer_name)
                                if refreshed_layer.isValid():
                                    if not refreshed_layer.crs().isValid():
                                        refreshed_layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
                                    if self._layer_has_georeference(refreshed_layer):
                                        cached_layer = refreshed_layer
                                        self._append_debug_log(
                                            "item_load_attempt "
                                            f"source={source_id or 'unknown'} collection={collection_id or ''} item_id={item_id} "
                                            f"asset_key={key} mode=preview_georef success=yes cache=true"
                                        )
                        if key in {"preview", "thumbnail"} and not self._layer_has_georeference(cached_layer):
                            self._append_debug_log(
                                "item_load_attempt "
                                f"source={source_id or 'unknown'} collection={collection_id or ''} item_id={item_id} "
                                f"asset_key={key} mode=cache success=no error=preview_not_georeferenced",
                                level=Qgis.Warning,
                            )
                            continue
                        self._append_debug_log(
                            "item_load_attempt "
                            f"source={source_id or 'unknown'} collection={collection_id or ''} item_id={item_id} "
                            f"asset_key={key} auth_route={auth_route} mode=cache success=yes"
                        )
                        self._append_search_log(
                            f"Reusing cached asset '{key}' ({cached_path.name})",
                            level=Qgis.Info,
                        )
                        return cached_layer
                    self._append_debug_log(
                        "item_load_attempt "
                        f"source={source_id or 'unknown'} collection={collection_id or ''} item_id={item_id} "
                        f"asset_key={key} auth_route={auth_route} mode=cache success=no error=invalid_qgis_layer",
                        level=Qgis.Warning,
                    )
                    self._append_debug_log(
                        f"Cached asset '{cached_path}' failed QGIS validation; downloading fresh copy.",
                        level=Qgis.Warning,
                    )

                data = self.source_service.download_asset(url, source_hint=source_id, contract_id=contract_id)
                if expected_size is not None and expected_size > 0 and int(len(data)) != int(expected_size):
                    self._append_debug_log(
                        f"Asset size mismatch for {key}: expected={expected_size} downloaded={len(data)}",
                        level=Qgis.Warning,
                    )
                path = self._write_temp_asset(item, url, data, preferred_key=key)
                layer_name = self._asset_layer_name(item, key)
                layer = QgsRasterLayer(str(path), layer_name)
                if not layer.isValid():
                    raise RuntimeError(f"QGIS could not open downloaded asset ({path.name})")
                if key in {"preview", "thumbnail"} and not self._layer_has_georeference(layer):
                    if self._georeference_image_asset_from_item_bounds(item=item, image_path=path):
                        georef_layer = QgsRasterLayer(str(path), layer_name)
                        if georef_layer.isValid():
                            if not georef_layer.crs().isValid():
                                georef_layer.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
                            if self._layer_has_georeference(georef_layer):
                                layer = georef_layer
                                self._append_debug_log(
                                    "item_load_attempt "
                                    f"source={source_id or 'unknown'} collection={collection_id or ''} item_id={item_id} "
                                    f"asset_key={key} mode=preview_georef success=yes"
                                )
                if key in {"preview", "thumbnail"} and not self._layer_has_georeference(layer):
                    raise RuntimeError("preview asset has no georeference")
                self._append_debug_log(
                    "item_load_attempt "
                    f"source={source_id or 'unknown'} collection={collection_id or ''} item_id={item_id} "
                    f"asset_key={key} auth_route={auth_route} mode=download success=yes bytes={len(data)}"
                )
                return layer
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                if not first_error:
                    first_error = f"{key}: {exc}"
                self._append_debug_log(
                    "item_load_attempt "
                    f"source={source_id or 'unknown'} collection={collection_id or ''} item_id={item_id} "
                    f"asset_key={key} auth_route={auth_route} mode=download success=no error={exc}",
                    level=Qgis.Warning,
                )
                continue

        source_norm = str(source_id or "").strip().lower()
        if source_norm == "merlin-s2":
            wmts_layer = self._build_merlin_wmts_stream_layer(item)
            if wmts_layer is not None:
                self._append_search_log(
                    f"Fallback loaded Sentinel-2 WMTS layer for item {item_id} after raster asset attempts.",
                    level=Qgis.Info,
                )
                return wmts_layer

        attempted = ",".join(attempted_keys) if attempted_keys else "none"
        if errors:
            raise RuntimeError(
                f"No usable imagery assets were available for item {item_id}; "
                f"attempted_assets=[{attempted}] first_error={first_error or errors[0]}"
            )
        raise RuntimeError(
            f"No usable imagery assets were available for item {item_id}; attempted_assets=[{attempted}]"
        )

    @staticmethod
    def _imagery_asset_candidates_for_item(item):
        source_id = str(item.get("source_id") or "").strip().lower()
        assets = item.get("assets") or {}
        if source_id == "merlin-s2":
            ordered_keys = [
                "visual_fullres",
                "visual",
                "analytic",
                "preview",
                "thumbnail",
            ]
        else:
            ordered_keys = [
                "preview",
                "thumbnail",
                "visual",
                "visual_fullres",
                "analytic",
            ]
        seen = set()
        out = []
        for key in ordered_keys:
            if key in seen:
                continue
            seen.add(key)
            out.append((key, str(assets.get(key) or "").strip()))
        return out

    @staticmethod
    def _asset_auth_route_for_download(*, source_id, asset_url):
        source = str(source_id or "").strip().lower()
        if source == "merlin-s2":
            url_lc = str(asset_url or "").strip().lower()
            if "/odata/" in url_lc or "/download/" in url_lc:
                return "cdse_download_token"
            return "cdse_access_token"
        if source == "satellogic":
            return "satellogic_contract_auth"
        return "source_auto"

    @staticmethod
    def _layer_has_georeference(layer):
        if layer is None:
            return False
        try:
            if not layer.crs().isValid():
                return False
            extent = layer.extent()
            return extent is not None and not extent.isEmpty()
        except Exception:
            return False

    def _georeference_image_asset_from_item_bounds(self, *, item, image_path):
        path = Path(str(image_path or "")).expanduser().resolve()
        if not path.is_file():
            return False
        geometry_payload = item.get("geometry") if isinstance(item, dict) else None
        if not isinstance(geometry_payload, dict):
            return False
        geom = self._geometry_from_geojson(geometry_payload)
        if geom is None or geom.isEmpty():
            return False
        try:
            bounds = geom.boundingBox()
            min_x = float(bounds.xMinimum())
            min_y = float(bounds.yMinimum())
            max_x = float(bounds.xMaximum())
            max_y = float(bounds.yMaximum())
        except Exception:
            return False
        if not (max_x > min_x and max_y > min_y):
            return False

        image = QImage(str(path))
        width = int(image.width())
        height = int(image.height())
        if width < 2 or height < 2:
            return False

        pixel_size_x = (max_x - min_x) / float(width)
        pixel_size_y = (max_y - min_y) / float(height)
        if pixel_size_x <= 0 or pixel_size_y <= 0:
            return False

        x_center_ul = min_x + (pixel_size_x / 2.0)
        y_center_ul = max_y - (pixel_size_y / 2.0)
        world_lines = [
            f"{pixel_size_x:.15f}",
            "0.0",
            "0.0",
            f"{-pixel_size_y:.15f}",
            f"{x_center_ul:.15f}",
            f"{y_center_ul:.15f}",
        ]
        world_path = self._world_file_path(path)
        try:
            world_path.write_text("\n".join(world_lines) + "\n", encoding="ascii")
            prj_path = path.with_suffix(".prj")
            prj_wkt = QgsCoordinateReferenceSystem("EPSG:4326").toWkt()
            if prj_wkt:
                prj_path.write_text(prj_wkt, encoding="utf-8")
            return True
        except Exception:
            return False

    @staticmethod
    def _world_file_path(image_path):
        path = Path(str(image_path))
        suffix = path.suffix.lower()
        mapping = {
            ".png": ".pgw",
            ".jpg": ".jgw",
            ".jpeg": ".jgw",
            ".tif": ".tfw",
            ".tiff": ".tfw",
            ".jp2": ".j2w",
            ".webp": ".wld",
        }
        world_suffix = mapping.get(suffix, ".wld")
        return path.with_suffix(world_suffix)

    def _write_temp_asset(self, item, url, data, preferred_key):
        item_id = str(item.get("id") or "item").replace(":", "_").replace("/", "_")
        ext = self._guess_asset_extension(url, data)
        file_name = f"{item_id}_{preferred_key}{ext}"
        cache_dir_fn = getattr(self, "search_asset_cache_dir", None)
        if callable(cache_dir_fn):
            path = Path(cache_dir_fn(item=item, workflow=False)) / file_name
        else:
            path = self.temp_dir / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                if int(path.stat().st_size) == int(len(data)):
                    return path
            except Exception:
                pass
        path.write_bytes(data)
        return path

    def _find_cached_temp_asset_path(self, *, item, preferred_key, asset_url, expected_size):
        if expected_size is None or int(expected_size) <= 0:
            return None
        item_id = str((item if isinstance(item, dict) else {}).get("id") or "item")
        safe_item_id = item_id.replace(":", "_").replace("/", "_")
        name_prefix = f"{safe_item_id}_{preferred_key}"
        cache_dir = None
        cache_dir_fn = getattr(self, "search_asset_cache_dir", None)
        if callable(cache_dir_fn):
            try:
                cache_dir = Path(cache_dir_fn(item=item, workflow=False))
            except Exception:
                cache_dir = None
        if cache_dir is None:
            cache_dir = self.temp_dir

        candidates = []
        suffix = Path(urlparse(str(asset_url or "")).path).suffix.lower()
        if suffix:
            candidates.append(cache_dir / f"{name_prefix}{suffix}")
        for candidate in sorted(cache_dir.glob(f"{name_prefix}.*")):
            if candidate.is_file():
                candidates.append(candidate)

        seen = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            try:
                if int(candidate.stat().st_size) == int(expected_size):
                    return candidate
            except Exception:
                continue
        return None

    def _asset_expected_size_bytes(self, *, item, asset_key, asset_url):
        row = item if isinstance(item, dict) else {}
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        raw_assets = raw.get("assets") if isinstance(raw.get("assets"), dict) else {}
        if not raw_assets:
            return None

        key_norm = str(asset_key or "").strip()
        if key_norm.startswith("workflow_"):
            key_norm = key_norm[len("workflow_") :]

        candidate_assets = []
        seen_obj_ids = set()

        direct_asset = raw_assets.get(key_norm)
        if isinstance(direct_asset, dict):
            candidate_assets.append(direct_asset)
            seen_obj_ids.add(id(direct_asset))

        for raw_asset in raw_assets.values():
            if not isinstance(raw_asset, dict):
                continue
            if id(raw_asset) in seen_obj_ids:
                continue
            raw_hrefs = self._asset_hrefs_from_raw_asset(raw_asset)
            if any(self._asset_urls_match(href, asset_url) for href in raw_hrefs):
                candidate_assets.append(raw_asset)
                seen_obj_ids.add(id(raw_asset))

        for asset in candidate_assets:
            size_value = self._extract_size_from_asset_dict(asset)
            if size_value is not None and int(size_value) > 0:
                return int(size_value)
        return None

    @staticmethod
    def _asset_hrefs_from_raw_asset(asset):
        out = []
        if not isinstance(asset, dict):
            return out
        href = str(asset.get("href") or "").strip()
        if href:
            out.append(href)
        alternate = asset.get("alternate")
        if isinstance(alternate, dict):
            for row in alternate.values():
                if not isinstance(row, dict):
                    continue
                alt_href = str(row.get("href") or "").strip()
                if alt_href:
                    out.append(alt_href)
        return out

    @classmethod
    def _extract_size_from_asset_dict(cls, asset):
        if not isinstance(asset, dict):
            return None
        direct = cls._extract_size_from_mapping(asset)
        if direct is not None:
            return direct
        file_meta = asset.get("file")
        if isinstance(file_meta, dict):
            nested = cls._extract_size_from_mapping(file_meta)
            if nested is not None:
                return nested
        props = asset.get("properties")
        if isinstance(props, dict):
            nested = cls._extract_size_from_mapping(props)
            if nested is not None:
                return nested
        return None

    @classmethod
    def _extract_size_from_mapping(cls, mapping):
        if not isinstance(mapping, dict):
            return None
        for key in (
            "file:size",
            "size",
            "content_length",
            "content-length",
            "length",
            "bytes",
            "fileSize",
            "file_size",
        ):
            value = mapping.get(key)
            parsed = cls._coerce_positive_int(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _coerce_positive_int(value):
        if value is None:
            return None
        try:
            parsed = int(float(value))
        except Exception:
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _asset_urls_match(left, right):
        left_text = str(left or "").strip()
        right_text = str(right or "").strip()
        if not left_text or not right_text:
            return False
        if left_text == right_text:
            return True
        left_parsed = urlparse(left_text)
        right_parsed = urlparse(right_text)
        if left_parsed.path and right_parsed.path and left_parsed.path == right_parsed.path:
            return True
        left_core = f"{left_parsed.scheme}://{left_parsed.netloc}{left_parsed.path}"
        right_core = f"{right_parsed.scheme}://{right_parsed.netloc}{right_parsed.path}"
        return bool(left_core and right_core and left_core == right_core)

    def _build_stream_layer_for_item(self, item, source_urls=None, source_items=None, prefer_telluric=False):
        source_id = str(item.get("source_id") or "").strip().lower()
        if source_id == "merlin-s2":
            layer = self._build_merlin_wmts_stream_layer(item)
            if layer is not None:
                return layer
        if source_id == "satellogic":
            if bool(prefer_telluric):
                layer = self._build_satellogic_telluric_stream_layer(item)
                if layer is not None:
                    return layer
            layer = self._build_satellogic_proxy_stream_layer(
                item,
                source_urls=source_urls,
                source_items=source_items,
            )
            if layer is not None:
                return layer
            if not bool(prefer_telluric):
                layer = self._build_satellogic_telluric_stream_layer(item)
                if layer is not None:
                    return layer
        return None

    def _build_satellogic_telluric_stream_layer(self, item):
        if not self.local_tile_proxy.is_running():
            return None
        scene_id, raster_name = self._satellogic_telluric_scene_raster_from_item(item)
        if not scene_id or not raster_name:
            return None
        raw_contract_id = str(item.get("contract_id") or "").strip() or self.source_service.default_contract_id()
        contract_id = self.source_service.resolve_contract_id(raw_contract_id)
        params = [
            ("scene_id", scene_id),
            ("raster_name", raster_name),
        ]
        if contract_id:
            params.append(("contract_id", contract_id))
        query = urlencode(params, doseq=True)
        query = query.replace("&", "%26")
        xyz_url = f"{self.local_tile_proxy.base_url}/satellogic/telluric/tiles/{{z}}/{{x}}/{{y}}?{query}"
        layer_name = self._asset_layer_name(item, "telluric_stream")
        layer = self._make_xyz_layer(xyz_url, layer_name, zmin=0, zmax=22)
        if layer is None or not layer.isValid():
            return None
        self._apply_stream_layer_extent(layer, [item])
        self._append_debug_log(
            "Telluric tile stream setup: "
            f"scene_id={scene_id} raster={raster_name} contract={'set' if contract_id else 'missing'}"
        )
        return layer

    def _build_merlin_wmts_stream_layer(self, item):
        day = self._item_day(item)
        time_param = f"{day}/{day}" if day else ""
        use_backend_proxy = bool(getattr(self.provider_settings, "cdse_wmts_use_backend_proxy", True))

        backend_reason = ""
        if use_backend_proxy:
            backend_template_url, backend_reason = self._merlin_wmts_backend_template_url(item=item, time_param=time_param)
            if backend_template_url:
                layer_name = self._asset_layer_name(item, "wmts")
                layer = self._make_xyz_layer(backend_template_url, layer_name, zmin=0, zmax=19)
                if layer is not None and layer.isValid():
                    self._append_debug_log(
                        "merlin_wmts_stream source=backend status=ready "
                        f"item_id={item.get('id') or ''} day={day or ''} url={backend_template_url[:280]}"
                    )
                    return layer
                backend_reason = "backend_template_invalid_in_qgis"
                self._append_debug_log(
                    "merlin_wmts_stream source=backend status=invalid_layer "
                    f"item_id={item.get('id') or ''} day={day or ''}",
                    level=Qgis.Warning,
                )

        base_url = str(self.provider_settings.cdse_wmts_base_url or "").strip().rstrip("/")
        instance_id = str(self.provider_settings.cdse_wmts_instance_id or "").strip()
        layer_id = str(self.provider_settings.cdse_wmts_layer_id or "TRUE-COLOR").strip() or "TRUE-COLOR"
        if not base_url:
            reason = "missing_base_url"
            if backend_reason:
                reason = f"{backend_reason}; {reason}"
            self._set_stream_status(f"Stream status: Sentinel-2 WMTS unavailable ({reason})")
            return None
        if not instance_id:
            reason = "missing_instance_id"
            if backend_reason:
                reason = f"{backend_reason}; {reason}"
            self._set_stream_status(f"Stream status: Sentinel-2 WMTS unavailable ({reason})")
            return None
        if not layer_id:
            reason = "missing_layer_id"
            if backend_reason:
                reason = f"{backend_reason}; {reason}"
            self._set_stream_status(f"Stream status: Sentinel-2 WMTS unavailable ({reason})")
            return None

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
        if layer is None or not layer.isValid():
            reason = "direct_wmts_invalid_layer"
            if backend_reason:
                reason = f"{backend_reason}; {reason}"
            self._set_stream_status(f"Stream status: Sentinel-2 WMTS unavailable ({reason})")
            self._append_debug_log(
                "merlin_wmts_stream source=direct status=invalid_layer "
                f"item_id={item.get('id') or ''} day={day or ''} url={xyz_url[:280]}",
                level=Qgis.Warning,
            )
            return None
        self._append_debug_log(
            "merlin_wmts_stream source=direct status=ready "
            f"item_id={item.get('id') or ''} day={day or ''} url={xyz_url[:280]}"
        )
        return layer

    def _merlin_wmts_backend_template_url(self, *, item, time_param):
        backend_request = getattr(self, "_backend_json_request", None)
        if not callable(backend_request):
            return "", "backend_proxy_not_available"
        layer_id = str(self.provider_settings.cdse_wmts_layer_id or "TRUE-COLOR").strip() or "TRUE-COLOR"
        try:
            payload = backend_request(
                "/api/layers/sentinel/wmts",
                params={"layer_id": layer_id},
                timeout=12,
            )
        except Exception as exc:
            reason = f"backend_wmts_request_failed:{exc}"
            self._append_debug_log(
                f"merlin_wmts_stream source=backend status=unavailable reason={reason}",
                level=Qgis.Warning,
            )
            self._set_stream_status(f"Stream status: Sentinel-2 WMTS unavailable ({reason})")
            return "", reason
        if not isinstance(payload, dict):
            reason = "backend_wmts_invalid_response"
            self._append_debug_log(
                f"merlin_wmts_stream source=backend status=unavailable reason={reason}",
                level=Qgis.Warning,
            )
            return "", reason
        available = bool(payload.get("available"))
        reason = str(payload.get("reason") or "").strip()
        template_url = str(payload.get("template_url") or "").strip()
        warning = str(payload.get("warning") or "").strip()
        if not available:
            reason = reason or "backend_reported_unavailable"
            self._append_debug_log(
                "merlin_wmts_stream source=backend status=unavailable "
                f"reason={reason} warning={warning}",
                level=Qgis.Warning,
            )
            self._set_stream_status(f"Stream status: Sentinel-2 WMTS unavailable ({reason})")
            return "", reason
        if not template_url:
            reason = "backend_template_url_missing"
            self._append_debug_log(
                f"merlin_wmts_stream source=backend status=unavailable reason={reason}",
                level=Qgis.Warning,
            )
            return "", reason
        full_url = self._absolutize_backend_url(template_url)
        full_url = self._apply_wmts_time_to_template_url(full_url, time_param)
        return full_url, ""

    def _absolutize_backend_url(self, value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw
        if raw.startswith("/"):
            return f"{self._backend_api_base_url()}{raw}"
        return f"{self._backend_api_base_url()}/{raw.lstrip('/')}"

    @staticmethod
    def _apply_wmts_time_to_template_url(template_url, time_param):
        text = str(template_url or "").strip()
        if not text or not time_param:
            return text
        parsed = urlparse(text)
        params = parse_qs(parsed.query, keep_blank_values=True)
        if "time" in params:
            params["time"] = [time_param]
        elif "TIME" in params:
            params["TIME"] = [time_param]
        else:
            params["time"] = [time_param]
        query = urlencode(params, doseq=True)
        query = query.replace("%7Bz%7D", "{z}").replace("%7By%7D", "{y}").replace("%7Bx%7D", "{x}")
        return parsed._replace(query=query).geturl()

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
        is_local_proxy = self.local_tile_proxy.is_running() and stream_base == self.local_tile_proxy.base_url
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
        source_bbox_tokens = {}
        if is_local_proxy and len(resolved_sources) > 1:
            source_bbox_tokens = self._satellogic_source_bbox_tokens(source_items or [item])
        for source in resolved_sources:
            params.append(("url", source))
            if is_local_proxy and len(resolved_sources) > 1:
                params.append(("source_bbox", str(source_bbox_tokens.get(source) or "-")))
        if contract_id:
            params.append(("contract_id", contract_id))
        query = urlencode(params, doseq=True, safe=":/")
        # QGIS datasource URI parsing splits on '&' at the provider URI level.
        # Escape nested query separators so they remain inside the XYZ URL value.
        query = query.replace("&", "%26")
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
        pinned_item_id = str(getattr(self, "_auto_stream_pinned_item_id", "") or "").strip()
        if pinned_item_id:
            pinned_item = self.search_items.get(pinned_item_id)
            if isinstance(pinned_item, dict) and str(pinned_item.get("source_id") or "").strip().lower() == "satellogic":
                # Respect manual selection for NewSat imagery; do not auto-switch on zoom/pan.
                return
            setattr(self, "_auto_stream_pinned_item_id", "")
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
        self._add_layer_to_image_mate_group(new_layer, insert_on_top=True)
        self.preview_layer_id = new_layer.id()

    @staticmethod
    def _get_or_create_image_mate_group():
        root = QgsProject.instance().layerTreeRoot()
        for child in root.children():
            if isinstance(child, QgsLayerTreeGroup) and str(child.name() or "").strip() == "Image Mate":
                return child
        return root.addGroup("Image Mate")

    def _add_layer_to_image_mate_group(self, layer, *, insert_on_top=False):
        if layer is None:
            return
        project = QgsProject.instance()
        group = self._get_or_create_image_mate_group()
        if project.mapLayer(layer.id()) is None:
            project.addMapLayer(layer, False)
        existing_node = group.findLayer(layer.id())
        if existing_node is not None:
            group.removeChildNode(existing_node)
        insert_index = 0 if bool(insert_on_top) else len(group.children())
        group.insertLayer(insert_index, layer)

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
