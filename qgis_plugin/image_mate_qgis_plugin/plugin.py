# -*- coding: utf-8 -*-
"""Main plugin wiring for Image Mate."""

from pathlib import Path
from datetime import datetime, timezone
import gc
import json
import tempfile
import re
import time
import math
import os
import traceback
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from qgis import processing
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.gui import QgsMapToolEmitPoint
from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    Qgis,
    QgsDistanceArea,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsFillSymbol,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsTask,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .controllers.search_controller import SearchController
from .services.auth_service import AuthService
from .services.asset_intel_service import AssetIntelService
from .services.campaign_storage_service import CampaignStorageService
from .services.local_tile_proxy import LocalTileProxy
from .services.mosaic_contracts import (
    API_STATUS_NOT_SUBMITTED,
    ATTEMPT_STATUS_SUBMITTED,
    MUTATION_SOURCE_ACCEPT,
    PRICE_USD_PER_KM2,
    TASKING_DEFAULT_SKU,
    default_operator_name,
    utc_now_iso,
    validate_project_id,
)
from .services.mosaic_grid_service import MosaicGridService
from .services.mosaicking_service import (
    MosaickingLogBuffer,
    MosaickingService,
    normalize_mosaicking_request,
)
from .services.mosaic_tasking_service import MosaicTaskingService
from .services.mosaic_tracking_store import MosaicTrackingStore
from .services.mosaic_preview_resolution import (
    extract_order_geometry,
    is_completed_status,
    preview_collection_candidates,
    preview_item_id_candidates,
    preview_search_window,
)
from .services.side_by_side_layer_tree_service import (
    build_project_layer_tree_snapshot,
    resolve_selected_layers_for_canvas,
)
from .services.side_by_side_map_controller import SideBySideMapController
from .services.simulation_config_service import SimulationConfigService
from .services.settings_service import DEFAULT_CAMPAIGN_BASE_DIR
from .services.settings_service import SettingsService
from .services.source_service import SourceService
from .services.processing_runtime import ensure_processing_runtime
from .services.local_raster_path_resolver import resolve_local_raster_path
from .services.resample_workflows import (
    RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M,
    RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M,
    RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M,
    ResampleWorkflowSpec,
    resolution_hint_token,
)
from .services.time_lapse_video_service import (
    TimeLapseVideoService,
    normalize_time_lapse_fps,
    normalize_time_lapse_frames,
)
from .services.vessel_training_service import VesselTrainingService
from .services.vessel_detection_service import VesselDetectionService
from .ui.main_dock import ImageMateMainDock
from .mixins import SearchStreamingMixin
from .mixins import SimulationExecutionMixin
from .mixins import WorkflowExecutionMixin


class ImageMatePlugin(SimulationExecutionMixin, WorkflowExecutionMixin, SearchStreamingMixin):
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = Path(__file__).resolve().parent
        self._fallback_temp_dir = Path(tempfile.gettempdir()) / "image_mate_qgis_plugin"
        self._fallback_temp_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir = self._fallback_temp_dir
        self.action = None
        self.dock = None
        self.settings_service = SettingsService()
        self.provider_settings = self.settings_service.load()
        self.campaign_storage = CampaignStorageService(
            base_dir=str(self.provider_settings.campaign_base_dir or DEFAULT_CAMPAIGN_BASE_DIR),
            managed_storage_enabled=bool(self.provider_settings.campaign_managed_storage),
        )
        self.current_campaign_uid = ""
        self.current_campaign_root = None
        self._workflow_execution_temp_dir = self.temp_dir
        self._campaign_storage_error = ""
        try:
            self._configure_campaign_storage()
        except Exception as exc:
            self._campaign_storage_error = str(exc)
            self.temp_dir = self._fallback_temp_dir
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            self._workflow_execution_temp_dir = self.temp_dir
            self.provider_settings.campaign_managed_storage = False
        self.source_service = SourceService(self.provider_settings)
        self.asset_intel_service = AssetIntelService(self.provider_settings.asset_intel_db_path)
        self.vessel_detection_service = VesselDetectionService()
        self.vessel_training_service = VesselTrainingService(plugin_dir=self.plugin_dir)
        self.time_lapse_video_service = TimeLapseVideoService()
        self.mosaicking_service = MosaickingService()
        self._asset_intel_error = ""
        self._configure_asset_intel_service()
        self.local_tile_proxy = LocalTileProxy(self.source_service)
        self._local_tile_proxy_error = ""
        try:
            self.local_tile_proxy.start()
        except Exception as exc:
            self._local_tile_proxy_error = str(exc)
        self.auth_service = AuthService()
        self.simulation_config_service = SimulationConfigService()
        self.mosaic_grid_service = MosaicGridService(price_per_km2=PRICE_USD_PER_KM2)
        self.mosaic_tasking_service = MosaicTaskingService()
        self.search_controller = SearchController()
        self.search_items = {}
        self.search_layer_id = None
        self.preview_layer_id = None
        self._backend_health = {"checked_at": 0.0, "ok": False}
        self._monitoring_backend_notice_at = 0.0
        self._auto_stream_enabled = True
        self._auto_stream_zoom_threshold = 13
        self._satellogic_highres_zoom_threshold = 17
        self._satellogic_max_stream_sources = 8
        self._auto_stream_pinned_item_id = ""
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
        self._last_vessel_qa_batch_dir = ""
        self._show_debug_on_screen = False
        self._show_search_log_on_screen = False
        self._message_log_connected = False
        self._download_selected_tasks = {}
        self._download_selected_monitor_timer = QTimer()
        self._download_selected_monitor_timer.setInterval(500)
        self._download_selected_monitor_timer.timeout.connect(self._poll_download_selected_tasks)
        self._workflow_worker = None
        self._workflow_thread = None
        self._workflow_running = False
        self._workflow_run_started_at = 0.0
        self._workflow_total_nodes = 0
        self._workflow_node_types = {}
        self._simulation_worker = None
        self._simulation_thread = None
        self._simulation_running = False
        self._simulation_result = {}
        self._simulation_day_index = 0
        self._simulation_day_layer_id = None
        self._simulation_unique_layer_id = None
        self._simulation_revisit_target_layer_id = None
        self._simulation_pick_tool = None
        self._simulation_prev_map_tool = None
        self._simulation_target_point = {}
        self._asset_intel_polygon_pick_tool = None
        self._asset_intel_polygon_prev_map_tool = None
        self._mosaic_preview_layer_id = None
        self._mosaic_tracking_preview_layer_ids = {}
        self._mosaic_tracking_preview_project_id = ""
        self._mosaic_tiling_layer_id = None
        self._mosaic_tiling_sync_guard = False
        self._mosaic_breakdown_rows = []
        self._mosaic_breakdown_context = {}
        self._side_by_side_map_controller = SideBySideMapController(
            self.iface,
            mode_state_callback=self._on_workflow_side_by_side_mode_state_changed,
        )
        self.local_tile_proxy.set_event_logger(self._on_local_proxy_event)

    def initGui(self):
        icon_path = str(self.plugin_dir / "icons" / "image_mate.svg")
        self.action = QAction(QIcon(icon_path), "ISR Mission Workbench", self.iface.mainWindow())
        self.action.setObjectName("imageMateOpenDockAction")
        self.action.triggered.connect(self.show_dock)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&ISR Mission Workbench", self.action)
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
            self.iface.removePluginMenu("&ISR Mission Workbench", self.action)
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
        if self._download_selected_monitor_timer.isActive():
            self._download_selected_monitor_timer.stop()
        self._download_selected_tasks = {}
        self._stop_workflow_execution(timeout_ms=2000)
        self._stop_simulation_execution(timeout_ms=2000)
        self._stop_simulation_pick_mode()
        self._stop_asset_intel_polygon_pick_mode(set_pan=False)
        self._clear_mosaic_preview_layer()
        self._clear_mosaic_tracking_preview_layer()
        self._clear_mosaic_tiling_layer()
        self._side_by_side_map_controller.cleanup()
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
            self.dock.destroyed.connect(self._on_simulation_dock_destroyed)
            self.dock.destroyed.connect(self._on_asset_intel_dock_destroyed)
            self.dock.destroyed.connect(self._on_side_by_side_dock_destroyed)
            self.dock.validate_requested.connect(self.validate_setup)
            self.dock.settings_saved.connect(self.save_settings_from_dock)
            self.dock.campaign_apply_requested.connect(self.handle_campaign_apply_request)
            self.dock.search_requested.connect(self.handle_search_request)
            self.dock.download_selected_requested.connect(self.handle_download_selected_request)
            self.dock.location_jump_requested.connect(self.handle_location_jump_request)
            self.dock.location_suggestions_requested.connect(self.handle_location_suggestions_request)
            self.dock.result_selected.connect(self.handle_result_selected)
            self.dock.execute_workflow_requested.connect(self.handle_execute_workflow_request)
            self.dock.workflow_side_by_side_refresh_requested.connect(self.handle_workflow_side_by_side_refresh_request)
            self.dock.workflow_side_by_side_start_requested.connect(self.handle_workflow_side_by_side_start_request)
            self.dock.workflow_side_by_side_review_requested.connect(self.handle_workflow_side_by_side_review_request)
            self.dock.workflow_side_by_side_stop_requested.connect(self.handle_workflow_side_by_side_stop_request)
            self.dock.create_vrt_requested.connect(self.handle_create_vrt_request)
            self.dock.mosaicking_studio_requested.connect(self.handle_mosaicking_studio_request)
            self.dock.sharpen_image_requested.connect(self.handle_sharpen_image_request)
            self.dock.resample_image_10m_requested.connect(self.handle_resample_image_10m_request)
            self.dock.resample_image_10p8_to_3m_requested.connect(self.handle_resample_image_10p8_to_3m_request)
            self.dock.resample_image_2m_to_1m_requested.connect(self.handle_resample_image_2m_to_1m_request)
            self.dock.resample_image_3p76m_to_1m_requested.connect(self.handle_resample_image_3p76m_to_1m_request)
            self.dock.generate_time_lapse_requested.connect(self.handle_generate_time_lapse_request)
            self.dock.vessel_detect_requested.connect(self.handle_vessel_detect_request)
            self.dock.vessel_detect_extent_requested.connect(self.handle_vessel_detect_current_extent_request)
            self.dock.vessel_qa_layer_create_requested.connect(self.handle_vessel_create_qa_layer_request)
            self.dock.vessel_qa_status_set_requested.connect(self.handle_vessel_set_qa_status_request)
            self.dock.vessel_qa_finalize_requested.connect(self.handle_vessel_finalize_qa_batch_request)
            self.dock.vessel_qa_open_batch_folder_requested.connect(self.handle_vessel_open_qa_batch_folder_request)
            self.dock.vessel_qa_model_update_requested.connect(self.handle_vessel_model_update_request)
            self.dock.tasking_refresh_requested.connect(self.handle_tasking_refresh_request)
            self.dock.tasking_submit_requested.connect(self.handle_tasking_submit_request)
            self.dock.tasking_order_selected.connect(self.handle_tasking_order_selected)
            self.dock.mosaic_breakdown_requested.connect(self.handle_mosaic_breakdown_request)
            self.dock.mosaic_accept_requested.connect(self.handle_mosaic_accept_request)
            self.dock.mosaic_tracking_project_changed.connect(self.handle_mosaic_tracking_project_changed)
            self.dock.mosaic_tracking_tile_selected.connect(self.handle_mosaic_tracking_tile_selected)
            self.dock.mosaic_tracking_preview_toggled.connect(self.handle_mosaic_tracking_preview_toggled)
            self.dock.mosaic_refresh_status_requested.connect(self.handle_mosaic_refresh_status_request)
            self.dock.mosaic_delete_requested.connect(self.handle_mosaic_delete_request)
            self.dock.mosaic_show_tiling_requested.connect(self.handle_mosaic_show_tiling_request)
            self.dock.mosaic_mark_accepted_requested.connect(self.handle_mosaic_mark_accepted_request)
            self.dock.mosaic_retask_requested.connect(self.handle_mosaic_retask_request)
            self.dock.mosaic_cancel_requested.connect(self.handle_mosaic_cancel_request)
            self.dock.mosaic_more_requested.connect(self.handle_mosaic_more_request)
            self.dock.mosaic_refresh_projects_requested.connect(self.handle_mosaic_refresh_projects_request)
            self.dock.monitoring_refresh_requested.connect(self.handle_monitoring_refresh_request)
            self.dock.monitoring_create_subscription_requested.connect(self.handle_monitoring_create_subscription_request)
            self.dock.monitoring_ack_event_requested.connect(self.handle_monitoring_ack_event_request)
            self.dock.monitoring_create_cue_requested.connect(self.handle_monitoring_create_cue_request)
            self.dock.asset_intel_search_requested.connect(self.handle_asset_intel_search_request)
            self.dock.asset_intel_asset_selected.connect(self.handle_asset_intel_asset_selected)
            self.dock.asset_intel_polygon_size_from_selection_requested.connect(
                self.handle_asset_intel_polygon_size_from_selection_request
            )
            self.dock.asset_intel_create_requested.connect(self.handle_asset_intel_create_request)
            self.dock.asset_intel_update_requested.connect(self.handle_asset_intel_update_request)
            self.dock.asset_intel_delete_requested.connect(self.handle_asset_intel_delete_request)
            self.dock.asset_intel_note_create_requested.connect(self.handle_asset_intel_note_create_request)
            self.dock.asset_intel_note_update_requested.connect(self.handle_asset_intel_note_update_request)
            self.dock.asset_intel_note_delete_requested.connect(self.handle_asset_intel_note_delete_request)
            self.dock.asset_intel_structure_mutation_requested.connect(
                self.handle_asset_intel_structure_mutation_request
            )
            self.dock.simulation_config_changed.connect(self.handle_simulation_config_changed)
            self.dock.simulation_start_requested.connect(self.handle_simulation_start_request)
            self.dock.simulation_cancel_requested.connect(self.handle_simulation_cancel_request)
            self.dock.simulation_first_day_requested.connect(self.handle_simulation_first_day_request)
            self.dock.simulation_prev_30_days_requested.connect(self.handle_simulation_prev_30_days_request)
            self.dock.simulation_prev_day_requested.connect(self.handle_simulation_prev_day_request)
            self.dock.simulation_next_day_requested.connect(self.handle_simulation_next_day_request)
            self.dock.simulation_next_30_days_requested.connect(self.handle_simulation_next_30_days_request)
            self.dock.simulation_last_day_requested.connect(self.handle_simulation_last_day_request)
            self.dock.simulation_pick_target_requested.connect(self.handle_simulation_pick_target_request)
            self.dock.simulation_scenario_changed.connect(self.handle_simulation_scenario_changed)
            self.dock.source_combo.currentIndexChanged.connect(self._on_source_changed)
            self.dock.set_runtime_summary(self._runtime_summary_text())
            self.dock.load_settings(self.provider_settings)
            self.dock.set_campaign_context(self._campaign_context_payload())
            self._bind_dock_data()
            self._sync_download_monitor_to_dock()
            self._simulation_bind_dock_data()
            self._refresh_asset_intel_data()
            self._refresh_workflow_side_by_side_layer_tree()
            self._sync_workflow_side_by_side_mode_to_dock()
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)

        self._refresh_workflow_side_by_side_layer_tree()
        self._sync_workflow_side_by_side_mode_to_dock()
        self.dock.show()
        self.dock.raise_()
        self._log_info("Dock opened")

    def _on_simulation_dock_destroyed(self, _obj=None):
        self._stop_simulation_pick_mode()

    def _on_asset_intel_dock_destroyed(self, _obj=None):
        self._stop_asset_intel_polygon_pick_mode(set_pan=False)

    def _on_side_by_side_dock_destroyed(self, _obj=None):
        self._side_by_side_map_controller.stop()

    @staticmethod
    def _normalize_layer_id_list(values):
        if not isinstance(values, list):
            return []
        out = []
        for value in values:
            layer_id = str(value or "").strip()
            if layer_id and layer_id not in out:
                out.append(layer_id)
        return out

    def _on_workflow_side_by_side_mode_state_changed(self, active):
        is_active = bool(active)
        message = "Side-by-side mode is on." if is_active else "Side-by-side mode is off."
        self._sync_workflow_side_by_side_mode_to_dock(active=is_active, message=message)

    def _sync_workflow_side_by_side_mode_to_dock(self, *, active=None, message=""):
        if self.dock is None or not hasattr(self.dock, "set_side_by_side_mode_state"):
            return
        if active is None:
            active = self._side_by_side_map_controller.is_active()
        self.dock.set_side_by_side_mode_state(bool(active), message=message)

    def _refresh_workflow_side_by_side_layer_tree(self):
        if self.dock is None or not hasattr(self.dock, "set_side_by_side_layer_tree"):
            return
        payload = build_project_layer_tree_snapshot(project=QgsProject.instance())
        self.dock.set_side_by_side_layer_tree(payload)

    def handle_workflow_side_by_side_refresh_request(self):
        self._refresh_workflow_side_by_side_layer_tree()
        self._sync_workflow_side_by_side_mode_to_dock()

    @staticmethod
    def _side_by_side_title_for_selection(*, layer_ids, resolved_layers, default_title):
        ids = layer_ids if isinstance(layer_ids, list) else []
        for layer_id in ids:
            if not layer_id:
                continue
            layer = QgsProject.instance().mapLayer(str(layer_id))
            if layer is None:
                continue
            name = str(layer.name() or "").strip()
            if name:
                return name
        for layer in resolved_layers or []:
            name = str(getattr(layer, "name", lambda: "")() or "").strip()
            if name:
                return name
        return str(default_title or "").strip() or "View"

    def _resolve_side_by_side_selection(self, payload):
        request = payload if isinstance(payload, dict) else {}
        lhs_layer_ids = self._normalize_layer_id_list(request.get("lhs_layer_ids"))
        rhs_layer_ids = self._normalize_layer_id_list(request.get("rhs_layer_ids"))

        if not lhs_layer_ids:
            return {
                "ok": False,
                "message": "Side-by-side mode requires at least one LHS layer selection.",
                "dock_message": "Select at least one LHS layer.",
            }
        if not rhs_layer_ids:
            return {
                "ok": False,
                "message": "Side-by-side mode requires at least one RHS layer selection.",
                "dock_message": "Select at least one RHS layer.",
            }

        project = QgsProject.instance()
        lhs_layers = resolve_selected_layers_for_canvas(selected_layer_ids=lhs_layer_ids, project=project)
        rhs_layers = resolve_selected_layers_for_canvas(selected_layer_ids=rhs_layer_ids, project=project)

        if not lhs_layers:
            return {
                "ok": False,
                "message": "Selected LHS layers are not available in the current project.",
                "dock_message": "LHS layer selection is invalid for the current project state.",
            }
        if not rhs_layers:
            return {
                "ok": False,
                "message": "Selected RHS layers are not available in the current project.",
                "dock_message": "RHS layer selection is invalid for the current project state.",
            }

        lhs_title = self._side_by_side_title_for_selection(
            layer_ids=lhs_layer_ids,
            resolved_layers=lhs_layers,
            default_title="LHS",
        )
        rhs_title = self._side_by_side_title_for_selection(
            layer_ids=rhs_layer_ids,
            resolved_layers=rhs_layers,
            default_title="RHS",
        )

        return {
            "ok": True,
            "lhs_layer_ids": lhs_layer_ids,
            "rhs_layer_ids": rhs_layer_ids,
            "lhs_layers": lhs_layers,
            "rhs_layers": rhs_layers,
            "lhs_title": lhs_title,
            "rhs_title": rhs_title,
        }

    def _side_by_side_canvas_context(self):
        canvas = self.iface.mapCanvas() if self.iface is not None else None
        initial_extent = None
        destination_crs = None
        if canvas is not None:
            try:
                initial_extent = QgsRectangle(canvas.extent())
            except Exception:
                initial_extent = None
            try:
                destination_crs = canvas.mapSettings().destinationCrs()
            except Exception:
                destination_crs = None
        return initial_extent, destination_crs

    def handle_workflow_side_by_side_start_request(self, payload):
        resolved = self._resolve_side_by_side_selection(payload)
        if not bool(resolved.get("ok")):
            message = str(resolved.get("message") or "Invalid side-by-side layer selection.").strip()
            dock_message = str(resolved.get("dock_message") or "").strip()
            self.iface.messageBar().pushMessage(
                "Image Mate",
                message,
                level=Qgis.Warning,
                duration=8,
            )
            self._sync_workflow_side_by_side_mode_to_dock(active=False, message=dock_message)
            return

        initial_extent, destination_crs = self._side_by_side_canvas_context()
        lhs_layers = list(resolved.get("lhs_layers") or [])
        rhs_layers = list(resolved.get("rhs_layers") or [])

        self._side_by_side_map_controller.start(
            lhs_layers=lhs_layers,
            rhs_layers=rhs_layers,
            initial_extent=initial_extent,
            destination_crs=destination_crs,
            lhs_default_title=str(resolved.get("lhs_title") or "").strip(),
            rhs_default_title=str(resolved.get("rhs_title") or "").strip(),
            preserve_extent_if_active=False,
        )
        self._sync_workflow_side_by_side_mode_to_dock(
            active=True,
            message=(
                "Side-by-side mode active: "
                f"LHS {len(lhs_layers)} layer(s), RHS {len(rhs_layers)} layer(s)."
            ),
        )
        self.iface.messageBar().pushMessage(
            "Image Mate",
            "Side-by-side mode started.",
            level=Qgis.Info,
            duration=5,
        )

    def handle_workflow_side_by_side_review_request(self, payload):
        resolved = self._resolve_side_by_side_selection(payload)
        if not bool(resolved.get("ok")):
            message = str(resolved.get("message") or "Invalid side-by-side layer selection.").strip()
            dock_message = str(resolved.get("dock_message") or "").strip()
            self.iface.messageBar().pushMessage(
                "Image Mate",
                message,
                level=Qgis.Warning,
                duration=8,
            )
            self._sync_workflow_side_by_side_mode_to_dock(active=False, message=dock_message)
            return

        mode_was_active = self._side_by_side_map_controller.is_active()
        initial_extent, destination_crs = self._side_by_side_canvas_context()
        lhs_layers = list(resolved.get("lhs_layers") or [])
        rhs_layers = list(resolved.get("rhs_layers") or [])

        self._side_by_side_map_controller.start(
            lhs_layers=lhs_layers,
            rhs_layers=rhs_layers,
            initial_extent=initial_extent,
            destination_crs=destination_crs,
            lhs_default_title=str(resolved.get("lhs_title") or "").strip(),
            rhs_default_title=str(resolved.get("rhs_title") or "").strip(),
            preserve_extent_if_active=True,
        )
        message = (
            "Side-by-side review refreshed."
            if mode_was_active
            else "Side-by-side mode started from Refresh View."
        )
        self._sync_workflow_side_by_side_mode_to_dock(
            active=True,
            message=(
                "Side-by-side mode active: "
                f"LHS {len(lhs_layers)} layer(s), RHS {len(rhs_layers)} layer(s)."
            ),
        )
        self.iface.messageBar().pushMessage(
            "Image Mate",
            message,
            level=Qgis.Info,
            duration=5,
        )

    def handle_workflow_side_by_side_stop_request(self):
        self._side_by_side_map_controller.stop()
        self._sync_workflow_side_by_side_mode_to_dock(active=False, message="Side-by-side mode is off.")

    def handle_simulation_scenario_changed(self, scenario_id):
        scenario = str(scenario_id or "").strip().lower()
        if scenario != "point_revisit_analysis":
            self._stop_simulation_pick_mode()

    def handle_simulation_pick_target_request(self):
        if self.dock is None:
            return
        canvas = self.iface.mapCanvas()
        if canvas is None:
            return
        self._stop_simulation_pick_mode()
        self._simulation_prev_map_tool = canvas.mapTool()
        self._simulation_pick_tool = QgsMapToolEmitPoint(canvas)
        self._simulation_pick_tool.canvasClicked.connect(self._on_simulation_canvas_point_picked)
        canvas.setMapTool(self._simulation_pick_tool)
        if hasattr(self.dock, "set_simulation_status"):
            self.dock.set_simulation_status("Simulation status: click on map to set point target.")

    def _on_simulation_canvas_point_picked(self, point, _button=None):
        canvas = self.iface.mapCanvas()
        if canvas is None:
            return
        src_crs = canvas.mapSettings().destinationCrs()
        dst_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        lon = float(point.x())
        lat = float(point.y())
        if src_crs.isValid() and src_crs != dst_crs:
            try:
                transformed = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance()).transform(
                    QgsPointXY(float(point.x()), float(point.y()))
                )
                lon = float(transformed.x())
                lat = float(transformed.y())
            except Exception:
                self.iface.messageBar().pushMessage(
                    "Image Mate",
                    "Failed to transform picked point to WGS84.",
                    level=Qgis.Warning,
                    duration=8,
                )
                self._stop_simulation_pick_mode()
                return
        self._simulation_target_point = {
            "lat": float(lat),
            "lon": float(lon),
            "source": "map_click",
            "label": "",
        }
        if self.dock is not None and hasattr(self.dock, "set_simulation_target_point"):
            self.dock.set_simulation_target_point(float(lat), float(lon), source="map_click", label="")
        if self.dock is not None and hasattr(self.dock, "set_simulation_status"):
            self.dock.set_simulation_status("Simulation status: target point set from map click.")
        if hasattr(self, "_append_search_log"):
            self._append_search_log(
                f"[Simulation] target point picked lat={float(lat):.6f}, lon={float(lon):.6f}",
                level=Qgis.Info,
            )
        self._stop_simulation_pick_mode()

    def _stop_simulation_pick_mode(self):
        canvas = self.iface.mapCanvas()
        pick_tool = self._simulation_pick_tool
        if pick_tool is not None:
            try:
                pick_tool.canvasClicked.disconnect(self._on_simulation_canvas_point_picked)
            except Exception:
                pass
        if canvas is not None and pick_tool is not None and canvas.mapTool() == pick_tool:
            prev = self._simulation_prev_map_tool
            try:
                if prev is not None:
                    canvas.setMapTool(prev)
                else:
                    canvas.unsetMapTool(pick_tool)
            except Exception:
                pass
        self._simulation_pick_tool = None
        self._simulation_prev_map_tool = None

    def validate_setup(self):
        auth_result = self.auth_service.validate_configuration(self.provider_settings)
        sources = self.source_service.list_sources()
        source_line = ", ".join(
            [f"{row['source_id']}={'on' if row['enabled'] else 'off'}" for row in sources]
        )
        asset_state = self._configure_asset_intel_service()
        asset_line = "ready" if bool(asset_state.get("ok")) else "unavailable"
        message = (
            f"{auth_result.get('message', 'validation completed')} | "
            f"sources: {source_line} | "
            f"asset intel: {asset_line}"
        )
        if self.dock is not None:
            self.dock.set_runtime_summary(self._runtime_summary_text(extra_line=message))
        self.iface.messageBar().pushMessage("Image Mate", message, level=Qgis.Info, duration=6)

    def save_settings_from_dock(self):
        if self.dock is None:
            return
        self.provider_settings = self.dock.apply_settings_to(self.provider_settings)
        self._backend_health = {"checked_at": 0.0, "ok": False}
        try:
            self._configure_campaign_storage()
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Campaign storage configuration failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            return
        self.settings_service.save(self.provider_settings)
        self.source_service = SourceService(self.provider_settings)
        try:
            self.local_tile_proxy.set_source_service(self.source_service)
            if not self.local_tile_proxy.is_running():
                self.local_tile_proxy.start()
            self._local_tile_proxy_error = ""
        except Exception as exc:
            self._local_tile_proxy_error = str(exc)
        self._configure_asset_intel_service()
        self.dock.set_campaign_context(self._campaign_context_payload())
        self._bind_dock_data()
        self._simulation_bind_dock_data()
        self._refresh_asset_intel_data()
        self.validate_setup()

    def _configure_asset_intel_service(self):
        db_path = str(getattr(self.provider_settings, "asset_intel_db_path", "") or "").strip()
        try:
            self.asset_intel_service.set_db_path(db_path)
            state = self.asset_intel_service.validate()
            self._asset_intel_error = "" if bool(state.get("ok")) else str(state.get("message") or "").strip()
            return state
        except Exception as exc:
            message = f"Asset Intel setup failed: {exc}"
            self._asset_intel_error = message
            return {"ok": False, "message": message}

    def _refresh_asset_intel_data(self):
        if self.dock is None:
            return
        state = self._configure_asset_intel_service()
        status_text = str(state.get("message") or "").strip() or "Asset Intel status unavailable."
        self.dock.set_asset_intel_status(status_text)
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_facets(
                {
                    "domain": [],
                    "domain_main": [],
                    "sub_domain_1": [],
                    "sub_domain_2": [],
                    "type": [],
                    "type_by_sub_domain_2": {},
                    "origin": [],
                    "proliferation": [],
                    "builder": [],
                }
            )
            self.dock.set_asset_intel_results([])
            self.dock.set_asset_intel_detail(None)
            return
        try:
            facets = self.asset_intel_service.list_facets()
            self.dock.set_asset_intel_facets(facets)
            self.handle_asset_intel_search_request(self.dock.current_asset_intel_payload())
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self.dock.set_asset_intel_status(f"Asset Intel refresh failed: {exc}")
            self.dock.set_asset_intel_results([])
            self.dock.set_asset_intel_detail(None)

    def handle_asset_intel_search_request(self, payload):
        if self.dock is None:
            return
        request_payload = payload if isinstance(payload, dict) else {}
        state = self._configure_asset_intel_service()
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_status(str(state.get("message") or "Asset Intel DB unavailable."))
            self.dock.set_asset_intel_results([])
            self.dock.set_asset_intel_detail(None)
            return
        try:
            rows = self.asset_intel_service.search_assets(request_payload)
            self.dock.set_asset_intel_results(rows)
            query_text = str(request_payload.get("query_text") or "").strip()
            if query_text:
                self.dock.set_asset_intel_status(
                    f"Asset Intel: {len(rows)} result(s) for '{query_text}'."
                )
            else:
                self.dock.set_asset_intel_status(f"Asset Intel: {len(rows)} result(s).")
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel search failed: {exc}", level=Qgis.Warning)
            self.dock.set_asset_intel_status(f"Asset Intel search failed: {exc}")
            self.dock.set_asset_intel_results([])
            self.dock.set_asset_intel_detail(None)

    def handle_asset_intel_asset_selected(self, asset_id):
        if self.dock is None:
            return
        selected_asset_id = str(asset_id or "").strip()
        if not selected_asset_id:
            self.dock.set_asset_intel_detail(None)
            return
        state = self._configure_asset_intel_service()
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_status(str(state.get("message") or "Asset Intel DB unavailable."))
            self.dock.set_asset_intel_detail(None)
            return
        try:
            detail = self.asset_intel_service.get_asset_detail(selected_asset_id)
            if not isinstance(detail, dict):
                self.dock.set_asset_intel_detail(None)
                self.dock.set_asset_intel_status(f"Asset Intel: no detail found for {selected_asset_id}.")
                return
            self.dock.set_asset_intel_detail(detail)
            asset_info = detail.get("asset") if isinstance(detail.get("asset"), dict) else {}
            title = str(asset_info.get("title") or selected_asset_id).strip()
            self.dock.set_asset_intel_status(f"Asset Intel: loaded {title}.")
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel detail load failed: {exc}", level=Qgis.Warning)
            self.dock.set_asset_intel_status(f"Asset Intel detail load failed: {exc}")
            self.dock.set_asset_intel_detail(None)

    def _refresh_asset_intel_after_mutation(self, *, selected_asset_id="", status_text=""):
        if self.dock is None:
            return
        try:
            facets = self.asset_intel_service.list_facets()
            self.dock.set_asset_intel_facets(facets)
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel facet refresh failed: {exc}", level=Qgis.Warning)
        try:
            rows = self.asset_intel_service.search_assets(self.dock.current_asset_intel_payload())
            self.dock.set_asset_intel_results(rows)
            if selected_asset_id:
                self.dock.select_asset_intel_asset(selected_asset_id)
            selected_now = self.dock.current_asset_intel_asset_id()
            detail_asset_id = str(selected_asset_id or selected_now or "").strip()
            if detail_asset_id:
                self.handle_asset_intel_asset_selected(detail_asset_id)
            else:
                self.dock.set_asset_intel_detail(None)
            if status_text:
                self.dock.set_asset_intel_status(status_text)
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel refresh failed after mutation: {exc}", level=Qgis.Warning)
            self.dock.set_asset_intel_status(f"Asset Intel refresh failed: {exc}")

    def handle_asset_intel_create_request(self, payload):
        if self.dock is None:
            return
        request_payload = payload if isinstance(payload, dict) else {}
        state = self._configure_asset_intel_service()
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_status(str(state.get("message") or "Asset Intel DB unavailable."))
            return
        try:
            asset_id = self.asset_intel_service.create_asset(request_payload)
            self._refresh_asset_intel_after_mutation(
                selected_asset_id=asset_id,
                status_text=f"Asset Intel: created {asset_id}.",
            )
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel create failed: {exc}", level=Qgis.Warning)
            self.dock.set_asset_intel_status(f"Asset Intel create failed: {exc}")

    def handle_asset_intel_update_request(self, payload):
        if self.dock is None:
            return
        request_payload = payload if isinstance(payload, dict) else {}
        asset_id = str(request_payload.get("asset_id") or self.dock.current_asset_intel_asset_id() or "").strip()
        if not asset_id:
            self.dock.set_asset_intel_status("Asset Intel update skipped: no asset selected.")
            return
        state = self._configure_asset_intel_service()
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_status(str(state.get("message") or "Asset Intel DB unavailable."))
            return
        try:
            updated_id = self.asset_intel_service.update_asset(asset_id, request_payload)
            self._refresh_asset_intel_after_mutation(
                selected_asset_id=updated_id,
                status_text=f"Asset Intel: updated {updated_id}.",
            )
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel update failed: {exc}", level=Qgis.Warning)
            self.dock.set_asset_intel_status(f"Asset Intel update failed: {exc}")

    def handle_asset_intel_delete_request(self, asset_id):
        if self.dock is None:
            return
        selected_asset_id = str(asset_id or "").strip()
        if not selected_asset_id:
            self.dock.set_asset_intel_status("Asset Intel delete skipped: no asset selected.")
            return
        state = self._configure_asset_intel_service()
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_status(str(state.get("message") or "Asset Intel DB unavailable."))
            return
        try:
            self.asset_intel_service.delete_asset(selected_asset_id)
            self._refresh_asset_intel_after_mutation(
                selected_asset_id="",
                status_text=f"Asset Intel: deleted {selected_asset_id}.",
            )
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel delete failed: {exc}", level=Qgis.Warning)
            self.dock.set_asset_intel_status(f"Asset Intel delete failed: {exc}")

    def handle_asset_intel_structure_mutation_request(self, payload):
        if self.dock is None:
            return
        request_payload = payload if isinstance(payload, dict) else {}
        action = str(request_payload.get("action") or "").strip().lower()
        mutation_payload = request_payload.get("payload")
        mutation_payload = mutation_payload if isinstance(mutation_payload, dict) else {}
        if not action:
            self.dock.set_asset_intel_status("Asset Intel update skipped: missing action.")
            return

        state = self._configure_asset_intel_service()
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_status(str(state.get("message") or "Asset Intel DB unavailable."))
            return

        selected_asset_id = str(
            mutation_payload.get("asset_id") or self.dock.current_asset_intel_asset_id() or ""
        ).strip()
        if action in {"create_unit", "create_system"} and selected_asset_id and not str(
            mutation_payload.get("asset_id") or ""
        ).strip():
            mutation_payload = dict(mutation_payload)
            mutation_payload["asset_id"] = selected_asset_id

        try:
            status_text = ""
            if action == "create_system":
                system_id = self.asset_intel_service.create_system(mutation_payload)
                status_text = f"Asset Intel: onboard system {system_id} created."
            elif action == "update_system":
                system_id = int(mutation_payload.get("system_id") or 0)
                if system_id <= 0:
                    raise ValueError("System ID is required.")
                self.asset_intel_service.update_system(system_id, mutation_payload)
                status_text = f"Asset Intel: onboard system {system_id} updated."
            elif action == "create_unit":
                unit_id = self.asset_intel_service.create_unit(mutation_payload)
                status_text = f"Asset Intel: fielded unit {unit_id} created."
            elif action == "update_unit":
                unit_id = int(mutation_payload.get("unit_id") or 0)
                if unit_id <= 0:
                    raise ValueError("Unit ID is required.")
                self.asset_intel_service.update_unit(unit_id, mutation_payload)
                status_text = f"Asset Intel: fielded unit {unit_id} updated."
            elif action == "create_unit_identifier":
                identifier_id = self.asset_intel_service.create_unit_identifier(mutation_payload)
                status_text = f"Asset Intel: identifier {identifier_id} created."
            elif action == "update_unit_identifier":
                identifier_id = int(mutation_payload.get("identifier_id") or 0)
                if identifier_id <= 0:
                    raise ValueError("Identifier ID is required.")
                self.asset_intel_service.update_unit_identifier(identifier_id, mutation_payload)
                status_text = f"Asset Intel: identifier {identifier_id} updated."
            elif action == "create_unit_system_fit":
                fit_id = self.asset_intel_service.create_unit_system_fit(mutation_payload)
                status_text = f"Asset Intel: unit-system fit {fit_id} created."
            elif action == "update_unit_system_fit":
                fit_id = int(mutation_payload.get("fit_id") or 0)
                if fit_id <= 0:
                    raise ValueError("Fit ID is required.")
                self.asset_intel_service.update_unit_system_fit(fit_id, mutation_payload)
                status_text = f"Asset Intel: unit-system fit {fit_id} updated."
            else:
                raise ValueError(f"Unsupported Asset Intel action: {action}")

            override_status = str(request_payload.get("status_text") or "").strip()
            self._refresh_asset_intel_after_mutation(
                selected_asset_id=selected_asset_id,
                status_text=override_status or status_text,
            )
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(
                f"Asset Intel structure update failed: action={action} error={exc}",
                level=Qgis.Warning,
            )
            self.dock.set_asset_intel_status(f"Asset Intel structure update failed: {exc}")

    def handle_asset_intel_note_create_request(self, payload):
        if self.dock is None:
            return
        request_payload = payload if isinstance(payload, dict) else {}
        state = self._configure_asset_intel_service()
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_status(str(state.get("message") or "Asset Intel DB unavailable."))
            return
        try:
            note_id = self.asset_intel_service.create_analyst_note(request_payload)
            asset_id = str(request_payload.get("asset_id") or self.dock.current_asset_intel_asset_id() or "").strip()
            if asset_id:
                self.handle_asset_intel_asset_selected(asset_id)
            self.dock.set_asset_intel_status(f"Asset Intel: analyst note {note_id} created.")
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel note create failed: {exc}", level=Qgis.Warning)
            self.dock.set_asset_intel_status(f"Asset Intel note create failed: {exc}")

    def handle_asset_intel_note_update_request(self, payload):
        if self.dock is None:
            return
        request_payload = payload if isinstance(payload, dict) else {}
        note_id = int(request_payload.get("note_id") or 0)
        if note_id <= 0:
            self.dock.set_asset_intel_status("Asset Intel note update skipped: invalid note id.")
            return
        state = self._configure_asset_intel_service()
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_status(str(state.get("message") or "Asset Intel DB unavailable."))
            return
        try:
            self.asset_intel_service.update_analyst_note(note_id, request_payload)
            asset_id = str(request_payload.get("asset_id") or self.dock.current_asset_intel_asset_id() or "").strip()
            if asset_id:
                self.handle_asset_intel_asset_selected(asset_id)
            self.dock.set_asset_intel_status(f"Asset Intel: analyst note {note_id} updated.")
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel note update failed: {exc}", level=Qgis.Warning)
            self.dock.set_asset_intel_status(f"Asset Intel note update failed: {exc}")

    def handle_asset_intel_note_delete_request(self, note_id):
        if self.dock is None:
            return
        selected_note_id = int(note_id or 0)
        if selected_note_id <= 0:
            self.dock.set_asset_intel_status("Asset Intel note delete skipped: invalid note id.")
            return
        state = self._configure_asset_intel_service()
        if not bool(state.get("ok")):
            self.dock.set_asset_intel_status(str(state.get("message") or "Asset Intel DB unavailable."))
            return
        try:
            self.asset_intel_service.delete_analyst_note(selected_note_id)
            asset_id = self.dock.current_asset_intel_asset_id()
            if asset_id:
                self.handle_asset_intel_asset_selected(asset_id)
            self.dock.set_asset_intel_status(f"Asset Intel: analyst note {selected_note_id} deleted.")
        except Exception as exc:
            self._asset_intel_error = str(exc)
            self._append_debug_log(f"Asset Intel note delete failed: {exc}", level=Qgis.Warning)
            self.dock.set_asset_intel_status(f"Asset Intel note delete failed: {exc}")

    def _campaign_storage_enabled(self):
        return bool(self.provider_settings.campaign_managed_storage)

    def _configure_campaign_storage(self):
        base_dir = str(self.provider_settings.campaign_base_dir or "").strip() or DEFAULT_CAMPAIGN_BASE_DIR
        campaign_name = str(self.provider_settings.campaign_name or "").strip()
        campaign_uid_input = str(self.provider_settings.campaign_uid or "").strip() or campaign_name
        campaign_uid = self.campaign_storage.normalize_campaign_uid(campaign_uid_input or "default-campaign")

        self.provider_settings.campaign_base_dir = base_dir
        self.provider_settings.campaign_uid = campaign_uid
        if not campaign_name:
            campaign_name = campaign_uid
        self.provider_settings.campaign_name = campaign_name

        self.campaign_storage.set_base_dir(base_dir)
        self.campaign_storage.set_managed_storage_enabled(self._campaign_storage_enabled())
        self.current_campaign_uid = campaign_uid
        self.current_campaign_root = self.campaign_storage.campaign_root(campaign_uid)

        if self._campaign_storage_enabled():
            self.current_campaign_root = self.campaign_storage.ensure_campaign_tree(
                campaign_uid,
                campaign_name=campaign_name,
            )
            self.temp_dir = self.campaign_storage.campaign_temp_dir(campaign_uid)
        else:
            self.temp_dir = self._fallback_temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._workflow_execution_temp_dir = self.temp_dir
        self._sync_project_path_to_campaign()

    def _sync_project_path_to_campaign(self):
        if not self._campaign_storage_enabled():
            return
        if not self.current_campaign_uid:
            return
        try:
            project = QgsProject.instance()
            project_path = self.campaign_storage.campaign_project_path(self.current_campaign_uid)
            project_path.parent.mkdir(parents=True, exist_ok=True)
            current_path = str(project.fileName() or "").strip()
            project_path_text = str(project_path)
            if not current_path:
                project.setFileName(project_path_text)
            elif Path(current_path) != project_path:
                # Avoid forced project reload; ensure the active project save target stays within campaign storage.
                project.setFileName(project_path_text)
        except Exception as exc:
            if hasattr(self, "_append_debug_log"):
                try:
                    self._append_debug_log(f"Campaign project path sync skipped: {exc}", level=Qgis.Warning)
                except Exception:
                    pass

    def _activate_campaign_project_context(self):
        if not self._campaign_storage_enabled():
            return {"project_exists": False, "opened": False}
        if not self.current_campaign_uid:
            return {"project_exists": False, "opened": False}

        project = QgsProject.instance()
        project_path = self.campaign_storage.campaign_project_path(self.current_campaign_uid)
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project_path_text = str(project_path)
        project_exists = project_path.exists()

        if project_exists:
            opened = bool(project.read(project_path_text))
            if not opened:
                raise RuntimeError(f"Failed to open campaign project: {project_path_text}")
            return {"project_exists": True, "opened": True}

        current_path = str(project.fileName() or "").strip()
        if not current_path or Path(current_path) != project_path:
            project.setFileName(project_path_text)
        return {"project_exists": False, "opened": False}

    def _campaign_context_payload(self):
        project_path = ""
        campaign_root = ""
        if self.current_campaign_uid:
            try:
                campaign_root = str(self.campaign_storage.campaign_root(self.current_campaign_uid))
                project_path = str(self.campaign_storage.campaign_project_path(self.current_campaign_uid))
            except Exception:
                campaign_root = ""
                project_path = ""
        existing_campaigns = self._list_existing_campaigns()
        return {
            "managed_storage": bool(self._campaign_storage_enabled()),
            "base_dir": str(self.provider_settings.campaign_base_dir or "").strip(),
            "campaign_uid": str(self.current_campaign_uid or "").strip(),
            "campaign_name": str(self.provider_settings.campaign_name or "").strip(),
            "campaign_root": campaign_root,
            "project_path": project_path,
            "existing_campaigns": existing_campaigns,
        }

    def _list_existing_campaigns(self):
        try:
            rows = self.campaign_storage.list_campaigns()
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    def _campaign_uid_exists(self, campaign_uid):
        uid = self.campaign_storage.normalize_campaign_uid(str(campaign_uid or "").strip() or "default-campaign")
        try:
            root = self.campaign_storage.campaign_root(uid)
        except Exception:
            return False
        return root.exists() and root.is_dir()

    def _next_available_campaign_uid(self, campaign_uid):
        base_uid = self.campaign_storage.normalize_campaign_uid(
            str(campaign_uid or "").strip() or "campaign",
            fallback="campaign",
        )
        if not self._campaign_uid_exists(base_uid):
            return base_uid
        for idx in range(2, 1000):
            candidate = self.campaign_storage.normalize_campaign_uid(f"{base_uid}-{idx}", fallback=base_uid)
            if not self._campaign_uid_exists(candidate):
                return candidate
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
        return self.campaign_storage.normalize_campaign_uid(f"{base_uid}-{stamp}", fallback=base_uid)

    def handle_campaign_apply_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        managed_storage = bool(request.get("managed_storage", True))
        base_dir = str(request.get("base_dir") or "").strip() or DEFAULT_CAMPAIGN_BASE_DIR
        campaign_name = str(request.get("campaign_name") or "").strip()
        campaign_uid_input = str(request.get("campaign_uid") or "").strip()
        create_new = bool(request.get("create_new", False))
        campaign_uid = self.campaign_storage.normalize_campaign_uid(
            campaign_uid_input or campaign_name or "default-campaign"
        )
        if create_new:
            campaign_uid = self._next_available_campaign_uid(campaign_uid)
            if not campaign_name:
                campaign_name = campaign_uid
        elif not campaign_name:
            for row in self._list_existing_campaigns():
                if not isinstance(row, dict):
                    continue
                row_uid = str(row.get("uid") or "").strip()
                if row_uid == campaign_uid:
                    campaign_name = str(row.get("name") or "").strip()
                    break

        self.provider_settings.campaign_managed_storage = managed_storage
        self.provider_settings.campaign_base_dir = base_dir
        self.provider_settings.campaign_uid = campaign_uid
        self.provider_settings.campaign_name = campaign_name or campaign_uid

        try:
            self._configure_campaign_storage()
            project_context = self._activate_campaign_project_context()
            self.settings_service.save(self.provider_settings)
            if self.dock is not None:
                self.dock.load_settings(self.provider_settings)
                self.dock.set_campaign_context(self._campaign_context_payload())
            if not self._campaign_storage_enabled():
                success_message = f"Campaign context applied: {self.current_campaign_uid}"
            elif bool(project_context.get("project_exists")):
                success_message = f"Campaign context applied and project opened: {self.current_campaign_uid}"
            else:
                success_message = (
                    f"Campaign context applied: {self.current_campaign_uid} "
                    "(project file does not exist yet; click Save to create it)."
                )
            if create_new:
                success_message = (
                    f"New campaign created and applied: {self.current_campaign_uid} "
                    "(project file does not exist yet; click Save to create it)."
                )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                success_message,
                level=Qgis.Success,
                duration=10,
            )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Campaign context update failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )

    def _campaign_geoprocessing_output_path(self, *, operation, suffix, hint=""):
        normalized_suffix = str(suffix or "").strip() or ".bin"
        if not normalized_suffix.startswith("."):
            normalized_suffix = f".{normalized_suffix}"

        if self._campaign_storage_enabled() and self.current_campaign_uid:
            self.campaign_storage.ensure_campaign_tree(
                self.current_campaign_uid,
                campaign_name=str(self.provider_settings.campaign_name or "").strip(),
            )
            return self.campaign_storage.campaign_geoprocessing_output_path(
                self.current_campaign_uid,
                operation=str(operation or "output"),
                suffix=normalized_suffix,
                hint=str(hint or "").strip(),
            )

        fallback_dir = self.temp_dir / "geoprocessing_outputs"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        op = self.campaign_storage.sanitize_component(str(operation or "output"), fallback="output")
        hint_token = self.campaign_storage.sanitize_component(str(hint or op), fallback=op)
        candidate = fallback_dir / f"{op}_{hint_token}_{stamp}{normalized_suffix}"
        return candidate

    def workflow_begin_run_context(self):
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        run_id = f"run_{stamp}"
        if self._campaign_storage_enabled() and self.current_campaign_uid:
            run_paths = self.campaign_storage.campaign_workflow_run_paths(self.current_campaign_uid, run_id)
            self._workflow_execution_temp_dir = run_paths["intermediate"]
        else:
            run_root = self.temp_dir / "workflow_runs" / run_id
            run_root.mkdir(parents=True, exist_ok=True)
            self._workflow_execution_temp_dir = run_root / "intermediate"
            self._workflow_execution_temp_dir.mkdir(parents=True, exist_ok=True)
        return run_id

    def workflow_end_run_context(self):
        self._workflow_execution_temp_dir = self.temp_dir

    def workflow_resolve_output_template(
        self,
        *,
        run_id,
        node_id,
        function_id,
        suffix,
        hint="",
        include_index_token=False,
    ):
        normalized_suffix = str(suffix or "").strip() or ".bin"
        if not normalized_suffix.startswith("."):
            normalized_suffix = f".{normalized_suffix}"
        output_hint = str(hint or "").strip()

        if self._campaign_storage_enabled() and self.current_campaign_uid:
            return self.campaign_storage.campaign_workflow_output_template(
                self.current_campaign_uid,
                run_id=str(run_id or ""),
                node_id=str(node_id or ""),
                function_id=str(function_id or ""),
                suffix=normalized_suffix,
                hint=output_hint,
                include_index_token=bool(include_index_token),
            )

        run_root = self.temp_dir / "workflow_runs" / self.campaign_storage.sanitize_component(
            str(run_id or "run"),
            fallback="run",
        )
        output_dir = run_root / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        node_key = self.campaign_storage.sanitize_component(str(node_id or "node"), fallback="node")
        function_key = self.campaign_storage.sanitize_component(str(function_id or "function"), fallback="function")
        hint_key = self.campaign_storage.sanitize_component(output_hint or function_key, fallback=function_key)
        file_name = f"{node_key}_{function_key}_{hint_key}"
        if include_index_token:
            file_name = f"{file_name}_{{index_03}}"
        return output_dir / f"{file_name}{normalized_suffix}"

    def workflow_source_cache_dir(self):
        if self._campaign_storage_enabled() and self.current_campaign_uid:
            return self.campaign_storage.campaign_workflow_source_cache_dir(self.current_campaign_uid)
        cache_dir = self.temp_dir / "workflow_source_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def search_asset_cache_dir(self, *, item, workflow=False):
        row = item if isinstance(item, dict) else {}
        source_id = str(row.get("source_id") or "").strip() or "unknown-source"
        item_id = str(row.get("id") or "").strip() or "item"
        if self._campaign_storage_enabled() and self.current_campaign_uid:
            return self.campaign_storage.campaign_imagery_cache_dir(
                self.current_campaign_uid,
                source_id=source_id,
                item_id=item_id,
                workflow=bool(workflow),
            )
        cache_dir = self.temp_dir / "imagery_cache" / self.campaign_storage.sanitize_component(source_id) / self.campaign_storage.sanitize_component(item_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def workflow_temp_dir(self):
        path = Path(self._workflow_execution_temp_dir or self.temp_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_processing_runtime(self, *, required_algorithms):
        return ensure_processing_runtime(
            required_algorithms=required_algorithms,
            log_callback=lambda message, level=Qgis.Info: self._append_debug_log(
                f"[Processing] {message}",
                level=level,
            ),
        )

    def handle_create_vrt_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        layer_ids_raw = request.get("layer_ids") if isinstance(request.get("layer_ids"), list) else []
        layer_ids = []
        for value in layer_ids_raw:
            layer_id = str(value or "").strip()
            if layer_id and layer_id not in layer_ids:
                layer_ids.append(layer_id)

        output_path_value = str(request.get("output_path") or "").strip()
        output_name_hint = str(request.get("output_name_hint") or "").strip()
        if not layer_ids:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Create VRT request is missing input layers.",
                level=Qgis.Warning,
                duration=8,
            )
            return
        try:
            if not output_path_value:
                output_path_value = str(
                    self._campaign_geoprocessing_output_path(
                        operation="create_vrt",
                        suffix=".vrt",
                        hint=output_name_hint or "vrt",
                    )
                )
            elif not output_path_value.lower().endswith(".vrt"):
                output_path_value = f"{output_path_value}.vrt"
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Create VRT output path could not be resolved: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            return

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
            self._ensure_processing_runtime(required_algorithms=("gdal:buildvirtualraster",))
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

    def handle_mosaicking_studio_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        studio = request.get("_studio")
        include_debug_information = bool(request.get("include_debug_information", False))
        studio_log_signal = (
            studio.processing_log_received
            if studio is not None and hasattr(studio, "processing_log_received")
            else None
        )
        studio_log_buffer = MosaickingLogBuffer()

        def _drain_studio_log():
            if studio_log_signal is not None:
                studio_log_buffer.drain(studio_log_signal.emit)

        studio_log_timer = None
        if studio is not None and studio_log_signal is not None:
            studio_log_timer = QTimer(studio)
            studio_log_timer.setInterval(75)
            studio_log_timer.timeout.connect(_drain_studio_log)
            studio_log_timer.start()
            studio._mosaicking_log_timer = studio_log_timer

        def _emit_studio_log(message):
            studio_log_buffer.publish(message)

        def _emit_studio_debug(message):
            if include_debug_information:
                _emit_studio_log(f"DEBUG: {str(message or '').strip()}")

        def _finish_studio(*, success, message):
            _drain_studio_log()
            if studio is not None and hasattr(studio, "finish_processing"):
                studio.finish_processing(success=success, message=message)

        _emit_studio_debug("Plugin request handler entered.")
        raw_layer_ids = request.get("layer_ids") if isinstance(request.get("layer_ids"), list) else []
        layer_ids = []
        for value in raw_layer_ids:
            layer_id = str(value or "").strip()
            if layer_id and layer_id not in layer_ids:
                layer_ids.append(layer_id)

        try:
            input_paths = []
            unsupported_layers = []
            for layer_id in layer_ids:
                layer = self._project_raster_layer_by_id(layer_id)
                if layer is None:
                    unsupported_layers.append(layer_id)
                    continue
                input_path = self._resolve_local_raster_source_path(layer)
                if not input_path:
                    unsupported_layers.append(str(layer.name() or layer_id))
                    continue
                input_paths.append(input_path)

            if unsupported_layers:
                raise ValueError(
                    "Mosaicker_v2 currently requires local raster files. Unsupported layer(s): "
                    + ", ".join(unsupported_layers)
                )

            normalized = normalize_mosaicking_request(
                input_paths=input_paths,
                output_path=str(request.get("output_path") or "").strip(),
                overwrite=bool(request.get("overwrite", False)),
            )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Mosaicking Studio request is invalid: {exc}",
                level=Qgis.Warning,
                duration=12,
            )
            self._append_debug_log(f"Mosaicking Studio validation failed: {exc}", level=Qgis.Warning)
            _finish_studio(
                success=False,
                message=f"Request validation failed: {exc}",
            )
            return

        output_path = str(normalized.output_path)
        input_path_values = [str(path) for path in normalized.input_paths]
        overwrite = bool(normalized.overwrite)
        self._append_debug_log(
            "Mosaicking Studio request: "
            f"inputs={len(input_path_values)} output={output_path} overwrite={overwrite}"
        )
        _emit_studio_log(f"Validated {len(input_path_values)} local raster inputs.")
        _emit_studio_debug(f"Resolved output path: {output_path}")
        self.iface.messageBar().pushMessage(
            "Image Mate",
            f"Mosaic generation started in the task manager: {Path(output_path).name}",
            level=Qgis.Info,
            duration=8,
        )

        def _run_mosaicker(task):
            try:
                _emit_studio_debug("QGIS background worker entered.")
                if task.isCanceled():
                    raise RuntimeError("Mosaic task was canceled before processing started.")
                _emit_studio_debug("Background task is active and not canceled.")
                return self.mosaicking_service.create_mosaic(
                    input_paths=input_path_values,
                    output_path=output_path,
                    overwrite=overwrite,
                    progress_callback=task.setProgress,
                    log_callback=_emit_studio_log,
                    debug_callback=_emit_studio_debug,
                )
            except Exception as exc:
                _emit_studio_debug(
                    f"Background worker raised {type(exc).__name__}: {exc}"
                )
                raise

        task_outcome = {"reported": False}

        def _mosaicker_finished(exception, result=None):
            task_outcome["reported"] = True
            _emit_studio_debug(
                "QGIS completion callback entered with "
                f"exception={exception!r}; result_type={type(result).__name__}."
            )
            if exception is not None:
                self.iface.messageBar().pushMessage(
                    "Image Mate",
                    f"Mosaic generation failed: {exception}",
                    level=Qgis.Warning,
                    duration=15,
                )
                self._append_debug_log(f"Mosaic generation failed: {exception}", level=Qgis.Warning)
                _finish_studio(
                    success=False,
                    message=f"Mosaic generation failed: {exception}",
                )
                return

            result_row = result if isinstance(result, dict) else {}
            result_path = str(result_row.get("output_path") or output_path).strip()
            mosaic_layer = QgsRasterLayer(result_path, f"Image Mate Mosaic {Path(result_path).stem}")
            if not mosaic_layer.isValid():
                self.iface.messageBar().pushMessage(
                    "Image Mate",
                    f"Mosaic was created but QGIS could not load it: {result_path}",
                    level=Qgis.Warning,
                    duration=15,
                )
                self._append_debug_log(
                    f"Mosaic output is invalid in QGIS: {result_path}",
                    level=Qgis.Warning,
                )
                _finish_studio(
                    success=False,
                    message=f"Mosaic was created but QGIS could not load it: {result_path}",
                )
                return

            self._add_layer_to_image_mate_group(mosaic_layer)
            elapsed = float(result_row.get("elapsed_seconds") or 0.0)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Mosaic created and added to the project: {result_path}",
                level=Qgis.Success,
                duration=12,
            )
            self._append_debug_log(
                "Mosaic generation completed: "
                f"inputs={result_row.get('input_count') or len(input_path_values)} "
                f"elapsed_seconds={elapsed:.1f} output={result_path} "
                f"analysis={result_row.get('analysis_path') or '(none)'}"
            )
            _finish_studio(
                success=True,
                message=f"Mosaic created and added to the project: {result_path}",
            )

        def _report_unhandled_termination(exception):
            if task_outcome["reported"]:
                return
            task_outcome["reported"] = True
            detail = str(exception or "QGIS terminated the task without an exception detail.")
            _emit_studio_debug(f"Termination fallback captured: {detail}")
            self._append_debug_log(
                f"Mosaic task terminated before its completion callback: {detail}",
                level=Qgis.Warning,
            )
            _finish_studio(
                success=False,
                message=f"Mosaic task terminated: {detail}",
            )

        def _task_terminated():
            exception = getattr(task, "exception", None)
            QTimer.singleShot(
                0,
                lambda captured_exception=exception: (
                    _report_unhandled_termination(captured_exception)
                ),
            )

        try:
            _emit_studio_debug("Constructing QgsTask.fromFunction task.")
            task = QgsTask.fromFunction(
                f"Image Mate Mosaicking Studio: {Path(output_path).name}",
                _run_mosaicker,
                on_finished=_mosaicker_finished,
            )
            if studio is not None and hasattr(studio, "processing_progress_received"):
                task.progressChanged.connect(studio.processing_progress_received.emit)
                _emit_studio_debug("Connected QGIS task progress to the studio progress bar.")
            if include_debug_information:
                task_status_names = {
                    int(QgsTask.Queued): "Queued",
                    int(QgsTask.OnHold): "On hold",
                    int(QgsTask.Running): "Running",
                    int(QgsTask.Complete): "Complete",
                    int(QgsTask.Terminated): "Terminated",
                }
                task.statusChanged.connect(
                    lambda status: _emit_studio_debug(
                        "QGIS task status changed: "
                        f"{task_status_names.get(int(status), 'Unknown')} ({int(status)})."
                    )
                )
            task.taskTerminated.connect(_task_terminated)
            task_id = QgsApplication.taskManager().addTask(task)
            _emit_studio_log(f"Background task submitted to QGIS (task id {task_id}).")
            _emit_studio_debug("Waiting for the QGIS task manager to start the worker.")
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Could not submit the mosaic task: {exc}",
                level=Qgis.Warning,
                duration=15,
            )
            self._append_debug_log(
                f"Mosaic task submission failed: {exc}",
                level=Qgis.Warning,
            )
            _finish_studio(
                success=False,
                message=f"Could not submit the mosaic task: {exc}",
            )

    def handle_sharpen_image_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        layer_id = str(request.get("layer_id") or "").strip()
        output_path_value = str(request.get("output_path") or "").strip()
        output_name_hint = str(request.get("output_name_hint") or "").strip()

        try:
            factor = float(request.get("factor") or 1.0)
        except Exception:
            factor = 1.0
        if factor <= 0:
            factor = 1.0

        if not layer_id:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Sharpen Image request is missing input layer.",
                level=Qgis.Warning,
                duration=8,
            )
            return
        try:
            if not output_path_value:
                output_path_value = str(
                    self._campaign_geoprocessing_output_path(
                        operation="sharpen",
                        suffix=".tif",
                        hint=output_name_hint or "sharpen",
                    )
                )
            elif not output_path_value.lower().endswith((".tif", ".tiff")):
                output_path_value = f"{output_path_value}.tif"
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Sharpen output path could not be resolved: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            return

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

    def handle_resample_image_10m_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        layer_id = str(request.get("layer_id") or "").strip()
        output_path_value = str(request.get("output_path") or "").strip()
        output_name_hint = str(request.get("output_name_hint") or "").strip()

        try:
            target_resolution_m = float(request.get("target_resolution_m") or 10.0)
        except Exception:
            target_resolution_m = 10.0
        if target_resolution_m <= 0:
            target_resolution_m = 10.0

        if not layer_id:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Resample to 10m request is missing input layer.",
                level=Qgis.Warning,
                duration=8,
            )
            return

        try:
            chain_result = self._execute_resample_chain(
                layer_id=layer_id,
                stage_resolutions_m=(target_resolution_m,),
                output_name_hint=output_name_hint,
                output_path_value=output_path_value,
                operation_prefix="resample_10m",
                default_output_hint="resample_10m",
                request_label="Resample to 10m request",
            )
            result_path = chain_result["output_path"]
            resampled_layer = QgsRasterLayer(str(result_path), f"Image Mate Resample 10m {result_path.stem}")
            if not resampled_layer.isValid():
                raise RuntimeError(f"Resampled output raster is invalid: {result_path}")

            self._add_layer_to_image_mate_group(resampled_layer)
            reprojection_note = str(chain_result.get("reprojection_note") or "").strip()
            if reprojection_note:
                self._append_search_log(reprojection_note, level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Resample to 10m completed and added to project: {result_path}",
                level=Qgis.Success,
                duration=10,
            )
            self._append_debug_log(f"Resample 10m created successfully: {result_path}")
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Resample to 10m failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            self._append_debug_log(f"Resample to 10m failed: {exc}", level=Qgis.Warning)

    def handle_resample_image_10p8_to_3m_request(self, payload):
        self._handle_resample_chain_workflow_request(
            payload=payload,
            workflow=RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M,
        )

    def handle_resample_image_2m_to_1m_request(self, payload):
        self._handle_resample_chain_workflow_request(
            payload=payload,
            workflow=RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M,
        )

    def handle_resample_image_3p76m_to_1m_request(self, payload):
        self._handle_resample_chain_workflow_request(
            payload=payload,
            workflow=RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M,
        )

    def handle_generate_time_lapse_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        try:
            frame_specs = normalize_time_lapse_frames(request.get("frames"))
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Generate Time Lapse request is invalid: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            return

        fps = normalize_time_lapse_fps(request.get("frames_per_second"), default=2, min_value=1, max_value=60)
        output_path_value = str(request.get("output_path") or "").strip()
        output_name_hint = str(request.get("output_name_hint") or "").strip()

        try:
            if not output_path_value:
                output_path_value = str(
                    self._campaign_geoprocessing_output_path(
                        operation="time_lapse_video",
                        suffix=".mp4",
                        hint=output_name_hint or "time_lapse",
                    )
                )
            elif not output_path_value.lower().endswith(".mp4"):
                output_path_value = f"{output_path_value}.mp4"
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Time lapse output path could not be resolved: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            return

        output_path = Path(output_path_value)
        if output_path.parent and not output_path.parent.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)

        canvas = self.iface.mapCanvas() if self.iface is not None else None
        map_extent = None
        destination_crs = None
        if canvas is not None:
            try:
                current_extent = canvas.extent()
                if current_extent is not None and not current_extent.isEmpty():
                    map_extent = QgsRectangle(current_extent)
            except Exception:
                map_extent = None
            try:
                map_crs = canvas.mapSettings().destinationCrs()
                if map_crs is not None and map_crs.isValid():
                    destination_crs = map_crs
            except Exception:
                destination_crs = None

        self._append_debug_log(
            "Generate Time Lapse request: "
            f"frames={len(frame_specs)} fps={fps} output={output_path}"
        )

        try:
            result = self.time_lapse_video_service.render_project_time_lapse(
                frame_specs=frame_specs,
                output_path=output_path,
                frames_per_second=fps,
                temp_dir=self.temp_dir,
                map_extent=map_extent,
                destination_crs=destination_crs,
                log_callback=lambda message, level=Qgis.Info: self._append_debug_log(
                    f"[Time Lapse] {message}",
                    level=level,
                ),
            )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Time lapse video created: {result.get('output_path')}",
                level=Qgis.Success,
                duration=10,
            )
            self._append_debug_log(
                "Time lapse generated successfully: "
                f"path={result.get('output_path')} "
                f"frames={result.get('frame_count')} sequence_frames={result.get('sequence_frames')}"
            )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Generate Time Lapse failed: {exc}",
                level=Qgis.Warning,
                duration=12,
            )
            self._append_debug_log(f"Generate Time Lapse failed: {exc}", level=Qgis.Warning)

    def _handle_resample_chain_workflow_request(self, *, payload, workflow: ResampleWorkflowSpec):
        request = payload if isinstance(payload, dict) else {}
        layer_id = str(request.get("layer_id") or "").strip()
        output_path_value = str(request.get("output_path") or "").strip()
        output_name_hint = str(request.get("output_name_hint") or "").strip()

        if not layer_id:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"{workflow.action_label} request is missing input layer.",
                level=Qgis.Warning,
                duration=8,
            )
            return

        try:
            chain_result = self._execute_resample_chain(
                layer_id=layer_id,
                stage_resolutions_m=workflow.stage_resolutions_m,
                output_name_hint=output_name_hint,
                output_path_value=output_path_value,
                operation_prefix=workflow.operation_key,
                default_output_hint=workflow.default_output_hint,
                request_label=workflow.action_label,
            )
            result_path = chain_result["output_path"]
            resampled_layer = QgsRasterLayer(str(result_path), f"{workflow.layer_name_prefix} {result_path.stem}")
            if not resampled_layer.isValid():
                raise RuntimeError(f"Resampled output raster is invalid: {result_path}")

            self._add_layer_to_image_mate_group(resampled_layer)
            reprojection_note = str(chain_result.get("reprojection_note") or "").strip()
            if reprojection_note:
                self._append_search_log(reprojection_note, level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"{workflow.action_label} completed and added to project: {result_path}",
                level=Qgis.Success,
                duration=10,
            )
            self._append_debug_log(f"{workflow.action_label} created successfully: {result_path}")
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"{workflow.action_label} failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            self._append_debug_log(f"{workflow.action_label} failed: {exc}", level=Qgis.Warning)

    def _execute_resample_chain(
        self,
        *,
        layer_id,
        stage_resolutions_m,
        output_name_hint,
        output_path_value,
        operation_prefix,
        default_output_hint,
        request_label,
    ):
        normalized_resolutions = []
        for value in stage_resolutions_m or []:
            try:
                resolution_m = float(value)
            except Exception:
                continue
            if resolution_m > 0:
                normalized_resolutions.append(resolution_m)
        if not normalized_resolutions:
            raise RuntimeError("No valid target resolutions were provided for resampling.")

        layer, input_path, src_crs, target_crs, reprojection_note = self._resolve_resample_layer_context(layer_id=layer_id)
        self._ensure_processing_runtime(required_algorithms=("gdal:warpreproject",))

        current_input_path = Path(input_path)
        current_source_crs = src_crs
        final_output_path = None
        stage_count = len(normalized_resolutions)
        stage_hint_base = str(output_name_hint or default_output_hint or operation_prefix).strip() or operation_prefix

        for stage_index, target_resolution_m in enumerate(normalized_resolutions, start=1):
            is_final_stage = stage_index == stage_count
            stage_operation = operation_prefix if is_final_stage else f"{operation_prefix}_stage{stage_index}"
            stage_output_path_value = output_path_value if is_final_stage else ""
            if is_final_stage:
                stage_hint = stage_hint_base
            else:
                stage_hint = f"{stage_hint_base}_stage{stage_index}_{resolution_hint_token(target_resolution_m)}"
            stage_output_path = self._resolve_resample_output_path(
                operation=stage_operation,
                output_name_hint=stage_hint,
                output_path_value=stage_output_path_value,
            )
            self._append_debug_log(
                f"{request_label} stage={stage_index}/{stage_count} "
                f"layer={layer.name()} input={current_input_path} "
                f"resolution_m={target_resolution_m:.2f} target_crs={target_crs.authid() or 'unknown'} "
                f"output={stage_output_path}"
            )
            final_output_path = self._run_resample_step(
                input_path=current_input_path,
                source_crs=current_source_crs,
                target_crs=target_crs,
                target_resolution_m=target_resolution_m,
                output_path=stage_output_path,
            )
            current_input_path = final_output_path
            current_source_crs = target_crs

        return {
            "output_path": Path(final_output_path),
            "reprojection_note": reprojection_note,
        }

    def _resolve_resample_output_path(self, *, operation, output_name_hint, output_path_value):
        output_path_text = str(output_path_value or "").strip()
        if not output_path_text:
            output_path_text = str(
                self._campaign_geoprocessing_output_path(
                    operation=operation,
                    suffix=".tif",
                    hint=output_name_hint or operation,
                )
            )
        elif not output_path_text.lower().endswith((".tif", ".tiff")):
            output_path_text = f"{output_path_text}.tif"

        output_path = Path(output_path_text)
        if output_path.parent and not output_path.parent.exists():
            output_path.parent.mkdir(parents=True, exist_ok=True)
        return output_path

    def _resolve_resample_layer_context(self, *, layer_id):
        layer = self._project_raster_layer_by_id(layer_id)
        if layer is None:
            raise RuntimeError(f"Raster layer not found in project: {layer_id}")

        input_path = self._resolve_local_raster_source_path(layer)
        if not input_path:
            provider_name = str(layer.providerType() or "").strip() or "unknown"
            layer_source = str(layer.source() or "").strip()
            provider_uri = ""
            try:
                provider = layer.dataProvider()
                provider_uri = str(provider.dataSourceUri() or "").strip() if provider is not None else ""
            except Exception:
                provider_uri = ""
            self._append_debug_log(
                "Resample input rejected: "
                f"layer={layer.name()} provider={provider_name} source={layer_source} uri={provider_uri}",
                level=Qgis.Warning,
            )
            raise RuntimeError("Resample requires a local raster file layer or local VRT (not remote stream).")

        src_crs = layer.crs()
        if src_crs is None or not src_crs.isValid():
            raise RuntimeError("Input raster CRS is invalid.")

        target_crs = src_crs
        reprojection_note = ""
        try:
            map_units = src_crs.mapUnits()
        except Exception:
            map_units = QgsUnitTypes.DistanceUnknownUnit
        if int(map_units) != int(QgsUnitTypes.DistanceMeters):
            target_crs = QgsCoordinateReferenceSystem("EPSG:3857")
            reprojection_note = (
                f"Input CRS {src_crs.authid() or 'unknown'} is not meter-based; "
                "resampling in EPSG:3857."
            )
        return layer, Path(input_path), src_crs, target_crs, reprojection_note

    def _run_resample_step(self, *, input_path, source_crs, target_crs, target_resolution_m, output_path):
        params = {
            "INPUT": str(input_path),
            "SOURCE_CRS": source_crs,
            "TARGET_CRS": target_crs,
            "RESAMPLING": 1,  # Bilinear
            "NODATA": None,
            "TARGET_RESOLUTION": float(target_resolution_m),
            "OPTIONS": "",
            "DATA_TYPE": 0,
            "TARGET_EXTENT": None,
            "TARGET_EXTENT_CRS": None,
            "MULTITHREADING": True,
            "EXTRA": "",
            "OUTPUT": str(output_path),
        }
        result = processing.run("gdal:warpreproject", params)
        result_path_text = str(result.get("OUTPUT") or output_path).strip()
        if not result_path_text:
            raise RuntimeError("gdal:warpreproject returned an empty output path")
        result_path = Path(result_path_text)
        if not result_path.exists():
            raise RuntimeError(f"Resampled output file was not created: {result_path}")
        return result_path

    def handle_vessel_detect_request(self, payload):
        request = dict(payload) if isinstance(payload, dict) else {}
        if "single_best_only" not in request:
            request["single_best_only"] = False
        if not str(request.get("output_name_hint") or "").strip():
            request["output_name_hint"] = "current_extent"
        self._append_debug_log(
            "Vessel detection request redirected to current-extent mode."
        )
        self.handle_vessel_detect_current_extent_request(request)

    def handle_vessel_detect_current_extent_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        variant_key = str(request.get("detection_variant") or "bb").strip().lower()
        if variant_key not in {"bb", "obb"}:
            variant_key = "bb"
        model_path = self._resolve_vessel_model_path_for_variant(request=request, variant=variant_key)
        output_name_hint = str(request.get("output_name_hint") or "current_extent").strip()
        single_best_only = bool(request.get("single_best_only", True))
        autofill_filters = bool(request.get("autofill_asset_intel_filters", True))
        create_qa_layer = bool(request.get("create_qa_layer", False))

        try:
            conf_threshold = float(
                request.get("conf_threshold", getattr(self.provider_settings, "vessel_conf_threshold_default", 0.25))
            )
        except Exception:
            conf_threshold = float(getattr(self.provider_settings, "vessel_conf_threshold_default", 0.25) or 0.25)
        try:
            iou_threshold = float(
                request.get("iou_threshold", getattr(self.provider_settings, "vessel_iou_threshold_default", 0.45))
            )
        except Exception:
            iou_threshold = float(getattr(self.provider_settings, "vessel_iou_threshold_default", 0.45) or 0.45)
        try:
            max_detections = int(
                request.get("max_detections", getattr(self.provider_settings, "vessel_max_detections_default", 20))
            )
        except Exception:
            max_detections = int(getattr(self.provider_settings, "vessel_max_detections_default", 20) or 20)
        try:
            min_context_px = int(request.get("min_context_px", 1024))
        except Exception:
            min_context_px = 1024
        min_context_px = max(256, min(4096, int(min_context_px)))

        if not model_path:
            if variant_key == "obb":
                guidance = (
                    "Detect Vessel (OBB) requires a default OBB ONNX model path. "
                    "Set VESSEL_OBB_MODEL_DEFAULT_PATH in .env."
                )
            else:
                guidance = "Detect Vessel requires a default ONNX model path. Set it in Integrations > Vessel Detection."
            self.iface.messageBar().pushMessage(
                "Image Mate",
                guidance,
                level=Qgis.Warning,
                duration=10,
            )
            return

        try:
            started_at = time.perf_counter()
            self._append_debug_log(
                "Vessel extent detection stage=resolve_raster "
                f"variant={variant_key} model={model_path} conf={conf_threshold:.2f} "
                f"iou={iou_threshold:.2f} max_det={max_detections}",
                level=Qgis.Info,
            )
            layer, input_path, extent_in_layer_crs = self._resolve_local_raster_for_current_extent_detection()
            self._append_debug_log(
                "Vessel extent detection stage=resolve_raster_done "
                f"layer={layer.name()} input={input_path}",
                level=Qgis.Info,
            )
            chip_hint = f"{layer.name()}_extent_vessel"
            self._append_debug_log(
                f"Vessel extent detection stage=chip_export_start hint={chip_hint}",
                level=Qgis.Info,
            )
            chip_path = self._export_raster_extent_chip(
                input_path=str(input_path),
                extent_in_layer_crs=extent_in_layer_crs,
                hint=chip_hint,
                min_context_px=min_context_px,
            )
            self._append_debug_log(
                f"Vessel extent detection stage=chip_export_done chip={chip_path}",
                level=Qgis.Info,
            )

            self._append_debug_log(
                "Vessel extent detection request: "
                f"variant={variant_key} layer={layer.name()} input={input_path} chip={chip_path} model={model_path} "
                f"conf={conf_threshold:.2f} iou={iou_threshold:.2f} max_det={max_detections}"
            )
            inference_started_at = time.perf_counter()
            detections = self.vessel_detection_service.detect(
                layer_path=str(chip_path),
                model_path=str(model_path),
                conf=float(conf_threshold),
                iou=float(iou_threshold),
                max_det=int(max_detections),
            )
            inference_elapsed_s = max(0.0, float(time.perf_counter() - inference_started_at))
            self._append_debug_log(
                "Vessel extent detection stage=inference_done "
                f"detections={len(detections or [])} elapsed_s={inference_elapsed_s:.2f}",
                level=Qgis.Info,
            )
            if not detections:
                self.iface.messageBar().pushMessage(
                    "Image Mate",
                    "Detect Vessel completed: no vessels detected in current map extent.",
                    level=Qgis.Info,
                    duration=7,
                )
                return

            ranked = sorted(detections, key=lambda r: float(r.get("confidence") or 0.0), reverse=True)
            selected_rows = ranked[:1] if single_best_only else ranked

            model_version = Path(model_path).stem or "vessel_model"
            run_id = datetime.now(tz=timezone.utc).strftime("vessel_extent_%Y%m%dT%H%M%S%fZ")
            timestamp_utc = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
            measured_rows = []
            for idx, row in enumerate(selected_rows, start=1):
                measured = self._measure_vessel_dimensions(
                    layer=layer,
                    input_path=str(chip_path),
                    detection=row,
                )
                merged = dict(row)
                merged.update(measured)
                merged["run_id"] = run_id
                merged["timestamp_utc"] = timestamp_utc
                merged["model_version"] = model_version
                merged["source_layer_id"] = layer.id()
                merged["scene_id"] = f"{layer.id()}_current_extent"
                if single_best_only:
                    merged["detection_id"] = "det_001"
                else:
                    merged["detection_id"] = f"det_{idx:03d}"
                measured_rows.append(merged)

            layer_name_hint = output_name_hint or f"{layer.name()}_extent"
            result_layer = self._build_vessel_detection_layer(
                source_layer=layer,
                detections=measured_rows,
                layer_name_hint=layer_name_hint,
            )
            self._add_layer_to_image_mate_group(result_layer, insert_on_top=True)

            if create_qa_layer:
                qa_layer = self._build_vessel_qa_layer_from_detection_rows(
                    source_layer=layer,
                    detections=measured_rows,
                    layer_name_hint=layer_name_hint,
                )
                self._add_layer_to_image_mate_group(qa_layer, insert_on_top=True)

            if autofill_filters:
                self._apply_asset_intel_vessel_size_filters(measured_rows)

            total_elapsed_s = max(0.0, float(time.perf_counter() - started_at))
            self._append_debug_log(
                "Vessel extent detection stage=complete "
                f"features={len(measured_rows)} elapsed_s={total_elapsed_s:.2f}",
                level=Qgis.Info,
            )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Detect Vessel completed: {len(measured_rows)} boundary feature(s) added from current extent.",
                level=Qgis.Success,
                duration=10,
            )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Detect Vessel failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            self._append_debug_log(f"Detect Vessel failed: {exc}", level=Qgis.Warning)
            self._append_debug_log(traceback.format_exc(), level=Qgis.Warning)

    def _resolve_vessel_model_path_for_variant(self, *, request, variant):
        req = request if isinstance(request, dict) else {}
        if variant == "obb":
            request_path = str(req.get("model_path") or req.get("obb_model_path") or "").strip()
            if request_path:
                return request_path

            configured_path = str(getattr(self.provider_settings, "vessel_obb_model_default_path", "") or "").strip()
            if configured_path:
                return configured_path

            env_path = str(os.getenv("VESSEL_OBB_MODEL_DEFAULT_PATH", "") or "").strip()
            if env_path:
                return env_path

            bb_path = str(getattr(self.provider_settings, "vessel_model_default_path", "") or "").strip()
            candidates = []
            if bb_path:
                bb_obj = Path(bb_path).expanduser()
                if bb_obj.parent.name:
                    candidates.append(bb_obj.parent.parent / "yolo11n_obb_pretrained" / "model.onnx")
                    candidates.append(bb_obj.parent.parent / "yolo11n_obb_pretrained" / bb_obj.name)
                    candidates.append(bb_obj.parent / "yolo11n-obb.onnx")
            candidates.append(
                Path.home()
                / "Documents"
                / "Personal"
                / "dev"
                / "image-mate"
                / "ml"
                / "vessel"
                / "models"
                / "yolo11n_obb_pretrained"
                / "model.onnx"
            )
            try:
                candidates.append(
                    Path(__file__).resolve().parents[2]
                    / "ml"
                    / "vessel"
                    / "models"
                    / "yolo11n_obb_pretrained"
                    / "model.onnx"
                )
            except Exception:
                pass
            for candidate in candidates:
                try:
                    if candidate.exists():
                        return str(candidate)
                except Exception:
                    continue
            return ""

        return str(
            req.get("model_path")
            or getattr(self.provider_settings, "vessel_model_default_path", "")
            or ""
        ).strip()

    def _resolve_local_raster_for_current_extent_detection(self):
        canvas = self.iface.mapCanvas() if self.iface is not None else None
        if canvas is None:
            raise RuntimeError("Map canvas is unavailable.")
        current_extent = canvas.extent()
        if current_extent is None or current_extent.isEmpty():
            raise RuntimeError("Current map extent is empty.")

        candidate_layers = []
        active_layer = self.iface.activeLayer() if self.iface is not None else None
        if isinstance(active_layer, QgsRasterLayer):
            candidate_layers.append(active_layer)

        seen_layer_ids = {str(active_layer.id() or "").strip()} if isinstance(active_layer, QgsRasterLayer) else set()
        try:
            ordered_layers = QgsProject.instance().layerTreeRoot().layerOrder()
        except Exception:
            ordered_layers = []
        for layer in ordered_layers or []:
            if not isinstance(layer, QgsRasterLayer):
                continue
            layer_id = str(layer.id() or "").strip()
            if not layer_id or layer_id in seen_layer_ids:
                continue
            seen_layer_ids.add(layer_id)
            candidate_layers.append(layer)
        if not candidate_layers:
            for layer in QgsProject.instance().mapLayers().values():
                if not isinstance(layer, QgsRasterLayer):
                    continue
                layer_id = str(layer.id() or "").strip()
                if not layer_id or layer_id in seen_layer_ids:
                    continue
                seen_layer_ids.add(layer_id)
                candidate_layers.append(layer)

        for layer in candidate_layers:
            if layer is None or not layer.crs().isValid():
                continue
            input_path = self._resolve_local_raster_source_path(layer)
            if not input_path:
                continue
            try:
                extent_in_layer_crs = self._current_map_extent_in_layer_crs(layer)
            except Exception:
                continue
            clipped_extent = self._extent_intersection(extent_in_layer_crs, layer.extent())
            if clipped_extent is None or clipped_extent.isEmpty():
                continue
            return layer, input_path, clipped_extent

        raise RuntimeError(
            "No local georeferenced raster intersects the current map extent. "
            "Activate or load a local raster layer and try again."
        )

    def _current_map_extent_in_layer_crs(self, layer):
        if layer is None:
            raise RuntimeError("Raster layer is required.")
        canvas = self.iface.mapCanvas() if self.iface is not None else None
        if canvas is None:
            raise RuntimeError("Map canvas is unavailable.")
        extent = canvas.extent()
        if extent is None or extent.isEmpty():
            raise RuntimeError("Current map extent is empty.")
        map_crs = canvas.mapSettings().destinationCrs()
        layer_crs = layer.crs()
        if map_crs.isValid() and layer_crs.isValid() and map_crs != layer_crs:
            transform = QgsCoordinateTransform(map_crs, layer_crs, QgsProject.instance())
            extent = transform.transformBoundingBox(extent)
        return extent

    @staticmethod
    def _extent_intersection(left, right):
        if left is None or right is None:
            return None
        xmin = max(float(left.xMinimum()), float(right.xMinimum()))
        ymin = max(float(left.yMinimum()), float(right.yMinimum()))
        xmax = min(float(left.xMaximum()), float(right.xMaximum()))
        ymax = min(float(left.yMaximum()), float(right.yMaximum()))
        if xmax <= xmin or ymax <= ymin:
            return None
        return QgsRectangle(xmin, ymin, xmax, ymax)

    def _export_raster_extent_chip(self, *, input_path, extent_in_layer_crs, hint="extent", min_context_px=0):
        try:
            from osgeo import gdal
        except Exception as exc:
            raise RuntimeError(f"GDAL Python bindings are required for extent clipping: {exc}") from exc

        if extent_in_layer_crs is None or extent_in_layer_crs.isEmpty():
            raise RuntimeError("Cannot clip raster by empty map extent.")

        chip_extent = QgsRectangle(extent_in_layer_crs)
        if int(min_context_px or 0) > 0:
            expanded_extent = self._expand_extent_for_min_chip_pixels(
                input_path=str(input_path),
                extent_in_layer_crs=chip_extent,
                min_context_px=int(min_context_px),
            )
            if expanded_extent is not None:
                if (
                    abs(float(expanded_extent.width()) - float(chip_extent.width())) > 1e-9
                    or abs(float(expanded_extent.height()) - float(chip_extent.height())) > 1e-9
                ):
                    self._append_debug_log(
                        "Vessel extent detection stage=chip_extent_expand "
                        f"min_context_px={int(min_context_px)} "
                        f"old_w={float(chip_extent.width()):.3f} old_h={float(chip_extent.height()):.3f} "
                        f"new_w={float(expanded_extent.width()):.3f} new_h={float(expanded_extent.height()):.3f}",
                        level=Qgis.Info,
                    )
                chip_extent = expanded_extent

        output_path = self._campaign_geoprocessing_output_path(
            operation="vessel_extent_chip",
            suffix=".tif",
            hint=str(hint or "extent"),
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        proj_win = [
            float(chip_extent.xMinimum()),
            float(chip_extent.yMaximum()),
            float(chip_extent.xMaximum()),
            float(chip_extent.yMinimum()),
        ]
        options = gdal.TranslateOptions(
            format="GTiff",
            projWin=proj_win,
            creationOptions=["TILED=YES", "COMPRESS=LZW", "BIGTIFF=IF_SAFER"],
        )
        clipped_ds = gdal.Translate(str(output_path), str(input_path), options=options)
        if clipped_ds is None:
            raise RuntimeError("GDAL failed to clip raster by current map extent.")
        clipped_ds = None

        check_ds = gdal.Open(str(output_path), gdal.GA_ReadOnly)
        if check_ds is None:
            raise RuntimeError(f"Failed to open extent chip after clipping: {output_path}")
        try:
            width = int(check_ds.RasterXSize or 0)
            height = int(check_ds.RasterYSize or 0)
            if width <= 0 or height <= 0:
                raise RuntimeError("Extent chip has invalid dimensions.")
        finally:
            check_ds = None

        return str(output_path)

    def _expand_extent_for_min_chip_pixels(self, *, input_path, extent_in_layer_crs, min_context_px):
        try:
            from osgeo import gdal
        except Exception:
            return None

        min_px = max(1, int(min_context_px or 0))
        if min_px <= 1:
            return QgsRectangle(extent_in_layer_crs)

        ds = gdal.Open(str(input_path), gdal.GA_ReadOnly)
        if ds is None:
            return QgsRectangle(extent_in_layer_crs)
        try:
            width_px = int(ds.RasterXSize or 0)
            height_px = int(ds.RasterYSize or 0)
            if width_px <= 0 or height_px <= 0:
                return QgsRectangle(extent_in_layer_crs)
            try:
                gt = ds.GetGeoTransform(can_return_null=True)
            except TypeError:
                gt = ds.GetGeoTransform()
        finally:
            ds = None

        if not gt:
            return QgsRectangle(extent_in_layer_crs)

        px_size_x = float(math.hypot(float(gt[1]), float(gt[4])))
        px_size_y = float(math.hypot(float(gt[2]), float(gt[5])))
        if px_size_x <= 0.0 or px_size_y <= 0.0:
            return QgsRectangle(extent_in_layer_crs)

        current = QgsRectangle(extent_in_layer_crs)
        target_w = max(float(current.width()), float(min_px) * px_size_x)
        target_h = max(float(current.height()), float(min_px) * px_size_y)
        if target_w <= float(current.width()) and target_h <= float(current.height()):
            return current

        cx = (float(current.xMinimum()) + float(current.xMaximum())) * 0.5
        cy = (float(current.yMinimum()) + float(current.yMaximum())) * 0.5
        expanded = QgsRectangle(
            float(cx - (target_w * 0.5)),
            float(cy - (target_h * 0.5)),
            float(cx + (target_w * 0.5)),
            float(cy + (target_h * 0.5)),
        )

        corners = []
        for px, py in ((0.0, 0.0), (float(width_px), 0.0), (0.0, float(height_px)), (float(width_px), float(height_px))):
            mx = float(gt[0] + (px * gt[1]) + (py * gt[2]))
            my = float(gt[3] + (px * gt[4]) + (py * gt[5]))
            corners.append((mx, my))
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        raster_extent = QgsRectangle(float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))
        clipped = self._extent_intersection(expanded, raster_extent)
        return clipped if clipped is not None else current

    def _build_vessel_detection_layer(self, *, source_layer, detections, layer_name_hint):
        src = source_layer if source_layer is not None else None
        src_crs = src.crs() if src is not None else None
        crs_token = src_crs.authid() if src_crs is not None and src_crs.isValid() else "EPSG:4326"
        safe_hint = self.campaign_storage.sanitize_component(str(layer_name_hint or "vessels"), fallback="vessels")
        layer_name = f"Image Mate Vessel Detections {safe_hint}"
        layer = QgsVectorLayer(f"Polygon?crs={crs_token}", layer_name, "memory")
        if not layer.isValid():
            raise RuntimeError("Failed to create vessel detection output layer.")

        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("run_id", QVariant.String),
                QgsField("scene_id", QVariant.String),
                QgsField("source_layer_id", QVariant.String),
                QgsField("detection_id", QVariant.String),
                QgsField("class_id", QVariant.Int),
                QgsField("class_name", QVariant.String),
                QgsField("confidence", QVariant.Double),
                QgsField("length_m", QVariant.Double),
                QgsField("width_m", QVariant.Double),
                QgsField("model_version", QVariant.String),
                QgsField("timestamp_utc", QVariant.String),
                QgsField("measurement_warning", QVariant.String),
            ]
        )
        layer.updateFields()

        features = []
        for row in detections or []:
            map_obb = row.get("obb_map")
            if not isinstance(map_obb, list) or len(map_obb) < 4:
                continue
            ring = []
            for pair in map_obb[:4]:
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                try:
                    ring.append(QgsPointXY(float(pair[0]), float(pair[1])))
                except Exception:
                    continue
            if len(ring) < 4:
                continue
            ring.append(QgsPointXY(ring[0].x(), ring[0].y()))
            geom = QgsGeometry.fromPolygonXY([ring])
            if geom is None or geom.isEmpty():
                continue

            feature = QgsFeature(layer.fields())
            feature.setGeometry(geom)
            feature["run_id"] = str(row.get("run_id") or "")
            feature["scene_id"] = str(row.get("scene_id") or "")
            feature["source_layer_id"] = str(row.get("source_layer_id") or "")
            feature["detection_id"] = str(row.get("detection_id") or "")
            feature["class_id"] = int(row.get("class_id") or 0)
            feature["class_name"] = str(row.get("class_name") or "vessel")
            feature["confidence"] = float(row.get("confidence") or 0.0)
            feature["length_m"] = float(row.get("length_m") or 0.0)
            feature["width_m"] = float(row.get("width_m") or 0.0)
            feature["model_version"] = str(row.get("model_version") or "")
            feature["timestamp_utc"] = str(row.get("timestamp_utc") or "")
            feature["measurement_warning"] = str(row.get("measurement_warning") or "")
            features.append(feature)

        if features:
            provider.addFeatures(features)
            layer.updateExtents()
        try:
            symbol = QgsFillSymbol.createSimple(
                {
                    "style": "no",
                    "outline_color": "255,255,0,255",
                    "outline_width": "1.0",
                    "outline_style": "solid",
                }
            )
            if symbol is not None:
                layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        except Exception:
            pass
        layer.setCustomProperty("image_mate/vessel_detection_layer", "1")
        if detections:
            first_row = detections[0] if isinstance(detections[0], dict) else {}
            layer.setCustomProperty("image_mate/vessel_run_id", str(first_row.get("run_id") or ""))
            layer.setCustomProperty("image_mate/vessel_model_version", str(first_row.get("model_version") or ""))
        return layer

    def _measure_vessel_dimensions(self, *, layer, input_path, detection):
        warning = ""
        try:
            from osgeo import gdal
        except Exception as exc:
            raise RuntimeError(f"GDAL Python bindings are required for vessel dimensions: {exc}") from exc

        obb_px = detection.get("obb_px") if isinstance(detection, dict) else None
        if not isinstance(obb_px, list) or len(obb_px) < 4:
            return {
                "length_m": 0.0,
                "width_m": 0.0,
                "measurement_warning": "invalid_obb",
                "obb_map": [],
            }

        ds = gdal.Open(str(input_path), gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError(f"Could not open raster for dimension conversion: {input_path}")
        try:
            try:
                gt = ds.GetGeoTransform(can_return_null=True)
            except TypeError:
                gt = ds.GetGeoTransform()
            width = int(ds.RasterXSize or 0)
            height = int(ds.RasterYSize or 0)
        finally:
            ds = None

        if gt is None:
            warning = "missing_geotransform_fallback_extent"
            gt = None

        map_obb: list[list[float]] = []
        for pair in obb_px[:4]:
            try:
                px = float(pair[0])
                py = float(pair[1])
            except Exception:
                continue
            if gt is not None:
                mx = float(gt[0] + (px * gt[1]) + (py * gt[2]))
                my = float(gt[3] + (px * gt[4]) + (py * gt[5]))
            else:
                extent = layer.extent()
                if width <= 0 or height <= 0 or extent.isEmpty():
                    mx = 0.0
                    my = 0.0
                else:
                    mx = float(extent.xMinimum() + (px / float(width)) * float(extent.width()))
                    my = float(extent.yMaximum() - (py / float(height)) * float(extent.height()))
            map_obb.append([mx, my])

        if len(map_obb) < 4:
            return {
                "length_m": 0.0,
                "width_m": 0.0,
                "measurement_warning": "invalid_mapped_obb",
                "obb_map": map_obb,
            }

        p0, p1, p2, p3 = [tuple(float(v) for v in pair[:2]) for pair in obb_px[:4]]
        m0, m1, m2, m3 = [tuple(float(v) for v in pair[:2]) for pair in map_obb[:4]]

        def _d2(a, b):
            dx = float(a[0]) - float(b[0])
            dy = float(a[1]) - float(b[1])
            return math.hypot(dx, dy)

        edge_px_01 = _d2(p0, p1)
        edge_px_12 = _d2(p1, p2)
        edge_px_23 = _d2(p2, p3)
        edge_px_30 = _d2(p3, p0)

        mid_px_01 = ((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5)
        mid_px_23 = ((p2[0] + p3[0]) * 0.5, (p2[1] + p3[1]) * 0.5)
        mid_px_12 = ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
        mid_px_30 = ((p3[0] + p0[0]) * 0.5, (p3[1] + p0[1]) * 0.5)

        mid_map_01 = ((m0[0] + m1[0]) * 0.5, (m0[1] + m1[1]) * 0.5)
        mid_map_23 = ((m2[0] + m3[0]) * 0.5, (m2[1] + m3[1]) * 0.5)
        mid_map_12 = ((m1[0] + m2[0]) * 0.5, (m1[1] + m2[1]) * 0.5)
        mid_map_30 = ((m3[0] + m0[0]) * 0.5, (m3[1] + m0[1]) * 0.5)

        group_a = (edge_px_01 + edge_px_23) * 0.5
        group_b = (edge_px_12 + edge_px_30) * 0.5

        if group_a >= group_b:
            major_start, major_end = mid_map_01, mid_map_23
            minor_start, minor_end = mid_map_12, mid_map_30
        else:
            major_start, major_end = mid_map_12, mid_map_30
            minor_start, minor_end = mid_map_01, mid_map_23

        distance_area = QgsDistanceArea()
        distance_area.setEllipsoid(QgsProject.instance().ellipsoid() or "WGS84")
        distance_area.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())

        try:
            length_m = float(
                distance_area.measureLine(
                    QgsPointXY(float(major_start[0]), float(major_start[1])),
                    QgsPointXY(float(major_end[0]), float(major_end[1])),
                )
            )
            width_m = float(
                distance_area.measureLine(
                    QgsPointXY(float(minor_start[0]), float(minor_start[1])),
                    QgsPointXY(float(minor_end[0]), float(minor_end[1])),
                )
            )
        except Exception as exc:
            warning = f"{warning}|distance_measure_failed:{exc}" if warning else f"distance_measure_failed:{exc}"
            length_m = _d2(major_start, major_end)
            width_m = _d2(minor_start, minor_end)

        if length_m < width_m:
            length_m, width_m = width_m, length_m
        if not math.isfinite(length_m):
            length_m = 0.0
        if not math.isfinite(width_m):
            width_m = 0.0
        return {
            "length_m": round(max(0.0, float(length_m)), 2),
            "width_m": round(max(0.0, float(width_m)), 2),
            "measurement_warning": warning,
            "obb_map": map_obb,
        }

    def _apply_asset_intel_vessel_size_filters(self, detection_rows):
        if self.dock is None:
            return
        rows = detection_rows if isinstance(detection_rows, list) else []
        if not rows:
            return
        ranked = sorted(rows, key=lambda r: float(r.get("confidence") or 0.0), reverse=True)
        selected = None
        for row in ranked:
            length_m = float(row.get("length_m") or 0.0)
            width_m = float(row.get("width_m") or 0.0)
            if length_m > 0.0 and width_m > 0.0:
                selected = row
                break
        if selected is None:
            return

        length_m = float(selected.get("length_m") or 0.0)
        width_m = float(selected.get("width_m") or 0.0)
        length_min = max(0.0, length_m * 0.80)
        length_max = max(0.0, length_m * 1.20)
        width_min = max(0.0, width_m * 0.75)
        width_max = max(0.0, width_m * 1.25)

        if hasattr(self.dock, "asset_intel_length_min_input"):
            self.dock.asset_intel_length_min_input.setText(f"{length_min:.2f}")
        if hasattr(self.dock, "asset_intel_length_max_input"):
            self.dock.asset_intel_length_max_input.setText(f"{length_max:.2f}")
        if hasattr(self.dock, "asset_intel_width_min_input"):
            self.dock.asset_intel_width_min_input.setText(f"{width_min:.2f}")
        if hasattr(self.dock, "asset_intel_width_max_input"):
            self.dock.asset_intel_width_max_input.setText(f"{width_max:.2f}")

        self.handle_asset_intel_search_request(self.dock.current_asset_intel_payload())
        self.dock.set_asset_intel_status(
            "Asset Intel: vessel-derived filters applied "
            f"(L={length_m:.2f}m, W={width_m:.2f}m)."
        )

    @staticmethod
    def _asset_intel_outer_ring_points(geometry):
        geom = geometry if isinstance(geometry, QgsGeometry) else None
        if geom is None or geom.isEmpty():
            return []
        try:
            polygon = geom.asPolygon()
            if polygon and polygon[0]:
                ring = polygon[0]
            else:
                multi = geom.asMultiPolygon()
                ring = multi[0][0] if multi and multi[0] else []
        except Exception:
            return []
        points = []
        for point in ring or []:
            try:
                points.append(QgsPointXY(float(point.x()), float(point.y())))
            except Exception:
                continue
        if len(points) > 1:
            first = points[0]
            last = points[-1]
            if abs(float(first.x()) - float(last.x())) <= 1e-9 and abs(float(first.y()) - float(last.y())) <= 1e-9:
                points = points[:-1]
        return points

    @staticmethod
    def _asset_intel_oriented_bbox_geometry(geometry):
        geom = geometry if isinstance(geometry, QgsGeometry) else None
        if geom is None or geom.isEmpty():
            return None
        try:
            oriented = geom.orientedMinimumBoundingBox()
            if isinstance(oriented, QgsGeometry) and not oriented.isEmpty():
                return oriented
            if isinstance(oriented, (list, tuple)) and oriented:
                candidate = oriented[0]
                if isinstance(candidate, QgsGeometry) and not candidate.isEmpty():
                    return candidate
        except Exception:
            pass
        try:
            bbox = geom.minimumBoundingBox()
            if isinstance(bbox, QgsGeometry) and not bbox.isEmpty():
                return bbox
        except Exception:
            pass
        return None

    def _measure_asset_intel_polygon_dimensions(self, *, layer, geometry):
        if layer is None or not isinstance(layer, QgsVectorLayer):
            raise RuntimeError("Active layer must be a vector polygon layer.")
        geom = geometry if isinstance(geometry, QgsGeometry) else None
        if geom is None or geom.isEmpty():
            raise RuntimeError("Selected feature has empty geometry.")

        bbox_geom = self._asset_intel_oriented_bbox_geometry(geom)
        if bbox_geom is None or bbox_geom.isEmpty():
            raise RuntimeError("Failed to derive an oriented bounding box from the selected polygon.")

        ring = self._asset_intel_outer_ring_points(bbox_geom)
        if len(ring) < 4:
            raise RuntimeError("Bounding box ring is incomplete; expected at least 4 points.")
        p0, p1, p2, p3 = ring[:4]

        def _midpoint(a, b):
            return QgsPointXY((float(a.x()) + float(b.x())) * 0.5, (float(a.y()) + float(b.y())) * 0.5)

        mid_01 = _midpoint(p0, p1)
        mid_23 = _midpoint(p2, p3)
        mid_12 = _midpoint(p1, p2)
        mid_30 = _midpoint(p3, p0)

        distance_area = QgsDistanceArea()
        distance_area.setEllipsoid(QgsProject.instance().ellipsoid() or "WGS84")
        distance_area.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())

        def _line_m(a, b):
            try:
                measured = float(distance_area.measureLine(a, b))
                if math.isfinite(measured):
                    return measured
            except Exception:
                pass
            dx = float(a.x()) - float(b.x())
            dy = float(a.y()) - float(b.y())
            return math.hypot(dx, dy)

        line_a = _line_m(mid_01, mid_23)
        line_b = _line_m(mid_12, mid_30)

        if line_a >= line_b:
            major_start, major_end = mid_01, mid_23
            length_m = line_a
            width_m = line_b
        else:
            major_start, major_end = mid_12, mid_30
            length_m = line_b
            width_m = line_a

        dx = float(major_end.x()) - float(major_start.x())
        dy = float(major_end.y()) - float(major_start.y())
        angle_deg = (math.degrees(math.atan2(dy, dx)) + 360.0) % 180.0

        if not math.isfinite(length_m) or length_m <= 0.0:
            raise RuntimeError("Measured length is invalid.")
        if not math.isfinite(width_m) or width_m <= 0.0:
            raise RuntimeError("Measured width is invalid.")

        return {
            "length_m": round(float(length_m), 2),
            "width_m": round(float(width_m), 2),
            "angle_deg": round(float(angle_deg), 2),
        }

    def _asset_intel_polygon_pick_layers(self):
        project = QgsProject.instance()
        seen_ids = set()
        out = []

        def _append_if_supported(layer):
            if layer is None or not isinstance(layer, QgsVectorLayer):
                return
            if int(layer.geometryType()) != int(QgsWkbTypes.PolygonGeometry):
                return
            layer_id = str(layer.id() or "").strip()
            if not layer_id or layer_id in seen_ids:
                return
            node = project.layerTreeRoot().findLayer(layer_id)
            if node is not None and not bool(node.isVisible()):
                return
            seen_ids.add(layer_id)
            out.append(layer)

        active_layer = self.iface.activeLayer() if self.iface is not None else None
        _append_if_supported(active_layer)

        try:
            ordered_layers = list(project.layerTreeRoot().layerOrder() or [])
        except Exception:
            ordered_layers = []
        for layer in reversed(ordered_layers):
            _append_if_supported(layer)

        if not out:
            for layer in project.mapLayers().values():
                _append_if_supported(layer)
        return out

    def _asset_intel_pick_polygon_feature_at_map_point(self, map_point):
        canvas = self.iface.mapCanvas() if self.iface is not None else None
        if canvas is None:
            return None, None
        map_crs = canvas.mapSettings().destinationCrs()
        point_map = QgsPointXY(float(map_point.x()), float(map_point.y()))
        map_tolerance = max(float(canvas.mapUnitsPerPixel()) * 6.0, 1e-9)

        for layer in self._asset_intel_polygon_pick_layers():
            layer_point = point_map
            layer_tolerance = map_tolerance
            try:
                layer_crs = layer.crs()
                if map_crs.isValid() and layer_crs.isValid() and map_crs != layer_crs:
                    transform = QgsCoordinateTransform(map_crs, layer_crs, QgsProject.instance())
                    layer_point = transform.transform(point_map)
                    tolerance_probe_map = QgsPointXY(float(point_map.x()) + map_tolerance, float(point_map.y()))
                    tolerance_probe_layer = transform.transform(tolerance_probe_map)
                    layer_tolerance = max(
                        abs(float(tolerance_probe_layer.x()) - float(layer_point.x())),
                        abs(float(tolerance_probe_layer.y()) - float(layer_point.y())),
                        1e-9,
                    )
            except Exception:
                continue

            point_geom = QgsGeometry.fromPointXY(layer_point)
            filter_rect = QgsRectangle(
                float(layer_point.x()) - float(layer_tolerance),
                float(layer_point.y()) - float(layer_tolerance),
                float(layer_point.x()) + float(layer_tolerance),
                float(layer_point.y()) + float(layer_tolerance),
            )
            request = QgsFeatureRequest().setFilterRect(filter_rect)

            best_feature = None
            best_area = None
            for feature in layer.getFeatures(request):
                feature_geom = feature.geometry()
                if feature_geom is None or feature_geom.isEmpty():
                    continue
                try:
                    if not (feature_geom.contains(point_geom) or feature_geom.intersects(point_geom)):
                        continue
                except Exception:
                    continue
                try:
                    area_value = abs(float(feature_geom.area()))
                except Exception:
                    area_value = float("inf")
                if best_feature is None or best_area is None or area_value < best_area:
                    best_feature = feature
                    best_area = area_value
            if best_feature is not None:
                return layer, best_feature
        return None, None

    def _apply_asset_intel_polygon_measurement_filters(self, measurement):
        if self.dock is None:
            raise RuntimeError("Asset Intel dock is unavailable.")
        payload = measurement if isinstance(measurement, dict) else {}
        length_m = float(payload.get("length_m") or 0.0)
        width_m = float(payload.get("width_m") or 0.0)
        angle_deg = float(payload.get("angle_deg") or 0.0)
        if not math.isfinite(length_m) or length_m <= 0.0:
            raise RuntimeError("Measured length is invalid.")
        if not math.isfinite(width_m) or width_m <= 0.0:
            raise RuntimeError("Measured width is invalid.")

        pad_m = 5.0
        length_min = max(0.0, length_m - pad_m)
        length_max = max(0.0, length_m + pad_m)
        width_min = max(0.0, width_m - pad_m)
        width_max = max(0.0, width_m + pad_m)

        if hasattr(self.dock, "asset_intel_length_min_input"):
            self.dock.asset_intel_length_min_input.setText(f"{length_min:.2f}")
        if hasattr(self.dock, "asset_intel_length_max_input"):
            self.dock.asset_intel_length_max_input.setText(f"{length_max:.2f}")
        if hasattr(self.dock, "asset_intel_width_min_input"):
            self.dock.asset_intel_width_min_input.setText(f"{width_min:.2f}")
        if hasattr(self.dock, "asset_intel_width_max_input"):
            self.dock.asset_intel_width_max_input.setText(f"{width_max:.2f}")

        self.handle_asset_intel_search_request(self.dock.current_asset_intel_payload())
        return {
            "length_m": round(length_m, 2),
            "width_m": round(width_m, 2),
            "angle_deg": round(angle_deg, 2),
        }

    def _on_asset_intel_polygon_canvas_clicked(self, point, _button=None):
        picked_layer = None
        picked_feature_id = None
        prior_selection_ids = []
        try:
            layer, feature = self._asset_intel_pick_polygon_feature_at_map_point(point)
            if layer is None or feature is None:
                raise RuntimeError("No polygon found at clicked location.")
            picked_layer = layer
            picked_feature_id = int(feature.id())
            try:
                prior_selection_ids = list(layer.selectedFeatureIds() or [])
            except Exception:
                prior_selection_ids = []
            try:
                layer.selectByIds([picked_feature_id])
            except Exception:
                pass

            measurement = self._measure_asset_intel_polygon_dimensions(
                layer=layer,
                geometry=feature.geometry(),
            )
            applied = self._apply_asset_intel_polygon_measurement_filters(measurement)
            self.dock.set_asset_intel_status(
                "Asset Intel: polygon-derived filters applied "
                f"(L={float(applied['length_m']):.2f}m, W={float(applied['width_m']):.2f}m, "
                f"angle={float(applied['angle_deg']):.2f}deg, +/-5m)."
            )
        except Exception as exc:
            if self.dock is not None:
                self.dock.set_asset_intel_status(f"Asset Intel polygon measurement failed: {exc}")
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Asset Intel polygon measurement failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            self._append_debug_log(f"Asset Intel polygon measurement failed: {exc}", level=Qgis.Warning)
        finally:
            if picked_layer is not None and picked_feature_id is not None:
                try:
                    restore_ids = [fid for fid in prior_selection_ids if int(fid) != int(picked_feature_id)]
                    picked_layer.selectByIds(restore_ids)
                except Exception:
                    try:
                        picked_layer.removeSelection()
                    except Exception:
                        pass
            self._stop_asset_intel_polygon_pick_mode(set_pan=True)

    def _stop_asset_intel_polygon_pick_mode(self, *, set_pan):
        canvas = self.iface.mapCanvas() if self.iface is not None else None
        pick_tool = self._asset_intel_polygon_pick_tool
        if pick_tool is not None:
            try:
                pick_tool.canvasClicked.disconnect(self._on_asset_intel_polygon_canvas_clicked)
            except Exception:
                pass
        if canvas is not None and pick_tool is not None and canvas.mapTool() == pick_tool:
            prev_tool = self._asset_intel_polygon_prev_map_tool
            try:
                if set_pan:
                    pan_action = self.iface.actionPan() if self.iface is not None else None
                    if pan_action is not None:
                        pan_action.trigger()
                    elif prev_tool is not None:
                        canvas.setMapTool(prev_tool)
                    else:
                        canvas.unsetMapTool(pick_tool)
                elif prev_tool is not None:
                    canvas.setMapTool(prev_tool)
                else:
                    canvas.unsetMapTool(pick_tool)
            except Exception:
                pass
        self._asset_intel_polygon_pick_tool = None
        self._asset_intel_polygon_prev_map_tool = None
        if self.dock is not None and hasattr(self.dock, "set_asset_intel_target_select_mode"):
            self.dock.set_asset_intel_target_select_mode(False)

    def handle_asset_intel_polygon_size_from_selection_request(self):
        if self.dock is None:
            return
        canvas = self.iface.mapCanvas() if self.iface is not None else None
        if canvas is None:
            self.dock.set_asset_intel_status("Asset Intel polygon measurement failed: map canvas unavailable.")
            return
        if not self._asset_intel_polygon_pick_layers():
            self.dock.set_asset_intel_status(
                "Asset Intel polygon measurement failed: no visible polygon layer found."
            )
            return

        self._stop_asset_intel_polygon_pick_mode(set_pan=False)
        self._stop_simulation_pick_mode()
        self._asset_intel_polygon_prev_map_tool = canvas.mapTool()
        self._asset_intel_polygon_pick_tool = QgsMapToolEmitPoint(canvas)
        self._asset_intel_polygon_pick_tool.canvasClicked.connect(self._on_asset_intel_polygon_canvas_clicked)
        canvas.setMapTool(self._asset_intel_polygon_pick_tool)
        if hasattr(self.dock, "set_asset_intel_target_select_mode"):
            self.dock.set_asset_intel_target_select_mode(True)
        self.dock.set_asset_intel_status("Asset Intel: Select Mode active. Click a polygon on the map.")

    @staticmethod
    def _project_vector_layer_by_id(layer_id):
        layer_key = str(layer_id or "").strip()
        if not layer_key:
            return None
        layer = QgsProject.instance().mapLayer(layer_key)
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return None
        return layer

    @staticmethod
    def _layer_has_fields(layer, field_names):
        if layer is None or not isinstance(field_names, (list, tuple)):
            return False
        try:
            fields = layer.fields()
        except Exception:
            return False
        for name in field_names:
            field_name = str(name or "").strip()
            if not field_name:
                return False
            if fields.indexFromName(field_name) < 0:
                return False
        return True

    @classmethod
    def _is_vessel_detection_layer(cls, layer):
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return False
        marker = str(layer.customProperty("image_mate/vessel_detection_layer") or "").strip()
        if marker == "1":
            return True
        required = [
            "run_id",
            "scene_id",
            "source_layer_id",
            "detection_id",
            "confidence",
            "length_m",
            "width_m",
            "model_version",
        ]
        return cls._layer_has_fields(layer, required)

    @classmethod
    def _is_vessel_qa_layer(cls, layer):
        if layer is None or not isinstance(layer, QgsVectorLayer):
            return False
        marker = str(layer.customProperty("image_mate/vessel_qa_layer") or "").strip()
        if marker == "1":
            return True
        required = [
            "run_id",
            "scene_id",
            "source_layer_id",
            "detection_id",
            "qa_status",
            "label_source",
            "confidence",
            "length_m",
            "width_m",
            "timestamp_utc",
            "model_version",
        ]
        return cls._layer_has_fields(layer, required)

    def _new_vessel_qa_layer(self, *, crs_token, layer_name_hint):
        safe_hint = self.campaign_storage.sanitize_component(str(layer_name_hint or "qa"), fallback="qa")
        layer_name = f"Image Mate Vessel QA {safe_hint}"
        layer = QgsVectorLayer(f"Polygon?crs={crs_token}", layer_name, "memory")
        if not layer.isValid():
            raise RuntimeError("Failed to create vessel QA output layer.")
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("run_id", QVariant.String),
                QgsField("scene_id", QVariant.String),
                QgsField("source_layer_id", QVariant.String),
                QgsField("detection_id", QVariant.String),
                QgsField("qa_status", QVariant.String),
                QgsField("label_source", QVariant.String),
                QgsField("confidence", QVariant.Double),
                QgsField("length_m", QVariant.Double),
                QgsField("width_m", QVariant.Double),
                QgsField("timestamp_utc", QVariant.String),
                QgsField("model_version", QVariant.String),
            ]
        )
        layer.updateFields()
        layer.setCustomProperty("image_mate/vessel_qa_layer", "1")
        return layer

    def _build_vessel_qa_layer_from_detection_rows(self, *, source_layer, detections, layer_name_hint):
        src = source_layer if source_layer is not None else None
        src_crs = src.crs() if src is not None else None
        crs_token = src_crs.authid() if src_crs is not None and src_crs.isValid() else "EPSG:4326"
        layer = self._new_vessel_qa_layer(crs_token=crs_token, layer_name_hint=layer_name_hint)
        provider = layer.dataProvider()

        default_ts = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
        features = []
        run_id_marker = ""
        model_version_marker = ""
        for idx, row in enumerate(detections or [], start=1):
            map_obb = row.get("obb_map")
            if not isinstance(map_obb, list) or len(map_obb) < 4:
                continue
            ring = []
            for pair in map_obb[:4]:
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                try:
                    ring.append(QgsPointXY(float(pair[0]), float(pair[1])))
                except Exception:
                    continue
            if len(ring) < 4:
                continue
            ring.append(QgsPointXY(ring[0].x(), ring[0].y()))
            geom = QgsGeometry.fromPolygonXY([ring])
            if geom is None or geom.isEmpty():
                continue

            feature = QgsFeature(layer.fields())
            feature.setGeometry(geom)
            run_id = str(row.get("run_id") or "").strip()
            detection_id = str(row.get("detection_id") or "").strip() or f"det_{idx:03d}"
            model_version = str(row.get("model_version") or "").strip()
            timestamp_utc = str(row.get("timestamp_utc") or "").strip() or default_ts
            feature["run_id"] = run_id
            feature["scene_id"] = str(row.get("scene_id") or "").strip()
            feature["source_layer_id"] = str(row.get("source_layer_id") or "").strip()
            feature["detection_id"] = detection_id
            feature["qa_status"] = "pending"
            feature["label_source"] = "model"
            feature["confidence"] = float(row.get("confidence") or 0.0)
            feature["length_m"] = float(row.get("length_m") or 0.0)
            feature["width_m"] = float(row.get("width_m") or 0.0)
            feature["timestamp_utc"] = timestamp_utc
            feature["model_version"] = model_version
            features.append(feature)

            if not run_id_marker and run_id:
                run_id_marker = run_id
            if not model_version_marker and model_version:
                model_version_marker = model_version

        if features:
            provider.addFeatures(features)
            layer.updateExtents()
        layer.setCustomProperty("image_mate/vessel_run_id", run_id_marker)
        layer.setCustomProperty("image_mate/vessel_model_version", model_version_marker)
        return layer

    def _build_vessel_qa_layer_from_detection_layer(self, *, detection_layer, layer_name_hint):
        if detection_layer is None or not isinstance(detection_layer, QgsVectorLayer):
            raise RuntimeError("Detection layer is invalid.")
        crs = detection_layer.crs()
        crs_token = crs.authid() if crs is not None and crs.isValid() else "EPSG:4326"
        layer = self._new_vessel_qa_layer(crs_token=crs_token, layer_name_hint=layer_name_hint)
        provider = layer.dataProvider()
        default_ts = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
        source_fields = detection_layer.fields()
        features = []
        run_id_marker = str(detection_layer.customProperty("image_mate/vessel_run_id") or "").strip()
        model_version_marker = str(detection_layer.customProperty("image_mate/vessel_model_version") or "").strip()

        def _fstr(src_feature, field_name, default_value=""):
            if source_fields.indexFromName(field_name) < 0:
                return str(default_value or "").strip()
            value = src_feature[field_name]
            if value is None:
                return str(default_value or "").strip()
            text = str(value).strip()
            if text.lower() == "none":
                return str(default_value or "").strip()
            return text

        def _ffloat(src_feature, field_name, default_value=0.0):
            if source_fields.indexFromName(field_name) < 0:
                return float(default_value)
            value = src_feature[field_name]
            try:
                return float(value)
            except Exception:
                return float(default_value)

        for idx, src_feature in enumerate(detection_layer.getFeatures(), start=1):
            geom = src_feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry(geom))

            run_id = _fstr(src_feature, "run_id", run_id_marker)
            scene_id = _fstr(src_feature, "scene_id", "")
            source_layer_id = _fstr(src_feature, "source_layer_id", "")
            detection_id = _fstr(src_feature, "detection_id", "") or f"det_{idx:03d}"
            confidence = _ffloat(src_feature, "confidence", 0.0)
            length_m = _ffloat(src_feature, "length_m", 0.0)
            width_m = _ffloat(src_feature, "width_m", 0.0)
            timestamp_utc = _fstr(src_feature, "timestamp_utc", default_ts) or default_ts
            model_version = _fstr(src_feature, "model_version", model_version_marker)

            feature["run_id"] = run_id
            feature["scene_id"] = scene_id
            feature["source_layer_id"] = source_layer_id
            feature["detection_id"] = detection_id
            feature["qa_status"] = "pending"
            feature["label_source"] = "model"
            feature["confidence"] = confidence
            feature["length_m"] = length_m
            feature["width_m"] = width_m
            feature["timestamp_utc"] = timestamp_utc
            feature["model_version"] = model_version
            features.append(feature)

            if not run_id_marker and run_id:
                run_id_marker = run_id
            if not model_version_marker and model_version:
                model_version_marker = model_version

        if features:
            provider.addFeatures(features)
            layer.updateExtents()
        layer.setCustomProperty("image_mate/vessel_run_id", run_id_marker)
        layer.setCustomProperty("image_mate/vessel_model_version", model_version_marker)
        return layer

    def handle_vessel_create_qa_layer_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        layer_id = str(request.get("detection_layer_id") or "").strip()
        layer_name_hint = str(request.get("output_name_hint") or "").strip()

        try:
            layer = self._project_vector_layer_by_id(layer_id)
            if layer is None:
                active = self.iface.activeLayer() if self.iface is not None else None
                if isinstance(active, QgsVectorLayer):
                    layer = active
            if layer is None:
                raise RuntimeError("Choose a vessel detection layer first.")
            if not self._is_vessel_detection_layer(layer):
                raise RuntimeError(
                    "Selected layer is not a vessel detection layer (missing expected vessel detection fields)."
                )
            hint = layer_name_hint or layer.name()
            qa_layer = self._build_vessel_qa_layer_from_detection_layer(
                detection_layer=layer,
                layer_name_hint=hint,
            )
            self._add_layer_to_image_mate_group(qa_layer, insert_on_top=True)
            try:
                if self.iface is not None:
                    self.iface.setActiveLayer(qa_layer)
            except Exception:
                pass
            try:
                qa_layer.startEditing()
            except Exception:
                pass
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Vessel QA layer created: {qa_layer.name()} ({qa_layer.featureCount()} feature(s)).",
                level=Qgis.Success,
                duration=8,
            )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Create vessel QA layer failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            self._append_debug_log(f"Create vessel QA layer failed: {exc}", level=Qgis.Warning)

    def _resolve_vessel_qa_layer(self, layer_id):
        layer_key = str(layer_id or "").strip()
        layer = self._project_vector_layer_by_id(layer_key)
        if layer is None:
            active = self.iface.activeLayer() if self.iface is not None else None
            if isinstance(active, QgsVectorLayer):
                layer = active
        if layer is None:
            raise RuntimeError("No QA layer selected. Choose or activate a vessel QA layer.")
        if not self._is_vessel_qa_layer(layer):
            raise RuntimeError("Active layer is not a vessel QA layer.")
        return layer

    def handle_vessel_set_qa_status_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        requested_status = str(request.get("qa_status") or "").strip().lower()
        if requested_status not in {"pending", "approved", "rejected"}:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Vessel QA status update failed: invalid qa_status.",
                level=Qgis.Warning,
                duration=8,
            )
            return

        try:
            qa_layer = self._resolve_vessel_qa_layer(str(request.get("qa_layer_id") or "").strip())
            selected_ids = list(qa_layer.selectedFeatureIds() or [])
            if not selected_ids:
                raise RuntimeError("Select one or more QA features in the active QA layer.")
            fields = qa_layer.fields()
            status_idx = fields.indexFromName("qa_status")
            ts_idx = fields.indexFromName("timestamp_utc")
            source_idx = fields.indexFromName("label_source")
            detection_idx = fields.indexFromName("detection_id")
            if status_idx < 0:
                raise RuntimeError("QA layer is missing qa_status field.")

            now_utc = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
            updates = {}
            for fid in selected_ids:
                per_feature = {status_idx: requested_status}
                if ts_idx >= 0:
                    per_feature[ts_idx] = now_utc
                if source_idx >= 0:
                    src_feature = qa_layer.getFeature(int(fid))
                    current_source = (
                        str(src_feature["label_source"]).strip().lower()
                        if src_feature is not None and source_idx >= 0
                        else ""
                    )
                    if not current_source:
                        detection_id = (
                            str(src_feature["detection_id"]).strip()
                            if src_feature is not None and detection_idx >= 0
                            else ""
                        )
                        per_feature[source_idx] = "model" if detection_id else "manual"
                updates[int(fid)] = per_feature

            if not qa_layer.dataProvider().changeAttributeValues(updates):
                raise RuntimeError("Provider rejected QA status updates.")
            qa_layer.triggerRepaint()
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Vessel QA status updated to '{requested_status}' for {len(selected_ids)} feature(s).",
                level=Qgis.Success,
                duration=7,
            )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Vessel QA status update failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            self._append_debug_log(f"Vessel QA status update failed: {exc}", level=Qgis.Warning)

    @staticmethod
    def _feature_geometry_geojson(feature):
        if feature is None:
            return {}
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            return {}
        try:
            return json.loads(geom.asJson())
        except Exception:
            return {}

    @staticmethod
    def _feature_attribute_dict(feature, field_names):
        attrs = {}
        if feature is None:
            return attrs
        for name in field_names or []:
            key = str(name or "").strip()
            if not key:
                continue
            value = feature[key]
            if isinstance(value, (int, float)) or value is None:
                attrs[key] = value
            else:
                attrs[key] = str(value)
        return attrs

    @staticmethod
    def _qa_status_or_pending(value):
        normalized = str(value or "").strip().lower()
        if normalized in {"pending", "approved", "rejected"}:
            return normalized
        return "pending"

    @staticmethod
    def _feature_polygon_ring_coords(feature):
        if feature is None:
            return []
        geom = feature.geometry()
        if geom is None or geom.isEmpty():
            return []
        try:
            polygon = geom.asPolygon()
            if polygon and len(polygon) > 0:
                ring = polygon[0]
            else:
                multi = geom.asMultiPolygon()
                ring = multi[0][0] if multi and multi[0] else []
            points = []
            for point in ring or []:
                points.append([float(point.x()), float(point.y())])
            if len(points) > 1 and points[0] == points[-1]:
                points = points[:-1]
            if len(points) >= 4:
                return points[:4]
            return points
        except Exception:
            return []

    @staticmethod
    def _write_geojson_feature_collection(path_obj, features):
        payload = {
            "type": "FeatureCollection",
            "features": features if isinstance(features, list) else [],
        }
        Path(path_obj).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def handle_vessel_finalize_qa_batch_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        try:
            qa_layer = self._resolve_vessel_qa_layer(str(request.get("qa_layer_id") or "").strip())
            fields = qa_layer.fields()
            field_names = [str(row.name() or "").strip() for row in fields]
            required = [
                "run_id",
                "scene_id",
                "source_layer_id",
                "detection_id",
                "qa_status",
                "label_source",
                "confidence",
                "length_m",
                "width_m",
                "timestamp_utc",
                "model_version",
            ]
            if not self._layer_has_fields(qa_layer, required):
                raise RuntimeError("QA layer is missing one or more required fields.")

            all_features_geojson = []
            approved_features_geojson = []
            approved_records = []
            counts = {"pending": 0, "approved": 0, "rejected": 0}
            source_layer_ids = set()
            scene_ids = set()
            run_ids = set()
            model_versions = set()

            for feature in qa_layer.getFeatures():
                attrs = self._feature_attribute_dict(feature, field_names)
                qa_status = self._qa_status_or_pending(attrs.get("qa_status"))
                attrs["qa_status"] = qa_status
                label_source = str(attrs.get("label_source") or "").strip().lower()
                if label_source not in {"model", "manual"}:
                    detection_id = str(attrs.get("detection_id") or "").strip()
                    attrs["label_source"] = "model" if detection_id else "manual"
                counts[qa_status] = int(counts.get(qa_status, 0) or 0) + 1

                source_layer_id = str(attrs.get("source_layer_id") or "").strip()
                if source_layer_id:
                    source_layer_ids.add(source_layer_id)
                scene_id = str(attrs.get("scene_id") or "").strip()
                if scene_id:
                    scene_ids.add(scene_id)
                run_id = str(attrs.get("run_id") or "").strip()
                if run_id:
                    run_ids.add(run_id)
                model_version = str(attrs.get("model_version") or "").strip()
                if model_version:
                    model_versions.add(model_version)

                geometry_json = self._feature_geometry_geojson(feature)
                geojson_feature = {
                    "type": "Feature",
                    "geometry": geometry_json,
                    "properties": attrs,
                }
                all_features_geojson.append(geojson_feature)

                if qa_status == "approved":
                    approved_features_geojson.append(geojson_feature)
                    approved_records.append(
                        {
                            "properties": attrs,
                            "geometry": geometry_json,
                            "obb_map": self._feature_polygon_ring_coords(feature),
                        }
                    )

            approved_count = len(approved_features_geojson)
            if approved_count <= 0:
                raise RuntimeError(
                    "Finalize QA batch aborted: no approved labels found. "
                    "Mark at least one feature as approved first."
                )

            batch_id_raw = str(request.get("batch_id") or "").strip()
            if not batch_id_raw:
                batch_id_raw = datetime.now(tz=timezone.utc).strftime("qa_batch_%Y%m%dT%H%M%SZ")
            batch_id = self.campaign_storage.sanitize_component(batch_id_raw, fallback="qa_batch")
            dataset_id = str(request.get("dataset_id") or "").strip()
            chip_size = int(request.get("chip_size", 1024) or 1024)
            padding = int(request.get("padding", 128) or 128)
            split_payload = request.get("split") if isinstance(request.get("split"), dict) else {}
            split = {
                "train": int(split_payload.get("train", 70) or 70),
                "val": int(split_payload.get("val", 15) or 15),
                "test": int(split_payload.get("test", 15) or 15),
            }

            if self._campaign_storage_enabled() and self.current_campaign_uid:
                self.campaign_storage.ensure_campaign_tree(
                    self.current_campaign_uid,
                    campaign_name=str(self.provider_settings.campaign_name or "").strip(),
                )
                export_dir = self.campaign_storage.campaign_vessel_qa_export_dir(
                    self.current_campaign_uid,
                    batch_id,
                )
            else:
                export_dir = self.temp_dir / "ml" / "vessel" / "qa_exports" / batch_id
                export_dir.mkdir(parents=True, exist_ok=True)

            qa_snapshot_path = export_dir / "qa_snapshot.geojson"
            approved_snapshot_path = export_dir / "approved_snapshot.geojson"
            approved_records_path = export_dir / "approved_records.jsonl"
            manifest_path = export_dir / "qa_batch_manifest.json"

            self._write_geojson_feature_collection(qa_snapshot_path, all_features_geojson)
            self._write_geojson_feature_collection(approved_snapshot_path, approved_features_geojson)
            with approved_records_path.open("w", encoding="utf-8") as handle:
                for row in approved_records:
                    handle.write(json.dumps(row))
                    handle.write("\n")

            created_utc = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
            manifest = {
                "schema_version": 1,
                "batch_id": batch_id,
                "dataset_id": dataset_id,
                "created_utc": created_utc,
                "qa_layer_id": str(qa_layer.id() or ""),
                "qa_layer_name": str(qa_layer.name() or ""),
                "counts": {
                    "total": len(all_features_geojson),
                    "approved": approved_count,
                    "rejected": int(counts.get("rejected", 0) or 0),
                    "pending": int(counts.get("pending", 0) or 0),
                },
                "defaults": {
                    "chip_size": chip_size,
                    "padding": padding,
                    "split": split,
                },
                "scene_ids": sorted(scene_ids),
                "source_layer_ids": sorted(source_layer_ids),
                "run_ids": sorted(run_ids),
                "model_versions": sorted(model_versions),
                "files": {
                    "qa_snapshot_geojson": qa_snapshot_path.name,
                    "approved_snapshot_geojson": approved_snapshot_path.name,
                    "approved_records_jsonl": approved_records_path.name,
                },
            }
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            self._last_vessel_qa_batch_dir = str(Path(export_dir).resolve())

            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Vessel QA batch finalized: {batch_id} ({approved_count} approved) at {export_dir}",
                level=Qgis.Success,
                duration=12,
            )
            self._append_debug_log(
                f"Vessel QA batch finalized: batch_id={batch_id} approved={approved_count} path={export_dir}"
            )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Finalize vessel QA batch failed: {exc}",
                level=Qgis.Warning,
                duration=12,
            )
            self._append_debug_log(f"Finalize vessel QA batch failed: {exc}", level=Qgis.Warning)

    def handle_vessel_open_qa_batch_folder_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        try:
            batch_id = str(request.get("batch_id") or "").strip()
            preferred_batch_dir = str(request.get("batch_dir") or self._last_vessel_qa_batch_dir).strip()
            batch_context = self.vessel_training_service.resolve_batch_context(
                campaign_storage_enabled=self._campaign_storage_enabled(),
                campaign_storage=self.campaign_storage,
                current_campaign_uid=self.current_campaign_uid,
                temp_dir=self.temp_dir,
                batch_id=batch_id,
                preferred_batch_dir=preferred_batch_dir,
            )
            self._last_vessel_qa_batch_dir = str(batch_context.batch_dir)
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(batch_context.batch_dir)))
            if not opened:
                raise RuntimeError(f"Failed to open folder: {batch_context.batch_dir}")
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Opened vessel QA batch folder: {batch_context.batch_dir}",
                level=Qgis.Success,
                duration=10,
            )
            self._append_debug_log(
                f"Vessel QA batch folder opened: batch_id={batch_context.batch_id} path={batch_context.batch_dir}"
            )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Open vessel QA batch folder failed: {exc}",
                level=Qgis.Warning,
                duration=12,
            )
            self._append_debug_log(f"Open vessel QA batch folder failed: {exc}", level=Qgis.Warning)

    def handle_vessel_model_update_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        try:
            result = self.vessel_training_service.initialize_model_update_from_batch(
                campaign_storage_enabled=self._campaign_storage_enabled(),
                campaign_storage=self.campaign_storage,
                current_campaign_uid=self.current_campaign_uid,
                temp_dir=self.temp_dir,
                request=request,
                preferred_batch_dir=self._last_vessel_qa_batch_dir,
            )
            self._last_vessel_qa_batch_dir = str(result.get("batch_dir") or self._last_vessel_qa_batch_dir).strip()

            train_manifest_path = str(result.get("train_run_manifest_path") or "").strip()
            self.iface.messageBar().pushMessage(
                "Image Mate",
                (
                    "Vessel model update scaffold initialized: "
                    f"dataset={result.get('dataset_id')} run={Path(train_manifest_path).parent.name if train_manifest_path else '(unknown)'}"
                ),
                level=Qgis.Success,
                duration=12,
            )
            self._append_debug_log(
                "Vessel model update scaffold initialized: "
                f"batch_id={result.get('batch_id')} dataset_id={result.get('dataset_id')} "
                f"dataset_dir={result.get('dataset_dir')} train_manifest={train_manifest_path}"
            )

            if bool(request.get("open_batch_folder")):
                batch_dir = str(result.get("batch_dir") or "").strip()
                if batch_dir:
                    opened = QDesktopServices.openUrl(QUrl.fromLocalFile(batch_dir))
                    if not opened:
                        self._append_debug_log(
                            f"Model update scaffold: failed to open batch folder {batch_dir}",
                            level=Qgis.Warning,
                        )
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Vessel model update failed: {exc}",
                level=Qgis.Warning,
                duration=12,
            )
            self._append_debug_log(f"Vessel model update failed: {exc}", level=Qgis.Warning)

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
        source_candidates = []
        source = str(layer.source() or "").strip()
        if source:
            source_candidates.append(source)
        try:
            public_source = str(layer.publicSource() or "").strip()
        except Exception:
            public_source = ""
        if public_source and public_source not in source_candidates:
            source_candidates.append(public_source)
        try:
            provider = layer.dataProvider()
            provider_uri = str(provider.dataSourceUri() or "").strip() if provider is not None else ""
        except Exception:
            provider_uri = ""
        if provider_uri and provider_uri not in source_candidates:
            source_candidates.append(provider_uri)

        project_dirs = []
        try:
            project = QgsProject.instance()
            absolute_path = str(project.absolutePath() or "").strip()
            if absolute_path:
                project_dirs.append(absolute_path)
            home_path = str(project.homePath() or "").strip()
            if home_path and home_path not in project_dirs:
                project_dirs.append(home_path)
        except Exception:
            project_dirs = []

        return resolve_local_raster_path(
            source_candidates=source_candidates,
            project_dirs=project_dirs,
        )

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
            items = list(self._search_with_satellogic_detail_parity(request_payload) or [])
            source_id = str(request_payload.get("source_id") or "").strip().lower()
            coverage_mode = str(request_payload.get("min_coverage_filter") or "").strip().lower()
            if coverage_mode not in {"touching", "full", "half"}:
                coverage_mode = "full" if bool(request_payload.get("require_full_aoi_overlap", False)) else "half"
            min_overlap_ratio = 1.0 if coverage_mode == "full" else (0.5 if coverage_mode == "half" else None)
            if min_overlap_ratio is not None:
                original_items = list(items)
                original_count = len(original_items)
                filtered_items, dropped_count, invalid_geometry_count = self._filter_items_min_aoi_overlap(
                    items=items,
                    aoi_geometry=geometry,
                    min_overlap_ratio=float(min_overlap_ratio),
                )
                if (
                    source_id == "merlin-s2"
                    and coverage_mode == "full"
                    and original_count > 0
                    and len(filtered_items) == 0
                ):
                    items = original_items
                    self._append_search_log(
                        "Coverage filter ON (Full Coverage): produced 0 Sentinel-2 results; "
                        "auto-fallback applied to keep overlap matches."
                    )
                else:
                    items = filtered_items
                    self._append_search_log(
                        f"Coverage filter ON ({coverage_mode.title()} Coverage): "
                        f"kept {len(items)}/{original_count} item(s)."
                    )
                    if dropped_count > 0:
                        self._append_search_log(f"Coverage filter removed {dropped_count} item(s) below threshold.")
                    if invalid_geometry_count > 0:
                        self._append_search_log(
                            f"Coverage filter skipped {invalid_geometry_count} item(s) with invalid geometry.",
                            level=Qgis.Warning,
                        )
            else:
                self._append_search_log("Coverage filter OFF: overlap results are allowed.")
            self.search_items = {str(item.get("id") or ""): item for item in items or []}
            self._auto_stream_pinned_item_id = ""
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
                "ISR Mission Workbench",
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
            
            self.iface.messageBar().pushMessage(
                "ISR Mission Workbench",
                f"Search failed: {exc}",
                level=Qgis.Critical,
                duration=10,
            )
        finally:
            if self.dock is not None:
                self.dock.set_search_enabled(True)

    def _filter_items_full_aoi_overlap(self, *, items, aoi_geometry):
        return self._filter_items_min_aoi_overlap(
            items=items,
            aoi_geometry=aoi_geometry,
            min_overlap_ratio=1.0,
        )

    def _filter_items_min_aoi_overlap(self, *, items, aoi_geometry, min_overlap_ratio):
        rows = [row for row in (items or []) if isinstance(row, dict)]
        aoi_geom = self._geometry_from_geojson(aoi_geometry if isinstance(aoi_geometry, dict) else None)
        if aoi_geom is None or aoi_geom.isEmpty():
            self._append_search_log(
                "Coverage filter skipped: AOI geometry is invalid or unavailable.",
                level=Qgis.Warning,
            )
            return rows, 0, 0

        try:
            aoi_bbox = aoi_geom.boundingBox()
        except Exception:
            aoi_bbox = None
        try:
            aoi_area = abs(float(aoi_geom.area()))
        except Exception:
            aoi_area = 0.0
        if aoi_area <= 0.0:
            self._append_search_log(
                "Coverage filter skipped: AOI area is zero.",
                level=Qgis.Warning,
            )
            return rows, 0, 0

        threshold = max(0.0, min(1.0, float(min_overlap_ratio or 0.0)))

        kept = []
        invalid_geometry_count = 0
        for row in rows:
            geom_payload = row.get("geometry")
            if not isinstance(geom_payload, dict):
                invalid_geometry_count += 1
                continue
            candidate_geom = self._geometry_from_geojson(geom_payload)
            if candidate_geom is None or candidate_geom.isEmpty():
                invalid_geometry_count += 1
                continue
            if aoi_bbox is not None:
                try:
                    candidate_bbox = candidate_geom.boundingBox()
                    if threshold >= 0.999999:
                        if candidate_bbox is not None and not candidate_bbox.contains(aoi_bbox):
                            continue
                    elif candidate_bbox is not None and not candidate_bbox.intersects(aoi_bbox):
                        continue
                except Exception:
                    pass

            overlap_ratio = 0.0
            if threshold >= 0.999999:
                contains = False
                try:
                    contains = candidate_geom.contains(aoi_geom)
                except Exception:
                    contains = False
                if not contains:
                    try:
                        uncovered = aoi_geom.difference(candidate_geom)
                        contains = uncovered is not None and uncovered.isEmpty()
                    except Exception:
                        contains = False
                overlap_ratio = 1.0 if contains else 0.0
            else:
                try:
                    overlap_geom = candidate_geom.intersection(aoi_geom)
                    overlap_area = abs(float(overlap_geom.area())) if overlap_geom is not None else 0.0
                    overlap_ratio = overlap_area / aoi_area if aoi_area > 0.0 else 0.0
                except Exception:
                    overlap_ratio = 0.0

            if overlap_ratio + 1e-9 >= threshold:
                kept.append(row)

        dropped_count = max(0, len(rows) - len(kept))
        return kept, dropped_count, invalid_geometry_count

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
        if source_id == "satellogic":
            self._auto_stream_pinned_item_id = item_key
        else:
            self._auto_stream_pinned_item_id = ""
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
                        "NewSat Constellation stream candidates resolved: "
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

    def handle_download_selected_request(self, payload):
        request = payload if isinstance(payload, dict) else {}

        groups = self._resolve_download_selected_groups(request)
        if not groups:
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "No valid search selection to download. Select one or more search results first.",
                level=Qgis.Warning,
                duration=8,
            )
            if self.dock is not None and hasattr(self.dock, "_refresh_download_selected_button_state"):
                self.dock._refresh_download_selected_button_state()
            return

        total_items = sum(len(group.get("items") or []) for group in groups)
        request_id = datetime.now(tz=timezone.utc).strftime("download_%Y%m%dT%H%M%S%fZ")
        self._append_search_log(
            f"Starting background GeoTIFF download request={request_id} for {len(groups)} capture group(s), {total_items} item(s)."
        )
        self.iface.messageBar().pushMessage(
            "Image Mate",
            f"Background download started: {len(groups)} task(s), {total_items} item(s).",
            level=Qgis.Info,
            duration=6,
        )
        started_tasks = 0
        for idx, group in enumerate(groups, start=1):
            started_utc = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
            task_id = f"{request_id}_{idx:03d}"
            group_items = [dict(row) for row in (group.get("items") or []) if isinstance(row, dict)]
            items_total = int(len(group_items))
            group_label = str(group.get("outcome_id") or "").strip()
            if not group_label:
                item_ids = group.get("item_ids") if isinstance(group.get("item_ids"), list) else []
                group_label = str(item_ids[0] if item_ids else f"group_{idx}").strip() or f"group_{idx}"

            task_name = f"Image Mate Download {group_label} ({items_total} item(s))"

            def _on_finished(exception, result=None, _task_id=task_id):
                self._on_download_selected_task_finished(_task_id, exception, result)

            task = QgsTask.fromFunction(
                task_name,
                self._run_download_selected_task,
                on_finished=_on_finished,
                groups=[group],
            )
            self._download_selected_tasks[task_id] = {
                "task": task,
                "groups_total": 1,
                "items_total": items_total,
                "downloaded_files": 0,
                "started_utc": started_utc,
                "updated_utc": started_utc,
                "status": "queued",
                "note": f"Queued ({group_label})",
            }
            if self.dock is not None:
                self.dock.upsert_download_task_status(
                    task_id,
                    {
                        "status": "queued",
                        "progress_pct": 0.0,
                        "groups_total": 1,
                        "items_total": items_total,
                        "downloaded_files": 0,
                        "started_utc": started_utc,
                        "updated_utc": started_utc,
                        "note": f"Queued ({group_label})",
                    },
                )
            QgsApplication.taskManager().addTask(task)
            started_tasks += 1

        if self.dock is not None and started_tasks > 0:
            self.dock.set_download_monitor_progress(0.0, f"Download monitor: {started_tasks} task(s) queued")
        if started_tasks > 0 and not self._download_selected_monitor_timer.isActive():
            self._download_selected_monitor_timer.start()

    @staticmethod
    def _download_task_status_text(status_code):
        try:
            code = int(status_code)
        except Exception:
            return "unknown"
        mapping = {
            0: "queued",
            1: "on_hold",
            2: "running",
            3: "complete",
            4: "terminated",
        }
        return mapping.get(code, "unknown")

    def _poll_download_selected_tasks(self):
        if not self._download_selected_tasks:
            if self._download_selected_monitor_timer.isActive():
                self._download_selected_monitor_timer.stop()
            if self.dock is not None:
                self.dock.set_download_monitor_progress(0.0, "Download monitor: idle")
            return

        active_progress_values = []
        active_count = 0
        for task_id, meta in list(self._download_selected_tasks.items()):
            task = meta.get("task")
            if task is None:
                continue
            try:
                progress = float(task.progress())
            except Exception:
                progress = 0.0
            progress = max(0.0, min(100.0, progress))
            try:
                status_code = int(task.status())
            except Exception:
                status_code = -1
            status_text = self._download_task_status_text(status_code)
            now_utc = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
            meta["status"] = status_text
            meta["updated_utc"] = now_utc
            note = "Running"
            if status_text == "queued":
                note = "Queued"
            elif status_text == "on_hold":
                note = "On hold"
            elif status_text == "terminated":
                note = "Terminated"
            meta["note"] = note
            if status_text in {"queued", "running", "on_hold", "unknown"}:
                active_count += 1
                active_progress_values.append(progress)
            if self.dock is not None:
                self.dock.upsert_download_task_status(
                    task_id,
                    {
                        "status": status_text,
                        "progress_pct": progress,
                        "groups_total": int(meta.get("groups_total") or 0),
                        "items_total": int(meta.get("items_total") or 0),
                        "downloaded_files": int(meta.get("downloaded_files") or 0),
                        "started_utc": str(meta.get("started_utc") or ""),
                        "updated_utc": now_utc,
                        "note": note,
                    },
                )

        if self.dock is not None:
            if active_count > 0:
                avg_progress = (
                    float(sum(active_progress_values)) / float(len(active_progress_values))
                    if active_progress_values
                    else 0.0
                )
                self.dock.set_download_monitor_progress(
                    avg_progress,
                    f"Download monitor: {active_count} active task(s), {avg_progress:.1f}% avg",
                )
            else:
                self.dock.set_download_monitor_progress(0.0, "Download monitor: idle")

    def _sync_download_monitor_to_dock(self):
        if self.dock is None:
            return
        if not self._download_selected_tasks:
            self.dock.set_download_monitor_progress(0.0, "Download monitor: idle")
            return
        active_progress_values = []
        active_count = 0
        for task_id, meta in self._download_selected_tasks.items():
            task = meta.get("task")
            try:
                progress = float(task.progress()) if task is not None else 0.0
            except Exception:
                progress = 0.0
            progress = max(0.0, min(100.0, progress))
            try:
                status_text = self._download_task_status_text(int(task.status())) if task is not None else "queued"
            except Exception:
                status_text = "queued"
            if status_text in {"queued", "running", "on_hold", "unknown"}:
                active_count += 1
                active_progress_values.append(progress)
            self.dock.upsert_download_task_status(
                task_id,
                {
                    "status": status_text,
                    "progress_pct": progress,
                    "groups_total": int(meta.get("groups_total") or 0),
                    "items_total": int(meta.get("items_total") or 0),
                    "downloaded_files": int(meta.get("downloaded_files") or 0),
                    "started_utc": str(meta.get("started_utc") or ""),
                    "updated_utc": str(meta.get("updated_utc") or ""),
                    "note": str(meta.get("note") or "Running"),
                },
            )
        if active_count > 0:
            avg_progress = (
                float(sum(active_progress_values)) / float(len(active_progress_values))
                if active_progress_values
                else 0.0
            )
            self.dock.set_download_monitor_progress(
                avg_progress,
                f"Download monitor: {active_count} active task(s), {avg_progress:.1f}% avg",
            )
        else:
            self.dock.set_download_monitor_progress(0.0, "Download monitor: idle")

    def _resolve_download_selected_groups(self, payload):
        request = payload if isinstance(payload, dict) else {}
        raw_groups = request.get("groups") if isinstance(request.get("groups"), list) else []
        if not raw_groups:
            return []

        grouped = {}
        ordered_keys = []
        for raw in raw_groups:
            row = raw if isinstance(raw, dict) else {}
            item_id = str(row.get("item_id") or "").strip()
            outcome_id = str(row.get("outcome_id") or "").strip()
            raw_ids = row.get("group_item_ids") if isinstance(row.get("group_item_ids"), list) else []
            item_ids = []
            for value in raw_ids:
                key = str(value or "").strip()
                if key and key not in item_ids:
                    item_ids.append(key)
            if item_id and item_id not in item_ids:
                item_ids.insert(0, item_id)
            if not item_ids:
                continue

            group_key = outcome_id or f"item:{item_id or item_ids[0]}"
            if group_key not in grouped:
                grouped[group_key] = {
                    "group_key": group_key,
                    "outcome_id": outcome_id,
                    "item_ids": [],
                    "items": [],
                }
                ordered_keys.append(group_key)
            group_row = grouped[group_key]
            if not group_row.get("outcome_id") and outcome_id:
                group_row["outcome_id"] = outcome_id
            for key in item_ids:
                if key in group_row["item_ids"]:
                    continue
                item = self.search_items.get(key)
                if isinstance(item, dict):
                    group_row["item_ids"].append(key)
                    group_row["items"].append(item)

        out = []
        for key in ordered_keys:
            row = grouped.get(key) or {}
            if row.get("items"):
                out.append(row)
        return out

    @staticmethod
    def _format_download_layer_timestamp(value):
        text = str(value or "").strip()
        if not text:
            return ""
        candidate = text
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.strftime("%Y-%m-%dT%H:%M:%S")
        except Exception:
            pass
        match = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", text)
        if match:
            return f"{match.group(1)}T{match.group(2)}"
        return ""

    def _download_group_display_timestamp(self, group_items):
        rows = [row for row in (group_items or []) if isinstance(row, dict)]
        for row in rows:
            stamp = self._format_download_layer_timestamp(row.get("datetime"))
            if stamp:
                return stamp
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def _download_group_layer_name(*, group, fallback_hint):
        row = group if isinstance(group, dict) else {}
        stamp = str(row.get("display_timestamp") or "").strip()
        outcome_id = str(row.get("outcome_id") or "").strip() or str(fallback_hint or "").strip()
        if stamp and outcome_id:
            return f"{stamp} {outcome_id}"
        return outcome_id or stamp or "downloaded_imagery"

    @staticmethod
    def _normalized_band_token(value):
        token = str(value or "").strip().lower()
        if token in {"r", "red"}:
            return "red"
        if token in {"g", "green"}:
            return "green"
        if token in {"b", "blue"}:
            return "blue"
        if token in {"nir", "nearinfrared", "near_infrared"}:
            return "nir"
        return ""

    @classmethod
    def _band_tokens_from_band_order_text(cls, text):
        raw = str(text or "").strip().lower()
        if not raw:
            return []
        normalized = re.sub(r"[^a-z0-9]+", " ", raw).strip()
        if not normalized:
            return []
        tokens = []
        for token in normalized.split():
            if token == "rgb":
                tokens.extend(["red", "green", "blue"])
                continue
            normalized_token = cls._normalized_band_token(token)
            if normalized_token:
                tokens.append(normalized_token)
        return tokens

    @classmethod
    def _rgb_band_map_from_band_order_text(cls, text, *, band_count):
        tokens = cls._band_tokens_from_band_order_text(text)
        if len(tokens) < 3:
            return None
        if "red" not in tokens or "green" not in tokens or "blue" not in tokens:
            return None
        red_band = int(tokens.index("red")) + 1
        green_band = int(tokens.index("green")) + 1
        blue_band = int(tokens.index("blue")) + 1
        max_idx = max(red_band, green_band, blue_band)
        if int(max_idx) > int(max(1, int(band_count or 0))):
            return None
        return (red_band, green_band, blue_band)

    @classmethod
    def _band_order_text_from_item(cls, item):
        row = item if isinstance(item, dict) else {}
        for key in ("band_order", "bandOrder", "band_order_string", "bandOrderString"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        raw = row.get("raw")
        raw_row = raw if isinstance(raw, dict) else {}
        properties = raw_row.get("properties") if isinstance(raw_row.get("properties"), dict) else {}

        band_rows = properties.get("eo:bands")
        if isinstance(band_rows, list):
            band_names = []
            for band in band_rows:
                band_row = band if isinstance(band, dict) else {}
                token = (
                    str(band_row.get("common_name") or "").strip()
                    or str(band_row.get("name") or "").strip()
                    or str(band_row.get("id") or "").strip()
                )
                normalized = cls._normalized_band_token(token)
                if normalized:
                    band_names.append(normalized)
            if band_names:
                return " ".join(band_names)

        for scope in (properties, raw_row):
            if not isinstance(scope, dict):
                continue
            for key, value in scope.items():
                if not isinstance(value, str):
                    continue
                key_norm = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower())
                if "band" not in key_norm:
                    continue
                if "order" not in key_norm and "name" not in key_norm:
                    continue
                text = str(value or "").strip()
                if text:
                    return text
        return ""

    def _download_group_band_order_text(self, group_items):
        rows = [row for row in (group_items or []) if isinstance(row, dict)]
        for row in rows:
            text = self._band_order_text_from_item(row)
            if text:
                return text
        return ""

    def _apply_download_layer_rendering(self, *, layer, band_order_text):
        if layer is None or not layer.isValid():
            return

        rgb_map = self._rgb_band_map_from_band_order_text(
            band_order_text,
            band_count=int(layer.bandCount() or 0),
        )
        if rgb_map:
            red_band, green_band, blue_band = rgb_map
            renderer = layer.renderer()
            applied_rgb_map = False
            if renderer is not None and all(
                hasattr(renderer, name) for name in ("setRedBand", "setGreenBand", "setBlueBand")
            ):
                try:
                    renderer.setRedBand(int(red_band))
                    renderer.setGreenBand(int(green_band))
                    renderer.setBlueBand(int(blue_band))
                    applied_rgb_map = True
                except Exception:
                    applied_rgb_map = False
            if applied_rgb_map:
                self._append_search_log(
                    "Download Selected display bands mapped via band order "
                    f"'{band_order_text}': R={red_band}, G={green_band}, B={blue_band}"
                )

        try:
            from qgis.core import QgsCubicRasterResampler  # noqa: PLC0415

            resample_filter = layer.resampleFilter() if hasattr(layer, "resampleFilter") else None
            if resample_filter is not None:
                if hasattr(resample_filter, "setZoomedInResampler"):
                    resample_filter.setZoomedInResampler(QgsCubicRasterResampler())
                if hasattr(resample_filter, "setZoomedOutResampler"):
                    resample_filter.setZoomedOutResampler(QgsCubicRasterResampler())
                if hasattr(resample_filter, "setMaxOversampling"):
                    resample_filter.setMaxOversampling(float(5.0))
        except Exception as exc:
            self._append_search_log(
                f"Download Selected resampling configuration skipped: {exc}",
                level=Qgis.Warning,
            )

        if hasattr(layer, "triggerRepaint"):
            try:
                layer.triggerRepaint()
            except Exception:
                pass

    def _geotiff_asset_candidates_for_item(self, item):
        row = item if isinstance(item, dict) else {}
        assets = row.get("assets") if isinstance(row.get("assets"), dict) else {}
        source_id = str(row.get("source_id") or "").strip().lower()
        collection_id = str(row.get("collection") or "").strip().lower()

        if source_id == "merlin-s2":
            ordered_keys = ["visual_fullres", "analytic", "visual", "preview", "thumbnail"]
        else:
            ordered_keys = ["analytic", "visual_fullres", "visual", "preview", "thumbnail"]
        # Quickview thumb usually resolves to one whole-image asset; keep direct visual keys first.
        if collection_id == "quickview-visual-thumb":
            ordered_keys = ["visual", "visual_fullres", "analytic", "preview", "thumbnail"]

        out = []
        seen_urls = set()
        for key in ordered_keys:
            url = str(assets.get(key) or "").strip()
            if not url or url in seen_urls:
                continue
            key_norm = str(key or "").strip().lower()
            if key_norm in {"preview", "thumbnail", "browse"} and not self._asset_url_hints_geotiff(url):
                continue
            seen_urls.add(url)
            out.append((key, url))

        # Add any remaining explicit GeoTIFF-like URLs not covered above.
        for key, value in assets.items():
            key_norm = str(key or "").strip()
            url = str(value or "").strip()
            if not url or url in seen_urls:
                continue
            if not self._asset_url_hints_geotiff(url):
                continue
            seen_urls.add(url)
            out.append((key_norm or "asset", url))
        return out

    @staticmethod
    def _asset_url_hints_geotiff(url):
        text = str(url or "").strip()
        if not text:
            return False
        path_suffix = Path(urlparse(text).path).suffix.lower()
        if path_suffix in {".tif", ".tiff", ".geotiff"}:
            return True
        lower = text.lower()
        for token in ("format=tif", "format=tiff", "image/tiff", "image%2ftiff", "application/geotiff"):
            if token in lower:
                return True
        return False

    @staticmethod
    def _bytes_look_like_tiff(data):
        sample = bytes(data[:8] if data else b"")
        return bool(sample.startswith(b"II*\x00") or sample.startswith(b"MM\x00*"))

    @classmethod
    def _path_looks_like_tiff(cls, path_value):
        path = Path(str(path_value or "")).expanduser()
        if not path.exists() or not path.is_file():
            return False
        suffix = str(path.suffix or "").strip().lower()
        if suffix in {".tif", ".tiff", ".geotiff"}:
            return True
        try:
            with path.open("rb") as handle:
                header = handle.read(8)
        except Exception:
            return False
        return cls._bytes_look_like_tiff(header)

    def _download_geotiff_asset_for_item(self, *, item, task):
        row = item if isinstance(item, dict) else {}
        item_id = str(row.get("id") or "").strip() or "unknown-item"
        source_id = str(row.get("source_id") or "").strip() or None
        contract_id = str(row.get("contract_id") or "").strip() or None
        candidates = self._geotiff_asset_candidates_for_item(row)
        if not candidates:
            raise RuntimeError(f"No GeoTIFF-like assets listed for item {item_id}.")

        errors = []
        attempted_keys = []
        for key, url in candidates:
            if task.isCanceled():
                raise RuntimeError("Task canceled")
            attempted_keys.append(str(key or "").strip() or "asset")
            expected_size = self._asset_expected_size_bytes(
                item=row,
                asset_key=key,
                asset_url=url,
            )
            try:
                cached_path = self._find_cached_temp_asset_path(
                    item=row,
                    preferred_key=key,
                    asset_url=url,
                    expected_size=expected_size,
                )
                if cached_path is not None and self._path_looks_like_tiff(cached_path):
                    return {
                        "item_id": item_id,
                        "asset_key": str(key or "").strip() or "asset",
                        "asset_url": str(url or "").strip(),
                        "path": str(cached_path),
                        "from_cache": True,
                    }

                data = self.source_service.download_asset(url, source_hint=source_id, contract_id=contract_id)
                if not self._bytes_look_like_tiff(data):
                    raise RuntimeError("asset payload is not TIFF/GeoTIFF")
                saved_path = self._write_temp_asset(item=row, url=url, data=data, preferred_key=key)
                if not self._path_looks_like_tiff(saved_path):
                    raise RuntimeError("downloaded file does not look like GeoTIFF")
                return {
                    "item_id": item_id,
                    "asset_key": str(key or "").strip() or "asset",
                    "asset_url": str(url or "").strip(),
                    "path": str(saved_path),
                    "from_cache": False,
                }
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                continue

        attempted = ",".join(attempted_keys) if attempted_keys else "none"
        first_error = errors[0] if errors else "download failed"
        raise RuntimeError(
            f"GeoTIFF download failed for item {item_id}; attempted_assets=[{attempted}] first_error={first_error}"
        )

    def _run_download_selected_task(self, task, groups):
        rows = [dict(row) for row in (groups or []) if isinstance(row, dict)]
        total_items = sum(len(row.get("items") or []) for row in rows)
        completed_items = 0
        result = {
            "canceled": False,
            "groups": [],
            "downloaded_files": 0,
            "group_errors": [],
        }

        for group in rows:
            if task.isCanceled():
                result["canceled"] = True
                return result
            outcome_id = str(group.get("outcome_id") or "").strip()
            item_ids = [str(value or "").strip() for value in (group.get("item_ids") or []) if str(value or "").strip()]
            group_items = [dict(row) for row in (group.get("items") or []) if isinstance(row, dict)]
            group_result = {
                "outcome_id": outcome_id,
                "item_ids": item_ids,
                "downloads": [],
                "errors": [],
                "display_timestamp": self._download_group_display_timestamp(group_items),
                "band_order_text": self._download_group_band_order_text(group_items),
            }
            for item in group_items:
                if task.isCanceled():
                    result["canceled"] = True
                    return result
                try:
                    downloaded = self._download_geotiff_asset_for_item(item=item, task=task)
                    group_result["downloads"].append(downloaded)
                    result["downloaded_files"] = int(result.get("downloaded_files") or 0) + 1
                except Exception as exc:
                    item_id = str((item if isinstance(item, dict) else {}).get("id") or "").strip() or "item"
                    group_result["errors"].append(f"{item_id}: {exc}")
                completed_items += 1
                if total_items > 0:
                    task.setProgress(min(100.0, (float(completed_items) * 100.0) / float(total_items)))
            if group_result["errors"]:
                result["group_errors"].extend(group_result["errors"])
            result["groups"].append(group_result)
        return result

    def _on_download_selected_task_finished(self, task_id, exception, result):
        if self.dock is not None and hasattr(self.dock, "_refresh_download_selected_button_state"):
            self.dock._refresh_download_selected_button_state()
        meta = self._download_selected_tasks.pop(str(task_id or "").strip(), {})
        groups_total = int(meta.get("groups_total") or 0)
        items_total = int(meta.get("items_total") or 0)
        started_utc = str(meta.get("started_utc") or "")
        updated_utc = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
        if not self._download_selected_tasks and self._download_selected_monitor_timer.isActive():
            self._download_selected_monitor_timer.stop()

        if exception is not None:
            if self.dock is not None:
                self.dock.upsert_download_task_status(
                    task_id,
                    {
                        "status": "failed",
                        "progress_pct": 0.0,
                        "groups_total": groups_total,
                        "items_total": items_total,
                        "downloaded_files": 0,
                        "started_utc": started_utc,
                        "updated_utc": updated_utc,
                        "note": f"Failed: {exception}",
                    },
                )
                self.dock.set_download_monitor_progress(0.0, f"Download monitor: {task_id} failed")
            self._append_search_log(f"Download Selected failed: {exception}", level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Download Selected failed: {exception}",
                level=Qgis.Warning,
                duration=10,
            )
            return

        summary = result if isinstance(result, dict) else {}
        if bool(summary.get("canceled")):
            if self.dock is not None:
                self.dock.upsert_download_task_status(
                    task_id,
                    {
                        "status": "canceled",
                        "progress_pct": 0.0,
                        "groups_total": groups_total,
                        "items_total": items_total,
                        "downloaded_files": int(summary.get("downloaded_files") or 0),
                        "started_utc": started_utc,
                        "updated_utc": updated_utc,
                        "note": "Canceled",
                    },
                )
                self.dock.set_download_monitor_progress(0.0, f"Download monitor: {task_id} canceled")
            self._append_search_log("Download Selected canceled.")
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Download Selected canceled.",
                level=Qgis.Warning,
                duration=6,
            )
            return

        groups = summary.get("groups") if isinstance(summary.get("groups"), list) else []
        layers_added = 0
        layer_errors = []
        for idx, group in enumerate(groups, start=1):
            downloads = group.get("downloads") if isinstance(group.get("downloads"), list) else []
            tif_paths = []
            seen_paths = set()
            for row in downloads:
                path = Path(str((row if isinstance(row, dict) else {}).get("path") or "").strip())
                if not path.exists():
                    continue
                key = str(path).lower()
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                tif_paths.append(path)
            if not tif_paths:
                continue

            outcome_id = str(group.get("outcome_id") or "").strip()
            item_ids = group.get("item_ids") if isinstance(group.get("item_ids"), list) else []
            fallback_hint = str(item_ids[0] if item_ids else f"group_{idx}").strip() or f"group_{idx}"
            hint = outcome_id or fallback_hint
            band_order_text = str(group.get("band_order_text") or "").strip()

            raster_path = ""
            if len(tif_paths) == 1:
                raster_path = str(tif_paths[0])
            else:
                try:
                    output_vrt = self._campaign_geoprocessing_output_path(
                        operation="download_selected_vrt",
                        suffix=".vrt",
                        hint=hint,
                    )
                    self._ensure_processing_runtime(required_algorithms=("gdal:buildvirtualraster",))
                    params = {
                        "INPUT": [str(path) for path in tif_paths],
                        "RESOLUTION": 0,
                        "SEPARATE": False,
                        "PROJ_DIFFERENCE": False,
                        "ADD_ALPHA": False,
                        "OUTPUT": str(output_vrt),
                    }
                    run_result = processing.run("gdal:buildvirtualraster", params)
                    raster_path = str(run_result.get("OUTPUT") or output_vrt).strip()
                    self._append_search_log(
                        f"Built outcome VRT ({hint}) from {len(tif_paths)} tile(s): {raster_path}"
                    )
                except Exception as exc:
                    layer_errors.append(f"{hint}: failed to build VRT ({exc})")
                    continue

            if not raster_path:
                layer_errors.append(f"{hint}: output raster path missing")
                continue

            layer_name = self._download_group_layer_name(group=group, fallback_hint=fallback_hint)
            layer = QgsRasterLayer(raster_path, layer_name)
            if not layer.isValid():
                layer_errors.append(f"{hint}: QGIS failed to open raster ({raster_path})")
                continue
            self._apply_download_layer_rendering(layer=layer, band_order_text=band_order_text)
            self._add_layer_to_image_mate_group(layer, insert_on_top=True)
            layers_added += 1

        downloaded_files = int(summary.get("downloaded_files") or 0)
        final_progress = 100.0 if downloaded_files > 0 or groups_total > 0 else 0.0
        group_errors = summary.get("group_errors") if isinstance(summary.get("group_errors"), list) else []
        if group_errors:
            for text in group_errors[:8]:
                self._append_search_log(f"Download warning: {text}", level=Qgis.Warning)
            if len(group_errors) > 8:
                self._append_search_log(
                    f"Download warning: {len(group_errors) - 8} additional error(s) suppressed.",
                    level=Qgis.Warning,
                )
        if layer_errors:
            for text in layer_errors[:8]:
                self._append_search_log(f"Layer add warning: {text}", level=Qgis.Warning)

        if layers_added > 0:
            if self.dock is not None:
                self.dock.upsert_download_task_status(
                    task_id,
                    {
                        "status": "complete",
                        "progress_pct": final_progress,
                        "groups_total": groups_total,
                        "items_total": items_total,
                        "downloaded_files": downloaded_files,
                        "started_utc": started_utc,
                        "updated_utc": updated_utc,
                        "note": f"Complete: {layers_added} layer(s) added",
                    },
                )
                self.dock.set_download_monitor_progress(
                    final_progress,
                    f"Download monitor: {task_id} complete ({downloaded_files} file(s))",
                )
            self._append_search_log(
                f"Download Selected complete: downloaded {downloaded_files} GeoTIFF file(s), added {layers_added} layer(s)."
            )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Download Selected complete: {layers_added} image layer(s) added.",
                level=Qgis.Success,
                duration=10,
            )
        else:
            if self.dock is not None:
                self.dock.upsert_download_task_status(
                    task_id,
                    {
                        "status": "complete_with_warnings",
                        "progress_pct": final_progress,
                        "groups_total": groups_total,
                        "items_total": items_total,
                        "downloaded_files": downloaded_files,
                        "started_utc": started_utc,
                        "updated_utc": updated_utc,
                        "note": "No usable output layers",
                    },
                )
                self.dock.set_download_monitor_progress(
                    final_progress,
                    f"Download monitor: {task_id} finished (no usable layers)",
                )
            self._append_search_log(
                "Download Selected completed, but no raster layers were added.",
                level=Qgis.Warning,
            )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Download Selected finished with no usable GeoTIFF outputs.",
                level=Qgis.Warning,
                duration=10,
            )

    def handle_tasking_refresh_request(self):
        if self.dock is None:
            return
        source_id = str(self.dock.current_source_id() or "").strip().lower() or "satellogic"
        if source_id != "satellogic":
            self.dock.set_tasking_status(
                "Tasking is currently NewSat Constellation-only. Switch Explore source to NewSat Constellation."
            )
            self.dock.set_tasking_products([])
            self.dock.set_tasking_projects([])
            self.dock.set_tasking_orders([])
            return
        try:
            configured_contract = str(self.dock.contract_id.text() or "").strip() if hasattr(self.dock, "contract_id") else ""
            resolved_contract = self.source_service.resolve_contract_id(configured_contract) or self.source_service.default_contract_id()
            if resolved_contract and not configured_contract and hasattr(self.dock, "set_contract_id"):
                self.dock.set_contract_id(resolved_contract)
            self.dock.set_tasking_status("Loading tasking products, projects, and orders...")
            tasking_limit = 500
            products = self.source_service.list_tasking_products()
            orders = self.source_service.list_tasking_orders(contract_id=resolved_contract, limit=tasking_limit)
            projects = sorted({
                str(row.get("project_name") or "").strip()
                for row in orders
                if str(row.get("project_name") or "").strip()
            })
            self.dock.set_tasking_products(products)
            self.dock.set_tasking_projects(projects)
            self.dock.set_tasking_orders(orders)
            self.dock.set_tasking_status(
                f"Tasking ready: {len(products)} products, {len(projects)} projects, {len(orders)} orders."
            )
        except Exception as exc:
            self.dock.set_tasking_status(f"Tasking refresh failed: {exc}")
            self._append_search_log(f"Tasking refresh failed: {exc}", level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Tasking refresh failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )

    def handle_tasking_submit_request(self, payload):
        if self.dock is None:
            return
        source_id = str(self.dock.current_source_id() or "").strip().lower() or "satellogic"
        if source_id != "satellogic":
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Tasking submission requires source 'NewSat Constellation'.",
                level=Qgis.Warning,
                duration=8,
            )
            return
        request = payload if isinstance(payload, dict) else {}
        target_type = str(request.get("target_type") or "").strip().lower()
        geometry_mode = str(request.get("geometry_mode") or "").strip()
        try:
            geometry = self._resolve_tasking_geometry(target_type=target_type, geometry_mode=geometry_mode)
            cadence = str(request.get("cadence") or "").strip()
            submit_payload = {
                "target_type": target_type,
                "geometry": geometry,
                "order_name": str(request.get("order_name") or "").strip(),
                "project_name": str(request.get("project_name") or "").strip() or None,
                "sku": str(request.get("sku") or "").strip(),
                "start_date": str(request.get("start_date") or "").strip(),
                "end_date": str(request.get("end_date") or "").strip(),
                "revisit_period": cadence if target_type == "point" and cadence else None,
                "remapping_period": cadence if target_type == "area" and cadence else None,
                "contract_id": str(request.get("contract_id") or "").strip() or None,
                "additional_parameters": {},
            }
            created = self.source_service.create_tasking_order(submit_payload)
            order = created.get("order") if isinstance(created, dict) else None
            order_id = str((order or {}).get("id") or "").strip()
            if order_id:
                self.dock.set_tasking_status(f"Tasking order submitted: {order_id}")
            else:
                self.dock.set_tasking_status("Tasking order submitted.")
            self.handle_tasking_refresh_request()
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Tasking order submitted{f' ({order_id})' if order_id else ''}.",
                level=Qgis.Success,
                duration=8,
            )
        except Exception as exc:
            self.dock.set_tasking_status(f"Tasking submit failed: {exc}")
            self._append_search_log(f"Tasking submit failed: {exc}", level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Tasking submit failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )

    def handle_tasking_order_selected(self, order_id):
        if self.dock is None:
            return
        order_key = str(order_id or "").strip()
        if not order_key:
            return
        try:
            contract_id = str(self.dock.contract_id.text() or "").strip() if hasattr(self.dock, "contract_id") else ""
            detail = self.source_service.get_tasking_order(order_key, contract_id=contract_id or None)
            order = detail.get("order") if isinstance(detail, dict) else None
            if isinstance(order, dict):
                self.dock.set_tasking_order_detail(order)
        except Exception:
            # Keep list-provided payload detail if live fetch fails.
            return

    def _log_mosaic(self, message, *, level=Qgis.Info):
        text = str(message or "").strip()
        if not text:
            return
        if hasattr(self, "_append_search_log"):
            self._append_search_log(f"[Mosaic] {text}", level=level)
        if hasattr(self, "_append_debug_log"):
            self._append_debug_log(f"[Mosaic] {text}", level=level)

    def _mosaic_campaign_uid(self):
        campaign_uid = str(self.current_campaign_uid or "").strip()
        if not campaign_uid:
            raise RuntimeError("Campaign context is not configured. Apply a campaign first.")
        return campaign_uid

    def _mosaic_project_paths(self, project_id):
        campaign_uid = self._mosaic_campaign_uid()
        project_key = str(project_id or "").strip()
        if not project_key:
            raise RuntimeError("Mosaic project id is required")
        root = self.campaign_storage.campaign_mosaic_root(campaign_uid)
        project_dir = root / project_key
        db_path = project_dir / "mosaic_tracking.sqlite3"
        shapefile_path = project_dir / "tiles.shp"
        meta_path = project_dir / "project_meta.json"
        return {
            "campaign_uid": campaign_uid,
            "project_dir": project_dir,
            "db_path": db_path,
            "shapefile_path": shapefile_path,
            "meta_path": meta_path,
        }

    def _mosaic_store_for_project(self, project_id, *, create_if_missing):
        paths = self._mosaic_project_paths(project_id)
        db_path = paths["db_path"]
        if not create_if_missing and not db_path.exists():
            raise RuntimeError(f"Mosaic project database not found: {db_path}")
        store = MosaicTrackingStore(db_path)
        store.initialize()
        return store

    def _mosaic_resolved_contract_id(self):
        configured_contract = (
            str(self.dock.contract_id.text() or "").strip()
            if self.dock is not None and hasattr(self.dock, "contract_id")
            else ""
        )
        resolved_contract = (
            self.source_service.resolve_contract_id(configured_contract)
            or self.source_service.default_contract_id()
            or ""
        )
        if (
            self.dock is not None
            and hasattr(self.dock, "set_contract_id")
            and resolved_contract
            and not configured_contract
        ):
            self.dock.set_contract_id(resolved_contract)
        return resolved_contract

    def _mosaic_source_id(self):
        if self.dock is None:
            return "satellogic"
        return str(self.dock.current_source_id() or "").strip().lower() or "satellogic"

    def _mosaic_source_supported(self):
        return self._mosaic_source_id() == "satellogic"

    def _resolve_mosaic_aoi_geojson(self, request):
        source = str(request.get("aoi_source") or "map_extent").strip().lower()
        if source == "polygon_layer":
            layer_id = str(request.get("aoi_layer_id") or "").strip()
            payload = self._simulation_polygon_layer_geometry_wgs84(layer_id)
        else:
            payload = self._current_extent_geometry_wgs84()
        if not isinstance(payload, dict):
            raise RuntimeError("Mosaic AOI resolution did not return a valid geometry object.")
        return payload

    def _clear_mosaic_preview_layer(self):
        layer_id = str(getattr(self, "_mosaic_preview_layer_id", "") or "").strip()
        if not layer_id:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is not None:
            QgsProject.instance().removeMapLayer(layer_id)
        self._mosaic_preview_layer_id = None

    def _clear_mosaic_tracking_preview_layer(self):
        preview_map = getattr(self, "_mosaic_tracking_preview_layer_ids", {})
        if not isinstance(preview_map, dict):
            preview_map = {}
        for layer_value in list(preview_map.values()):
            layer_ids = []
            if isinstance(layer_value, list):
                layer_ids = [str(row or "").strip() for row in layer_value if str(row or "").strip()]
            else:
                layer_key = str(layer_value or "").strip()
                if layer_key:
                    layer_ids = [layer_key]
            for layer_id in layer_ids:
                layer = QgsProject.instance().mapLayer(layer_id)
                if layer is not None:
                    QgsProject.instance().removeMapLayer(layer_id)
        self._mosaic_tracking_preview_layer_ids = {}
        self._mosaic_tracking_preview_project_id = ""

    def _clear_mosaic_tracking_preview_layer_for_tile(self, *, tile_id):
        tile_key = str(tile_id or "").strip()
        if not tile_key:
            return
        preview_map = getattr(self, "_mosaic_tracking_preview_layer_ids", {})
        if not isinstance(preview_map, dict):
            preview_map = {}
        layer_value = preview_map.pop(tile_key, "")
        layer_ids = []
        if isinstance(layer_value, list):
            layer_ids = [str(row or "").strip() for row in layer_value if str(row or "").strip()]
        else:
            layer_key = str(layer_value or "").strip()
            if layer_key:
                layer_ids = [layer_key]
        for layer_id in layer_ids:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer is not None:
                QgsProject.instance().removeMapLayer(layer_id)
        self._mosaic_tracking_preview_layer_ids = preview_map

    def _clear_mosaic_tiling_layer(self):
        layer_id = str(getattr(self, "_mosaic_tiling_layer_id", "") or "").strip()
        if not layer_id:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is not None:
            try:
                layer.selectionChanged.disconnect(self._on_mosaic_tiling_layer_selection_changed)
            except Exception:
                pass
            QgsProject.instance().removeMapLayer(layer_id)
        self._mosaic_tiling_layer_id = None

    @staticmethod
    def _mosaic_layer_source_path(layer):
        raw_source = str(getattr(layer, "source", lambda: "")() or "").strip()
        if not raw_source:
            return ""
        path_token = raw_source.split("|", 1)[0].strip()
        if not path_token:
            return ""
        if path_token.lower().startswith("file://"):
            parsed = QUrl(path_token)
            if parsed.isValid() and parsed.isLocalFile():
                return str(parsed.toLocalFile() or "").strip()
        return path_token

    @staticmethod
    def _mosaic_path_is_within(parent_path: Path, child_path: Path) -> bool:
        try:
            child_path.relative_to(parent_path)
            return True
        except Exception:
            return False

    def _release_mosaic_project_layers(self, *, project_id: str, project_dir: Path, shapefile_path: Path) -> int:
        project_key = str(project_id or "").strip()
        if not project_key:
            return 0
        project_dir_path = Path(project_dir).expanduser()
        project_dir_resolved = project_dir_path.resolve()
        shapefile_resolved = Path(shapefile_path).expanduser().resolve()
        tracked_layer_id = str(getattr(self, "_mosaic_tiling_layer_id", "") or "").strip()
        removed_count = 0
        map_layers = list(QgsProject.instance().mapLayers().items())
        for layer_id, layer in map_layers:
            if layer is None:
                continue
            remove_layer = False
            layer_project_id = str(layer.customProperty("image_mate/mosaic_project_id") or "").strip()
            if layer_project_id and layer_project_id == project_key:
                remove_layer = True
            source_path = self._mosaic_layer_source_path(layer)
            source_path_text = str(source_path or "").strip()
            if source_path_text:
                try:
                    source_path_resolved = Path(source_path_text).expanduser().resolve()
                except Exception:
                    source_path_resolved = Path(source_path_text)
                if source_path_resolved == shapefile_resolved:
                    remove_layer = True
                elif self._mosaic_path_is_within(project_dir_resolved, source_path_resolved):
                    remove_layer = True
                else:
                    source_norm = source_path_text.replace("\\", "/").lower()
                    project_norm = project_key.lower()
                    if f"/{project_norm}/" in source_norm and source_norm.endswith("/tiles.shp"):
                        remove_layer = True
            if not remove_layer:
                continue
            if layer_id == tracked_layer_id:
                try:
                    layer.selectionChanged.disconnect(self._on_mosaic_tiling_layer_selection_changed)
                except Exception:
                    pass
            QgsProject.instance().removeMapLayer(layer_id)
            removed_count += 1
        if tracked_layer_id and QgsProject.instance().mapLayer(tracked_layer_id) is None:
            self._mosaic_tiling_layer_id = None
        return removed_count

    def _render_mosaic_breakdown_preview(self, rows):
        self._clear_mosaic_preview_layer()
        tile_rows = [row for row in (rows or []) if isinstance(row, dict)]
        if not tile_rows:
            return
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Image Mate Mosaic Breakdown", "memory")
        if not layer.isValid():
            return
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("tile_id", QVariant.String),
                QgsField("area_km2", QVariant.Double),
            ]
        )
        layer.updateFields()
        features = []
        for row in tile_rows:
            tile_id = str(row.get("tile_id") or "").strip()
            if not tile_id:
                continue
            geom = None
            geom_wkt = str(row.get("geometry_wkt") or "").strip()
            if geom_wkt:
                try:
                    geom = QgsGeometry.fromWkt(geom_wkt)
                except Exception:
                    geom = None
            if (geom is None or geom.isEmpty()) and isinstance(row.get("geometry"), dict):
                geom = self._geometry_from_geojson(row.get("geometry"))
            if geom is None or geom.isEmpty():
                continue
            feature = QgsFeature(layer.fields())
            feature.setGeometry(geom)
            feature["tile_id"] = tile_id
            feature["area_km2"] = float(row.get("clipped_area_km2") or 0.0)
            features.append(feature)
        if not features:
            return
        provider.addFeatures(features)
        layer.updateExtents()
        layer.setCustomProperty("image_mate/mosaic_breakdown_preview", "1")
        self._add_layer_to_image_mate_group(layer, insert_on_top=True)
        self._mosaic_preview_layer_id = str(layer.id() or "").strip()

    @staticmethod
    def _mosaic_quote_expression_literal(value):
        return "'" + str(value or "").replace("'", "''") + "'"

    def _mosaic_accepted_tile_ids(self, project_id):
        project_key = str(project_id or "").strip()
        if not project_key:
            return set()
        try:
            store = self._mosaic_store_for_project(project_key, create_if_missing=False)
            rows = store.load_tiles(project_key)
        except Exception:
            return set()
        accepted = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            tile_id = str(row.get("tile_id") or "").strip()
            qa_status = str(row.get("qa_status") or "").strip().lower()
            if tile_id and qa_status == "accepted":
                accepted.add(tile_id)
        return accepted

    def _apply_mosaic_tiling_style(self, layer, *, accepted_tile_ids=None, selected_tile_id=""):
        if layer is None or not layer.isValid():
            return

        accepted_ids = {
            str(value or "").strip()
            for value in (accepted_tile_ids or set())
            if str(value or "").strip()
        }
        selected_id = str(selected_tile_id or "").strip()

        default_symbol = QgsFillSymbol.createSimple(
            {
                "style": "no",
                "color": "0,0,0,0",
                "outline_style": "solid",
                "outline_color": "255,255,0,128",
                "outline_width": "0.25",
            }
        )
        if default_symbol is None:
            return

        accepted_symbol = QgsFillSymbol.createSimple(
            {
                "style": "solid",
                "color": "144,238,144,128",
                "outline_style": "solid",
                "outline_color": "255,255,0,128",
                "outline_width": "0.25",
            }
        )
        if accepted_symbol is None:
            return

        selected_symbol = QgsFillSymbol.createSimple(
            {
                "style": "no",
                "color": "0,0,0,0",
                "outline_style": "solid",
                "outline_color": "255,255,0,128",
                "outline_width": "0.75",
            }
        )
        if selected_symbol is None:
            return

        selected_accepted_symbol = QgsFillSymbol.createSimple(
            {
                "style": "solid",
                "color": "144,238,144,128",
                "outline_style": "solid",
                "outline_color": "255,255,0,128",
                "outline_width": "0.75",
            }
        )
        if selected_accepted_symbol is None:
            return

        accepted_expr = ""
        if accepted_ids:
            accepted_values = ",".join(
                self._mosaic_quote_expression_literal(value) for value in sorted(accepted_ids)
            )
            accepted_expr = f"\"tile_id\" IN ({accepted_values})"
        selected_expr = ""
        if selected_id:
            selected_expr = f"\"tile_id\" = {self._mosaic_quote_expression_literal(selected_id)}"

        accepted_check = accepted_expr if accepted_expr else "FALSE"
        selected_check = selected_expr if selected_expr else "FALSE"
        expression = (
            "CASE "
            f"WHEN ({selected_check}) AND ({accepted_check}) THEN 'selected_accepted' "
            f"WHEN ({selected_check}) THEN 'selected' "
            f"WHEN ({accepted_check}) THEN 'accepted' "
            "ELSE 'default' "
            "END"
        )
        categories = [
            QgsRendererCategory("selected_accepted", selected_accepted_symbol, "Selected Accepted"),
            QgsRendererCategory("selected", selected_symbol, "Selected"),
            QgsRendererCategory("accepted", accepted_symbol, "Accepted"),
            QgsRendererCategory("default", default_symbol, "Default"),
        ]
        renderer = QgsCategorizedSymbolRenderer(expression, categories)

        layer.setRenderer(renderer)
        layer.triggerRepaint()

    def _show_mosaic_tiling_layer(self, *, project_id: str, shapefile_path: Path) -> None:
        if not shapefile_path.exists():
            raise RuntimeError(f"Mosaic tiling shapefile not found: {shapefile_path}")
        self._clear_mosaic_tiling_layer()
        layer = QgsVectorLayer(str(shapefile_path), f"Image Mate Mosaic Tiling ({project_id})", "ogr")
        if not layer.isValid():
            raise RuntimeError(f"Failed to load Mosaic tiling shapefile: {shapefile_path}")
        layer.setCustomProperty("image_mate/mosaic_tiling", "1")
        layer.setCustomProperty("image_mate/mosaic_project_id", str(project_id or "").strip())
        selected_tile_id = ""
        if self.dock is not None and hasattr(self.dock, "current_mosaic_project_id"):
            selected_project = str(self.dock.current_mosaic_project_id() or "").strip()
            if selected_project == str(project_id or "").strip() and hasattr(self.dock, "current_mosaic_selected_tile_id"):
                selected_tile_id = str(self.dock.current_mosaic_selected_tile_id() or "").strip()
        accepted_tile_ids = self._mosaic_accepted_tile_ids(project_id)
        self._apply_mosaic_tiling_style(
            layer,
            accepted_tile_ids=accepted_tile_ids,
            selected_tile_id=selected_tile_id,
        )
        try:
            layer.selectionChanged.connect(self._on_mosaic_tiling_layer_selection_changed)
        except Exception:
            pass
        self._add_layer_to_image_mate_group(layer, insert_on_top=True)
        self._mosaic_tiling_layer_id = str(layer.id() or "").strip()

    def _on_mosaic_tiling_layer_selection_changed(self, selected, _deselected, _clear_and_select):
        if bool(getattr(self, "_mosaic_tiling_sync_guard", False)):
            return
        layer_id = str(getattr(self, "_mosaic_tiling_layer_id", "") or "").strip()
        if not layer_id:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None or not layer.isValid():
            return
        selected_ids = list(selected or [])
        if not selected_ids:
            return
        tile_id = ""
        for fid in selected_ids:
            try:
                feature = layer.getFeature(int(fid))
            except Exception:
                feature = None
            if feature is None or not feature.isValid():
                continue
            tile_id = str(feature.attribute("tile_id") or "").strip()
            if tile_id:
                break
        if not tile_id:
            return

        self._mosaic_tiling_sync_guard = True
        try:
            if self.dock is not None and hasattr(self.dock, "select_mosaic_tracking_tile"):
                self.dock.select_mosaic_tracking_tile(tile_id, scroll=True)
            project_id = str(layer.customProperty("image_mate/mosaic_project_id") or "").strip()
            self._refresh_mosaic_tiling_style(project_id=project_id, selected_tile_id=tile_id)
        finally:
            self._mosaic_tiling_sync_guard = False

    def _refresh_mosaic_tiling_style(self, *, project_id="", selected_tile_id=""):
        layer_id = str(getattr(self, "_mosaic_tiling_layer_id", "") or "").strip()
        if not layer_id:
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None or not layer.isValid():
            return
        shown_project = str(layer.customProperty("image_mate/mosaic_project_id") or "").strip()
        target_project = str(project_id or shown_project).strip()
        if not target_project:
            return
        if shown_project and target_project and shown_project != target_project:
            return
        selected_tile = str(selected_tile_id or "").strip()
        if not selected_tile and self.dock is not None and hasattr(self.dock, "current_mosaic_selected_tile_id"):
            selected_tile = str(self.dock.current_mosaic_selected_tile_id() or "").strip()
        accepted_tile_ids = self._mosaic_accepted_tile_ids(target_project)
        self._apply_mosaic_tiling_style(
            layer,
            accepted_tile_ids=accepted_tile_ids,
            selected_tile_id=selected_tile,
        )

    def _load_mosaic_tracking_project(self, project_id):
        project_key = str(project_id or "").strip()
        if self.dock is None:
            return
        if not project_key:
            self._clear_mosaic_tracking_preview_layer()
            if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
                self.dock.set_mosaic_tracking_preview_tiles([])
            self.dock.set_mosaic_tracking_rows([])
            self.dock.set_mosaic_tracking_status("Mosaic tracking: select a project.")
            return
        shown_preview_project = str(getattr(self, "_mosaic_tracking_preview_project_id", "") or "").strip()
        if shown_preview_project and shown_preview_project != project_key:
            self._clear_mosaic_tracking_preview_layer()
            if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
                self.dock.set_mosaic_tracking_preview_tiles([])
        store = self._mosaic_store_for_project(project_key, create_if_missing=False)
        rows = store.load_tiles(project_key)
        self.dock.set_mosaic_tracking_rows(rows)
        if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
            preview_map = getattr(self, "_mosaic_tracking_preview_layer_ids", {})
            if isinstance(preview_map, dict):
                self.dock.set_mosaic_tracking_preview_tiles(sorted(preview_map.keys()))
            else:
                self.dock.set_mosaic_tracking_preview_tiles([])
        self._refresh_mosaic_tiling_style(project_id=project_key)
        self.dock.set_mosaic_tracking_status(
            f"Mosaic tracking loaded: project={project_key}, tiles={len(rows)}."
        )

    def handle_mosaic_refresh_projects_request(self):
        if self.dock is None:
            return
        campaign_uid = str(self.current_campaign_uid or "").strip()
        projects = []
        if campaign_uid:
            try:
                projects = self.campaign_storage.list_mosaic_projects(campaign_uid)
            except Exception as exc:
                self.dock.set_mosaic_tracking_status(f"Mosaic projects refresh failed: {exc}")
                self._log_mosaic(f"project_refresh_failed error={exc}", level=Qgis.Warning)
                return
        self.dock.set_mosaic_projects(projects)
        self.dock.set_mosaic_tracking_status(
            f"Mosaic projects available: {len(projects)}."
        )
        selected_project = (
            str(self.dock.current_mosaic_project_id() or "").strip()
            if hasattr(self.dock, "current_mosaic_project_id")
            else ""
        )
        if selected_project:
            try:
                self._load_mosaic_tracking_project(selected_project)
            except Exception as exc:
                self._log_mosaic(
                    f"project_autoload_failed project={selected_project} error={exc}",
                    level=Qgis.Warning,
                )

    def handle_mosaic_breakdown_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        try:
            self.dock.set_mosaic_create_status("Mosaic create: running AOI breakdown...")
            aoi_geojson = self._resolve_mosaic_aoi_geojson(request)
            breakdown = self.mosaic_grid_service.build_breakdown(aoi_geojson)
            rows = [dict(row) for row in (breakdown.get("tiles") or []) if isinstance(row, dict)]
            estimated_price_usd = float(breakdown.get("estimated_price_usd") or 0.0)
            total_area_km2 = float(breakdown.get("total_area_km2") or 0.0)
            self._mosaic_breakdown_rows = rows
            self._mosaic_breakdown_context = {
                "aoi_source": str(request.get("aoi_source") or "map_extent").strip(),
                "aoi_layer_id": str(request.get("aoi_layer_id") or "").strip(),
                "aoi_geojson": aoi_geojson,
                "source_id": self._mosaic_source_id(),
                "estimated_price_usd": estimated_price_usd,
                "total_area_km2": total_area_km2,
            }
            self._render_mosaic_breakdown_preview(rows)
            self.dock.set_mosaic_breakdown_rows(rows)
            self.dock.set_mosaic_estimated_price(estimated_price_usd)
            self.dock.set_mosaic_create_status(
                f"Mosaic breakdown ready: tiles={len(rows)}, area={total_area_km2:.2f} km2, "
                f"price=${estimated_price_usd:,.2f}."
            )
            self._log_mosaic(
                f"breakdown_complete tiles={len(rows)} area_km2={total_area_km2:.3f} "
                f"price_usd={estimated_price_usd:.2f}"
            )
        except Exception as exc:
            self._mosaic_breakdown_rows = []
            self._mosaic_breakdown_context = {}
            self.dock.set_mosaic_breakdown_rows([])
            self.dock.set_mosaic_estimated_price(0.0)
            self.dock.set_mosaic_create_status(f"Mosaic breakdown failed: {exc}")
            self._log_mosaic(f"breakdown_failed error={exc}", level=Qgis.Warning)

    def handle_mosaic_accept_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        project_id = str(request.get("project_id") or "").strip()
        add_tasking = bool(request.get("add_tasking", True))
        valid, reason = validate_project_id(project_id)
        if not valid:
            self.dock.set_mosaic_create_status(f"Mosaic accept blocked: {reason}")
            return
        rows = [dict(row) for row in (self._mosaic_breakdown_rows or []) if isinstance(row, dict)]
        if not rows:
            self.dock.set_mosaic_create_status("Mosaic accept blocked: run 'Breakdown AOI' first.")
            return
        try:
            paths = self._mosaic_project_paths(project_id)
            campaign_uid = paths["campaign_uid"]
            if self.campaign_storage.mosaic_project_exists(campaign_uid, project_id):
                raise RuntimeError(f"Mosaic project already exists in campaign: {project_id}")
            source_id = str(self._mosaic_breakdown_context.get("source_id") or self._mosaic_source_id()).strip().lower()
            aoi_geojson = self._mosaic_breakdown_context.get("aoi_geojson")
            if not isinstance(aoi_geojson, dict):
                raise RuntimeError("Mosaic AOI context is unavailable. Run breakdown again.")
            estimated_price_usd = float(self._mosaic_breakdown_context.get("estimated_price_usd") or 0.0)
            aoi_source = str(self._mosaic_breakdown_context.get("aoi_source") or "map_extent").strip()

            shapefile_path = self.mosaic_tasking_service.write_tiles_shapefile(
                tile_rows=rows,
                shapefile_path=str(paths["shapefile_path"]),
            )
            store = MosaicTrackingStore(paths["db_path"])
            store.initialize()
            store.create_project_with_tiles(
                project_id=project_id,
                campaign_uid=campaign_uid,
                source_id=source_id,
                aoi_source=aoi_source,
                aoi_geojson=aoi_geojson,
                estimated_price_usd=estimated_price_usd,
                shapefile_path=shapefile_path,
                tile_rows=rows,
                mutation_source="create",
            )
            meta_payload = {
                "schema_version": 1,
                "project_id": project_id,
                "campaign_uid": campaign_uid,
                "source_id": source_id,
                "aoi_source": aoi_source,
                "tile_count": len(rows),
                "estimated_price_usd": estimated_price_usd,
                "price_per_km2_usd": PRICE_USD_PER_KM2,
                "shapefile_path": str(shapefile_path),
                "created_at": utc_now_iso(),
            }
            paths["meta_path"].write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")

            submitted = 0
            failed = int(len(rows))
            if add_tasking:
                contract_id = self._mosaic_resolved_contract_id()
                submit_results = self.mosaic_tasking_service.submit_tiles(
                    store=store,
                    source_service=self.source_service,
                    project_id=project_id,
                    tile_rows=rows,
                    contract_id=contract_id,
                    source_id=source_id,
                    sku=TASKING_DEFAULT_SKU,
                )
                submitted = sum(
                    1
                    for row in submit_results
                    if str(row.get("attempt_status") or "").strip() == ATTEMPT_STATUS_SUBMITTED
                )
                failed = sum(
                    1
                    for row in submit_results
                    if str(row.get("attempt_status") or "").strip() not in {ATTEMPT_STATUS_SUBMITTED}
                )
            self.handle_mosaic_refresh_projects_request()
            if hasattr(self.dock, "set_mosaic_current_project"):
                self.dock.set_mosaic_current_project(project_id)
            self._load_mosaic_tracking_project(project_id)
            source_note = ""
            if not add_tasking:
                source_note = " Tasking not added (Add Tasking unchecked)."
            elif source_id != "satellogic":
                source_note = " Source is not NewSat Constellation, so tile submissions were skipped."
            self.dock.set_mosaic_create_status(
                f"Mosaic project accepted: {project_id}. tiles={len(rows)}, submitted={submitted}, "
                f"non-submitted={failed}.{source_note}"
            )
            self._log_mosaic(
                f"accept_complete project={project_id} tiles={len(rows)} submitted={submitted} "
                f"non_submitted={failed} source={source_id} add_tasking={bool(add_tasking)}"
            )
        except Exception as exc:
            self.dock.set_mosaic_create_status(f"Mosaic accept failed: {exc}")
            self._log_mosaic(f"accept_failed project={project_id} error={exc}", level=Qgis.Warning)

    def handle_mosaic_tracking_project_changed(self, project_id):
        if self.dock is None:
            return
        try:
            self._load_mosaic_tracking_project(project_id)
        except Exception as exc:
            self._clear_mosaic_tracking_preview_layer()
            if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
                self.dock.set_mosaic_tracking_preview_tiles([])
            self.dock.set_mosaic_tracking_rows([])
            self.dock.set_mosaic_tracking_status(f"Mosaic tracking load failed: {exc}")
            self._log_mosaic(f"tracking_load_failed project={project_id} error={exc}", level=Qgis.Warning)

    def handle_mosaic_tracking_tile_selected(self, payload):
        request = payload if isinstance(payload, dict) else {}
        project_id = str(request.get("project_id") or "").strip()
        tile_id = str(request.get("tile_id") or "").strip()
        self._refresh_mosaic_tiling_style(project_id=project_id, selected_tile_id=tile_id)

    def _mosaic_preview_item_is_usable(self, item):
        row = item if isinstance(item, dict) else {}
        if not row:
            return False
        assets = row.get("assets") if isinstance(row.get("assets"), dict) else {}
        for key in ("preview", "thumbnail", "visual", "visual_fullres", "analytic"):
            if str(assets.get(key) or "").strip():
                return True
        if self._satellogic_item_cog_source_url(row):
            return True
        return False

    def _mosaic_preview_geometry_from_tile_row(self, tile_row):
        row = tile_row if isinstance(tile_row, dict) else {}
        geom_wkt = str(row.get("geometry_wkt") or "").strip()
        if not geom_wkt:
            return {}
        try:
            geom = QgsGeometry.fromWkt(geom_wkt)
        except Exception:
            return {}
        if geom is None or geom.isEmpty():
            return {}
        try:
            as_json = geom.asJson()
            payload = json.loads(as_json) if as_json else {}
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _mosaic_preview_item_from_deliverable(self, *, deliverable, contract_id):
        row = deliverable if isinstance(deliverable, dict) else {}
        assets_src = row.get("assets") if isinstance(row.get("assets"), dict) else {}
        if not assets_src:
            return None

        normalized_assets = {}
        raw_assets = {}

        def _asset_href(asset_value):
            if isinstance(asset_value, dict):
                return str(asset_value.get("href") or "").strip()
            return str(asset_value or "").strip()

        for key in ("visual_fullres", "visual", "analytic", "preview", "thumbnail"):
            href = _asset_href(assets_src.get(key))
            if not href:
                continue
            normalized_assets[key] = href
            raw_asset = assets_src.get(key)
            if isinstance(raw_asset, dict):
                payload = dict(raw_asset)
                payload["href"] = href
                raw_assets[key] = payload
            else:
                raw_assets[key] = {"href": href}

        if not normalized_assets:
            for key, asset in assets_src.items():
                key_text = str(key or "").strip()
                href = _asset_href(asset)
                if not key_text or not href:
                    continue
                normalized_assets[key_text] = href
                if isinstance(asset, dict):
                    payload = dict(asset)
                    payload["href"] = href
                    raw_assets[key_text] = payload
                else:
                    raw_assets[key_text] = {"href": href}

        if not normalized_assets:
            return None

        if "visual_fullres" not in normalized_assets and normalized_assets.get("visual"):
            normalized_assets["visual_fullres"] = normalized_assets.get("visual") or ""
            raw_assets["visual_fullres"] = dict(raw_assets.get("visual") or {"href": normalized_assets["visual_fullres"]})

        scene_id = ""
        for key in ("visual_fullres", "visual", "analytic", "preview", "thumbnail"):
            href = str(normalized_assets.get(key) or "").strip()
            if not href:
                continue
            scene_id = self._satellogic_scene_id_from_asset_href(href)
            if scene_id:
                break
        if not scene_id:
            for href in normalized_assets.values():
                tif_name = self._satellogic_tif_name_from_href(href)
                scene_id = self._satellogic_scene_id_from_tif_name(tif_name)
                if scene_id:
                    break

        deliverable_id = str(row.get("deliverable_id") or row.get("id") or "").strip()
        item_id = scene_id or deliverable_id
        if not item_id:
            return None

        raw_payload = {
            "id": item_id,
            "scene_id": scene_id,
            "assets": raw_assets,
            "properties": {
                "scene_id": scene_id,
                "satl:scene_id": scene_id,
                "deliverable_id": deliverable_id,
                "order_id": str(row.get("order") or "").strip(),
            },
            "deliverable": row,
        }
        if contract_id:
            raw_payload["properties"]["contract_id"] = contract_id

        result = {
            "id": item_id,
            "scene_id": scene_id,
            "source_id": "satellogic",
            "collection": "l1d-sr",
            "assets": normalized_assets,
            "raw": raw_payload,
        }
        if contract_id:
            result["contract_id"] = contract_id
        return result

    def _resolve_mosaic_tracking_preview_items(self, *, tile_row, collection_id):
        tile_data = tile_row if isinstance(tile_row, dict) else {}
        collection_key = str(collection_id or "").strip()
        if not collection_key:
            raise RuntimeError("Missing latest collection id.")

        contract_id = self._mosaic_resolved_contract_id()
        detail = self.source_service.get_tasking_order(collection_key, contract_id=contract_id or None)

        resolved_items = []
        resolved_ids = set()

        try:
            deliverable_detail = self.source_service.list_tasking_order_deliverables(
                collection_key,
                contract_id=contract_id or None,
            )
        except Exception as exc:
            self._log_mosaic(
                f"preview_deliverables_failed collection_id={collection_key} error={exc}",
                level=Qgis.Warning,
            )
            deliverable_detail = {}

        deliverables = deliverable_detail.get("deliverables") if isinstance(deliverable_detail, dict) else []
        deliverable_rows = [row for row in (deliverables or []) if isinstance(row, dict)]
        if deliverable_rows:
            delivered_statuses = {"DELIVERED", "COMPLETED", "SUCCESS", "SUCCEEDED"}
            preferred_rows = [
                row for row in deliverable_rows if str(row.get("status") or "").strip().upper() in delivered_statuses
            ]
            candidate_rows = preferred_rows or deliverable_rows
            for deliverable in candidate_rows:
                item = self._mosaic_preview_item_from_deliverable(
                    deliverable=deliverable,
                    contract_id=contract_id,
                )
                if not self._mosaic_preview_item_is_usable(item):
                    continue
                resolved_id = str(item.get("id") or "").strip()
                if resolved_id and resolved_id in resolved_ids:
                    continue
                if resolved_id:
                    resolved_ids.add(resolved_id)
                resolved_items.append(item)
        if resolved_items:
            return resolved_items

        for item_id in preview_item_id_candidates(detail):
            try:
                item = self.source_service.item_by_id(
                    item_id,
                    source_id="satellogic",
                    contract_id=contract_id or None,
                    collection_id="l1d-sr",
                )
            except Exception:
                item = None
            if not self._mosaic_preview_item_is_usable(item):
                continue
            resolved = dict(item)
            resolved.setdefault("source_id", "satellogic")
            if contract_id:
                resolved["contract_id"] = contract_id
            resolved_id = str(resolved.get("id") or item_id).strip()
            if resolved_id and resolved_id in resolved_ids:
                continue
            if resolved_id:
                resolved_ids.add(resolved_id)
            resolved_items.append(resolved)
        if resolved_items:
            return resolved_items

        geometry = extract_order_geometry(detail)
        if not geometry:
            geometry = self._mosaic_preview_geometry_from_tile_row(tile_data)
        if not geometry:
            raise RuntimeError("Preview search skipped: tasking order geometry unavailable.")

        start_date, end_date = preview_search_window(detail)
        for collection_hint in preview_collection_candidates(detail):
            search_request = {
                "source_id": "satellogic",
                "collection_id": collection_hint,
                "geometry": geometry,
                "start_date": start_date,
                "end_date": end_date,
                "contract_id": contract_id,
                "limit": 25,
                "max_cloud_cover": None,
            }
            try:
                items = self.source_service.search(search_request)
            except Exception as exc:
                self._log_mosaic(
                    "preview_search_failed "
                    f"collection={collection_hint} start={start_date} end={end_date} error={exc}",
                    level=Qgis.Warning,
                )
                continue
            for item in items:
                if not self._mosaic_preview_item_is_usable(item):
                    continue
                resolved = dict(item)
                resolved.setdefault("source_id", "satellogic")
                if contract_id:
                    resolved["contract_id"] = contract_id
                return [resolved]
        raise RuntimeError("No preview imagery found for the completed collection.")

    def _render_mosaic_tracking_preview_item(self, *, project_id, tile_id, item):
        image_error = ""
        stream_error = ""
        layer = None
        try:
            # Match browser behavior when possible: render Telluric tile stream first.
            layer = self._build_stream_layer_for_item(item, prefer_telluric=True)
        except Exception as exc:
            stream_error = str(exc)
            layer = None
        if layer is None:
            try:
                layer = self._load_item_imagery_layer(item)
            except Exception as exc:
                image_error = str(exc)
                layer = None
        if layer is None:
            try:
                layer = self._build_stream_layer_for_item(item)
            except Exception as exc:
                if not stream_error:
                    stream_error = str(exc)
                layer = None
        if layer is None:
            raise RuntimeError(stream_error or image_error or "Preview imagery layer could not be loaded.")

        tile_key = str(tile_id or "").strip()
        project_key = str(project_id or "").strip()
        if not tile_key:
            raise RuntimeError("Preview layer render requires a tile id.")
        self._add_layer_to_image_mate_group(layer, insert_on_top=True)
        layer.setCustomProperty("image_mate/mosaic_tracking_preview", "1")
        layer.setCustomProperty("image_mate/mosaic_tracking_tile_id", tile_key)
        layer.setCustomProperty("image_mate/mosaic_tracking_project_id", project_key)
        preview_map = getattr(self, "_mosaic_tracking_preview_layer_ids", {})
        if not isinstance(preview_map, dict):
            preview_map = {}
        existing_value = preview_map.get(tile_key)
        layer_ids = []
        if isinstance(existing_value, list):
            layer_ids = [str(row or "").strip() for row in existing_value if str(row or "").strip()]
        else:
            existing_id = str(existing_value or "").strip()
            if existing_id:
                layer_ids = [existing_id]
        layer_id = str(layer.id() or "").strip()
        if layer_id and layer_id not in layer_ids:
            layer_ids.append(layer_id)
        preview_map[tile_key] = layer_ids
        self._mosaic_tracking_preview_layer_ids = preview_map
        self._mosaic_tracking_preview_project_id = project_key

    def handle_mosaic_tracking_preview_toggled(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        project_id = str(request.get("project_id") or "").strip()
        tile_id = str(request.get("tile_id") or "").strip()
        enabled = bool(request.get("enabled", False))
        if not project_id and hasattr(self.dock, "current_mosaic_project_id"):
            project_id = str(self.dock.current_mosaic_project_id() or "").strip()
        if not project_id or not tile_id:
            if enabled:
                self.dock.set_mosaic_tracking_status("Mosaic preview skipped: select a project and tile.")
            return

        shown_preview_project = str(getattr(self, "_mosaic_tracking_preview_project_id", "") or "").strip()
        if shown_preview_project and shown_preview_project != project_id:
            self._clear_mosaic_tracking_preview_layer()
            if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
                self.dock.set_mosaic_tracking_preview_tiles([])

        if not enabled:
            self._clear_mosaic_tracking_preview_layer_for_tile(tile_id=tile_id)
            preview_map = getattr(self, "_mosaic_tracking_preview_layer_ids", {})
            if not isinstance(preview_map, dict) or not preview_map:
                self._mosaic_tracking_preview_project_id = ""
                preview_ids = []
            else:
                preview_ids = sorted(preview_map.keys())
            if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
                self.dock.set_mosaic_tracking_preview_tiles(preview_ids)
            self.dock.set_mosaic_tracking_status(f"Mosaic preview hidden: tile={tile_id}.")
            self._log_mosaic(f"preview_hidden project={project_id} tile={tile_id}")
            return

        try:
            store = self._mosaic_store_for_project(project_id, create_if_missing=False)
            tile_row = store.load_tile(project_id=project_id, tile_id=tile_id)
            if not tile_row:
                raise RuntimeError(f"Tile not found: {tile_id}")
            api_status = str(tile_row.get("api_status") or "").strip()
            if not is_completed_status(api_status):
                self._clear_mosaic_tracking_preview_layer_for_tile(tile_id=tile_id)
                preview_map = getattr(self, "_mosaic_tracking_preview_layer_ids", {})
                preview_ids = sorted(preview_map.keys()) if isinstance(preview_map, dict) else []
                if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
                    self.dock.set_mosaic_tracking_preview_tiles(preview_ids)
                self.dock.set_mosaic_tracking_status(
                    f"Mosaic preview unavailable: tile={tile_id} api_status={api_status or '--'} (requires Completed)."
                )
                return
            collection_id = str(tile_row.get("latest_collection_id") or "").strip()
            if not collection_id:
                raise RuntimeError(f"No latest collection id found for tile {tile_id}.")
            items = self._resolve_mosaic_tracking_preview_items(
                tile_row=tile_row,
                collection_id=collection_id,
            )
            self._clear_mosaic_tracking_preview_layer_for_tile(tile_id=tile_id)
            loaded_items = []
            for item in items:
                self._render_mosaic_tracking_preview_item(
                    project_id=project_id,
                    tile_id=tile_id,
                    item=item,
                )
                loaded_items.append(str(item.get("id") or "--").strip() or "--")
            if not loaded_items:
                raise RuntimeError("Preview imagery layer could not be loaded for any resolved item.")
            preview_map = getattr(self, "_mosaic_tracking_preview_layer_ids", {})
            preview_ids = sorted(preview_map.keys()) if isinstance(preview_map, dict) else []
            if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
                self.dock.set_mosaic_tracking_preview_tiles(preview_ids)
            first_item = loaded_items[0] if loaded_items else "--"
            self.dock.set_mosaic_tracking_status(
                f"Mosaic preview loaded: tile={tile_id}, items={len(loaded_items)}, first_item={first_item}."
            )
            self._log_mosaic(
                f"preview_loaded project={project_id} tile={tile_id} collection_id={collection_id} "
                f"items={len(loaded_items)} first_item={first_item}"
            )
        except Exception as exc:
            self._clear_mosaic_tracking_preview_layer_for_tile(tile_id=tile_id)
            preview_map = getattr(self, "_mosaic_tracking_preview_layer_ids", {})
            preview_ids = sorted(preview_map.keys()) if isinstance(preview_map, dict) else []
            if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
                self.dock.set_mosaic_tracking_preview_tiles(preview_ids)
            self.dock.set_mosaic_tracking_status(f"Mosaic preview failed: {exc}")
            self._log_mosaic(
                f"preview_failed project={project_id} tile={tile_id} error={exc}",
                level=Qgis.Warning,
            )

    def handle_mosaic_refresh_status_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        project_id = str(request.get("project_id") or "").strip()
        tile_id = str(request.get("tile_id") or "").strip()
        if not project_id and hasattr(self.dock, "current_mosaic_project_id"):
            project_id = str(self.dock.current_mosaic_project_id() or "").strip()
        if not project_id:
            self.dock.set_mosaic_tracking_status("Mosaic refresh skipped: select a project.")
            return
        source_id = self._mosaic_source_id()
        if source_id != "satellogic":
            self.dock.set_mosaic_tracking_status(
                "Mosaic refresh skipped: switch source to NewSat Constellation."
            )
            return
        try:
            store = self._mosaic_store_for_project(project_id, create_if_missing=False)
            contract_id = self._mosaic_resolved_contract_id()
            updates = self.mosaic_tasking_service.refresh_non_accepted_statuses(
                store=store,
                source_service=self.source_service,
                project_id=project_id,
                contract_id=contract_id,
                source_id=source_id,
                tile_ids=[tile_id] if tile_id else None,
                skip_failed=True,
            )
            self._load_mosaic_tracking_project(project_id)
            changed = sum(1 for row in updates if bool(row.get("changed")))
            errored = sum(1 for row in updates if str(row.get("error") or "").strip())
            skipped = sum(1 for row in updates if bool(row.get("skipped")))
            skipped_failed = sum(
                1
                for row in updates
                if bool(row.get("skipped"))
                and str(row.get("reason") or "").strip() == "terminal_failed"
            )
            skipped_canceled = sum(
                1
                for row in updates
                if bool(row.get("skipped"))
                and str(row.get("reason") or "").strip() == "terminal_canceled"
            )
            scope_text = f"tile={tile_id}" if tile_id else f"project={project_id}"
            self.dock.set_mosaic_tracking_status(
                f"Mosaic status refresh complete ({scope_text}): checked={len(updates)}, changed={changed}, "
                f"skipped={skipped} (failed={skipped_failed}, canceled={skipped_canceled}), errors={errored}."
            )
            self._log_mosaic(
                f"refresh_status_complete project={project_id} tile={tile_id or '--'} checked={len(updates)} "
                f"changed={changed} skipped={skipped} skipped_failed={skipped_failed} "
                f"skipped_canceled={skipped_canceled} errors={errored}"
            )
        except Exception as exc:
            self.dock.set_mosaic_tracking_status(f"Mosaic status refresh failed: {exc}")
            self._log_mosaic(
                f"refresh_status_failed project={project_id} tile={tile_id or '--'} error={exc}",
                level=Qgis.Warning,
            )

    def handle_mosaic_delete_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        project_id = str(request.get("project_id") or "").strip()
        if not project_id and hasattr(self.dock, "current_mosaic_project_id"):
            project_id = str(self.dock.current_mosaic_project_id() or "").strip()
        if not project_id:
            self.dock.set_mosaic_tracking_status("Mosaic delete skipped: select a project.")
            return
        try:
            campaign_uid = self._mosaic_campaign_uid()
            paths = self._mosaic_project_paths(project_id)
            # Release any in-project layers before deleting files on disk.
            self._clear_mosaic_tiling_layer()
            self._clear_mosaic_tracking_preview_layer()
            if hasattr(self.dock, "set_mosaic_tracking_preview_tiles"):
                self.dock.set_mosaic_tracking_preview_tiles([])
            released_layers = self._release_mosaic_project_layers(
                project_id=project_id,
                project_dir=paths["project_dir"],
                shapefile_path=paths["shapefile_path"],
            )
            if released_layers:
                self._log_mosaic(f"delete_release_layers project={project_id} removed={released_layers}")
            QCoreApplication.processEvents()
            gc.collect()
            def _on_lock_retry(attempt_no, _error):
                retried_removed = self._release_mosaic_project_layers(
                    project_id=project_id,
                    project_dir=paths["project_dir"],
                    shapefile_path=paths["shapefile_path"],
                )
                QCoreApplication.processEvents()
                gc.collect()
                self._log_mosaic(
                    f"delete_lock_retry project={project_id} attempt={attempt_no} released={retried_removed}",
                    level=Qgis.Warning,
                )

            deleted = self.campaign_storage.delete_mosaic_project(
                campaign_uid,
                project_id,
                max_attempts=12,
                on_lock_retry=_on_lock_retry,
            )
            if not deleted:
                self.dock.set_mosaic_tracking_status(f"Mosaic delete skipped: project not found ({project_id}).")
                self._log_mosaic(f"delete_skipped project={project_id} reason=not_found", level=Qgis.Warning)
                return
            self.handle_mosaic_refresh_projects_request()
            selected_project = (
                str(self.dock.current_mosaic_project_id() or "").strip()
                if hasattr(self.dock, "current_mosaic_project_id")
                else ""
            )
            if not selected_project:
                self.dock.set_mosaic_tracking_rows([])
            self.dock.set_mosaic_tracking_status(f"Mosaic deleted: {project_id}.")
            self._log_mosaic(f"delete_complete project={project_id}")
        except Exception as exc:
            self.dock.set_mosaic_tracking_status(f"Mosaic delete failed: {exc}")
            self._log_mosaic(
                f"delete_failed project={project_id} error={exc}",
                level=Qgis.Warning,
            )

    def handle_mosaic_show_tiling_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        enabled = bool(request.get("enabled", True))
        if not enabled:
            self._clear_mosaic_tiling_layer()
            self.dock.set_mosaic_tracking_status("Mosaic tiling hidden.")
            self._log_mosaic("show_tiling_disabled")
            return
        project_id = str(request.get("project_id") or "").strip()
        if not project_id and hasattr(self.dock, "current_mosaic_project_id"):
            project_id = str(self.dock.current_mosaic_project_id() or "").strip()
        if not project_id:
            self.dock.set_mosaic_tracking_status("Mosaic show tiling skipped: select a project.")
            return
        try:
            paths = self._mosaic_project_paths(project_id)
            self._show_mosaic_tiling_layer(project_id=project_id, shapefile_path=paths["shapefile_path"])
            self.dock.set_mosaic_tracking_status(f"Mosaic tiling shown: project={project_id}.")
            self._log_mosaic(f"show_tiling_complete project={project_id}")
        except Exception as exc:
            self.dock.set_mosaic_tracking_status(f"Mosaic show tiling failed: {exc}")
            self._log_mosaic(
                f"show_tiling_failed project={project_id} error={exc}",
                level=Qgis.Warning,
            )

    def handle_mosaic_mark_accepted_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        project_id = str(request.get("project_id") or "").strip()
        tile_id = str(request.get("tile_id") or "").strip()
        if not project_id or not tile_id:
            self.dock.set_mosaic_tracking_status("Mosaic mark accepted skipped: select project and tile.")
            return
        try:
            store = self._mosaic_store_for_project(project_id, create_if_missing=False)
            changed = store.mark_tile_accepted(
                project_id=project_id,
                tile_id=tile_id,
                accepted_by=default_operator_name(),
                mutation_source=MUTATION_SOURCE_ACCEPT,
                note="manual_accept",
            )
            self._load_mosaic_tracking_project(project_id)
            if changed:
                self.dock.set_mosaic_tracking_status(f"Mosaic tile accepted: {tile_id}.")
            else:
                self.dock.set_mosaic_tracking_status(f"Mosaic tile already accepted: {tile_id}.")
            self._log_mosaic(
                f"mark_accepted project={project_id} tile={tile_id} changed={bool(changed)}"
            )
        except Exception as exc:
            self.dock.set_mosaic_tracking_status(f"Mosaic mark accepted failed: {exc}")
            self._log_mosaic(
                f"mark_accepted_failed project={project_id} tile={tile_id} error={exc}",
                level=Qgis.Warning,
            )

    def handle_mosaic_retask_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        project_id = str(request.get("project_id") or "").strip()
        tile_id = str(request.get("tile_id") or "").strip()
        if not project_id or not tile_id:
            self.dock.set_mosaic_tracking_status("Mosaic re-task skipped: select project and tile.")
            return
        source_id = self._mosaic_source_id()
        if source_id != "satellogic":
            self.dock.set_mosaic_tracking_status(
                "Mosaic re-task skipped: switch source to NewSat Constellation."
            )
            return
        try:
            store = self._mosaic_store_for_project(project_id, create_if_missing=False)
            tile_row = store.load_tile(project_id=project_id, tile_id=tile_id)
            if not tile_row:
                raise RuntimeError(f"Tile not found: {tile_id}")
            qa_status = str(tile_row.get("qa_status") or "").strip()
            if qa_status.lower() == "accepted":
                self.dock.set_mosaic_tracking_status(
                    f"Mosaic re-task skipped: tile already accepted ({tile_id})."
                )
                return
            contract_id = self._mosaic_resolved_contract_id()
            result = self.mosaic_tasking_service.submit_single_tile(
                store=store,
                source_service=self.source_service,
                project_id=project_id,
                tile_id=tile_id,
                tile_row=tile_row,
                contract_id=contract_id,
                source_id=source_id,
                sku=TASKING_DEFAULT_SKU,
                mutation_source="retask",
            )
            self._load_mosaic_tracking_project(project_id)
            if str(result.get("attempt_status") or "").strip() == ATTEMPT_STATUS_SUBMITTED:
                self.dock.set_mosaic_tracking_status(
                    f"Mosaic re-task submitted: tile={tile_id}, collection_id={result.get('collection_id') or '--'}."
                )
            else:
                self.dock.set_mosaic_tracking_status(
                    f"Mosaic re-task failed: tile={tile_id}, error={result.get('error') or 'unknown'}."
                )
            self._log_mosaic(
                f"retask_result project={project_id} tile={tile_id} status={result.get('attempt_status')} "
                f"api_status={result.get('api_status')}"
            )
        except Exception as exc:
            self.dock.set_mosaic_tracking_status(f"Mosaic re-task failed: {exc}")
            self._log_mosaic(
                f"retask_failed project={project_id} tile={tile_id} error={exc}",
                level=Qgis.Warning,
            )

    def handle_mosaic_cancel_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        project_id = str(request.get("project_id") or "").strip()
        tile_id = str(request.get("tile_id") or "").strip()
        if not project_id or not tile_id:
            self.dock.set_mosaic_tracking_status("Mosaic cancel skipped: select project and tile.")
            return
        source_id = self._mosaic_source_id()
        if source_id != "satellogic":
            self.dock.set_mosaic_tracking_status(
                "Mosaic cancel skipped: switch source to NewSat Constellation."
            )
            return
        try:
            store = self._mosaic_store_for_project(project_id, create_if_missing=False)
            tile_row = store.load_tile(project_id=project_id, tile_id=tile_id)
            if not tile_row:
                raise RuntimeError(f"Tile not found: {tile_id}")
            qa_status = str(tile_row.get("qa_status") or "").strip().lower()
            if qa_status == "accepted":
                self.dock.set_mosaic_tracking_status(
                    f"Mosaic cancel skipped: tile already accepted ({tile_id})."
                )
                return
            collection_id = str(tile_row.get("latest_collection_id") or "").strip()
            if not collection_id:
                self.dock.set_mosaic_tracking_status(
                    f"Mosaic cancel skipped: no active collection id for tile {tile_id}."
                )
                return
            contract_id = self._mosaic_resolved_contract_id()
            detail = self.source_service.cancel_tasking_order(collection_id, contract_id=contract_id or None)
            order = detail.get("order") if isinstance(detail, dict) else None
            order = order if isinstance(order, dict) else {}
            api_status = str(order.get("status") or "cancelled").strip() or "cancelled"
            store.update_tile_api_status(
                project_id=project_id,
                tile_id=tile_id,
                api_status=api_status,
                mutation_source="cancel_tasking",
                note="manual_cancel",
            )
            self._load_mosaic_tracking_project(project_id)
            self.dock.set_mosaic_tracking_status(
                f"Mosaic tasking canceled: tile={tile_id}, collection_id={collection_id}, api_status={api_status}."
            )
            self._log_mosaic(
                f"cancel_tasking project={project_id} tile={tile_id} collection_id={collection_id} api_status={api_status}"
            )
        except Exception as exc:
            self.dock.set_mosaic_tracking_status(f"Mosaic cancel failed: {exc}")
            self._log_mosaic(
                f"cancel_tasking_failed project={project_id} tile={tile_id} error={exc}",
                level=Qgis.Warning,
            )

    def handle_mosaic_more_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        project_id = str(request.get("project_id") or "").strip()
        tile_id = str(request.get("tile_id") or "").strip()
        if not project_id or not tile_id:
            self.dock.set_mosaic_tracking_status("Mosaic detail skipped: select project and tile.")
            return
        source_id = self._mosaic_source_id()
        if source_id != "satellogic":
            self.dock.set_mosaic_tracking_status(
                "Mosaic detail skipped: switch source to NewSat Constellation."
            )
            return
        try:
            store = self._mosaic_store_for_project(project_id, create_if_missing=False)
            tile_row = store.load_tile(project_id=project_id, tile_id=tile_id)
            if not tile_row:
                raise RuntimeError(f"Tile not found: {tile_id}")
            collection_id = str(tile_row.get("latest_collection_id") or "").strip()
            if not collection_id:
                raise RuntimeError(f"No collection id available for tile {tile_id}.")
            contract_id = self._mosaic_resolved_contract_id()
            detail = self.source_service.get_tasking_order(collection_id, contract_id=contract_id or None)
            order = detail.get("order") if isinstance(detail, dict) else None
            raw = detail.get("raw") if isinstance(detail, dict) else None
            popup_payload = {
                "project_id": project_id,
                "tile_id": tile_id,
                "collection_id": collection_id,
                "source_id": source_id,
                "contract_id": str(contract_id or "").strip(),
                "fetched_at": utc_now_iso(),
                "order": order if isinstance(order, dict) else {},
                "raw": raw if isinstance(raw, dict) else (raw if raw is not None else {}),
            }
            if hasattr(self.dock, "show_mosaic_collection_api_detail_popup"):
                self.dock.show_mosaic_collection_api_detail_popup(popup_payload)
            self.dock.set_mosaic_tracking_status(
                f"Mosaic detail loaded: tile={tile_id}, collection_id={collection_id}."
            )
            self._log_mosaic(
                f"detail_loaded project={project_id} tile={tile_id} collection_id={collection_id}"
            )
        except Exception as exc:
            self.dock.set_mosaic_tracking_status(f"Mosaic detail failed: {exc}")
            self._log_mosaic(
                f"detail_failed project={project_id} tile={tile_id} error={exc}",
                level=Qgis.Warning,
            )

    def _selected_result_item(self):
        if self.dock is None:
            return None
        item_id = str(self.dock.current_result_item_id() or "").strip()
        if not item_id:
            return None
        return self.search_items.get(item_id)

    @staticmethod
    def _polygon_from_bounds(min_x, min_y, max_x, max_y):
        return {
            "type": "Polygon",
            "coordinates": [[
                [float(min_x), float(min_y)],
                [float(max_x), float(min_y)],
                [float(max_x), float(max_y)],
                [float(min_x), float(max_y)],
                [float(min_x), float(min_y)],
            ]],
        }

    def _selected_result_centroid_point(self):
        item = self._selected_result_item()
        if not isinstance(item, dict):
            raise RuntimeError("Select a search result first.")
        geometry = item.get("geometry")
        if not isinstance(geometry, dict):
            raise RuntimeError("Selected result does not include geometry.")
        qgeom = self._geometry_from_geojson(geometry)
        if qgeom is None or qgeom.isEmpty():
            raise RuntimeError("Selected result geometry is invalid.")
        centroid = qgeom.centroid()
        if centroid is None or centroid.isEmpty():
            raise RuntimeError("Selected result centroid could not be computed.")
        point = centroid.asPoint()
        return {"type": "Point", "coordinates": [float(point.x()), float(point.y())]}

    def _selected_result_area_geometry(self):
        item = self._selected_result_item()
        if not isinstance(item, dict):
            raise RuntimeError("Select a search result first.")
        geometry = item.get("geometry")
        if not isinstance(geometry, dict):
            raise RuntimeError("Selected result does not include geometry.")
        geom_type = str(geometry.get("type") or "").strip()
        if geom_type == "Polygon":
            return geometry
        qgeom = self._geometry_from_geojson(geometry)
        if qgeom is None or qgeom.isEmpty():
            raise RuntimeError("Selected result geometry is invalid.")
        rect = qgeom.boundingBox()
        if rect.isEmpty():
            raise RuntimeError("Selected result bounds are empty.")
        return self._polygon_from_bounds(rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())

    def _current_extent_point(self):
        extent_geometry = self._current_extent_geometry_wgs84()
        coords = extent_geometry.get("coordinates") if isinstance(extent_geometry, dict) else None
        ring = coords[0] if isinstance(coords, list) and coords else None
        if not isinstance(ring, list) or len(ring) < 4:
            raise RuntimeError("Map extent geometry is unavailable.")
        min_x = float(ring[0][0])
        min_y = float(ring[0][1])
        max_x = float(ring[2][0])
        max_y = float(ring[2][1])
        return {"type": "Point", "coordinates": [(min_x + max_x) / 2.0, (min_y + max_y) / 2.0]}

    def _resolve_tasking_geometry(self, *, target_type, geometry_mode):
        norm_target = str(target_type or "").strip().lower()
        norm_mode = str(geometry_mode or "").strip().lower()
        if norm_target == "point":
            if norm_mode == "selected_result_centroid":
                return self._selected_result_centroid_point()
            return self._current_extent_point()
        if norm_target == "area":
            if norm_mode == "selected_result_footprint":
                return self._selected_result_area_geometry()
            extent = self._current_extent_geometry_wgs84()
            if not isinstance(extent, dict):
                raise RuntimeError("Current map extent is unavailable.")
            return extent
        raise RuntimeError("Tasking target_type must be point or area")

    def _backend_json_request(self, path, *, method="GET", params=None, payload=None, timeout=20):
        base = self._backend_api_base_url().rstrip("/")
        suffix = str(path or "").strip()
        if not suffix.startswith("/"):
            suffix = f"/{suffix}"
        url = f"{base}{suffix}"
        if isinstance(params, dict) and params:
            encoded = urlencode(
                {k: v for k, v in params.items() if v is not None and str(v).strip() != ""},
                doseq=True,
            )
            if encoded:
                url = f"{url}?{encoded}"
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        req = Request(url=url, data=data, headers=headers, method=str(method or "GET").upper())
        retry_deadline = time.monotonic() + 3.0
        retry_attempt = 0
        while True:
            try:
                with urlopen(req, timeout=max(1, int(timeout or 20))) as resp:
                    body_bytes = resp.read() or b""
                if not body_bytes:
                    return {}
                body_text = body_bytes.decode("utf-8", errors="replace")
                parsed = json.loads(body_text)
                if isinstance(parsed, dict):
                    return parsed
                return {"value": parsed}
            except HTTPError as exc:
                detail = ""
                try:
                    body_bytes = exc.read() or b""
                    body_text = body_bytes.decode("utf-8", errors="replace").strip()
                    if body_text:
                        try:
                            body_json = json.loads(body_text)
                        except Exception:
                            body_json = None
                        if isinstance(body_json, dict):
                            detail = str(body_json.get("detail") or body_json)
                        else:
                            detail = body_text[:260]
                except Exception:
                    detail = ""
                prefix = f"{req.get_method()} {suffix} failed ({int(getattr(exc, 'code', 0) or 0)})"
                raise RuntimeError(f"{prefix}: {detail or exc.reason}") from exc
            except URLError as exc:
                reason = getattr(exc, "reason", exc)
                if self._is_connection_refused_error(reason) and time.monotonic() < retry_deadline:
                    # During plugin/backend reload the local API can come up a moment later.
                    retry_attempt += 1
                    time.sleep(min(0.6, 0.15 * (2 ** retry_attempt)))
                    continue
                raise RuntimeError(f"{req.get_method()} {suffix} failed: {reason}") from exc

    @staticmethod
    def _is_connection_refused_error(reason):
        if isinstance(reason, ConnectionRefusedError):
            return True
        win_error = getattr(reason, "winerror", None)
        try:
            if int(win_error or 0) == 10061:
                return True
        except Exception:
            pass
        errno = getattr(reason, "errno", None)
        try:
            if int(errno or 0) in (61, 111, 10061):
                return True
        except Exception:
            pass
        text = str(reason or "").strip().lower()
        if not text:
            return False
        return (
            "connection refused" in text
            or "actively refused" in text
            or "winerror 10061" in text
            or "errno 111" in text
        )

    def _resolve_monitoring_geometry(self, geometry_mode):
        mode = str(geometry_mode or "").strip().lower()
        if mode == "selected_result_footprint":
            return self._selected_result_area_geometry()
        extent = self._current_extent_geometry_wgs84()
        if not isinstance(extent, dict):
            raise RuntimeError("Current map extent is unavailable.")
        return extent

    @staticmethod
    def _event_geometry_candidate(event_row):
        if not isinstance(event_row, dict):
            return None
        for key in ("geometry", "aoi", "footprint"):
            value = event_row.get(key)
            if isinstance(value, dict):
                return value
        payload = event_row.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = None
        if isinstance(payload, dict):
            for key in ("geometry", "aoi", "footprint"):
                value = payload.get(key)
                if isinstance(value, dict):
                    return value
        return None

    def _resolve_cue_geometry(self, geometry_mode):
        mode = str(geometry_mode or "").strip().lower()
        if mode == "selected_result_footprint":
            return self._selected_result_area_geometry()
        if mode == "event_geometry" and self.dock is not None and hasattr(self.dock, "current_monitoring_event_row"):
            event_row = self.dock.current_monitoring_event_row()
            candidate = self._event_geometry_candidate(event_row)
            if isinstance(candidate, dict):
                return candidate
        extent = self._current_extent_geometry_wgs84()
        if not isinstance(extent, dict):
            raise RuntimeError("Current map extent is unavailable.")
        return extent

    @staticmethod
    def _is_backend_unreachable_error(exc):
        text = str(exc or "").strip().lower()
        if not text:
            return False
        return (
            "connection refused" in text
            or "actively refused" in text
            or "winerror 10061" in text
            or "errno 111" in text
            or "failed to establish a new connection" in text
            or "max retries exceeded" in text
        )

    def _set_monitoring_backend_unavailable(self, detail=""):
        if self.dock is None:
            return
        self.dock.set_monitoring_subscriptions([])
        self.dock.set_monitoring_events([])
        self.dock.set_monitoring_cues([])
        base = self._backend_api_base_url()
        self.dock.set_monitoring_status(
            f"Monitoring unavailable: backend API not reachable at {base} (plugin-only mode is OK)."
        )
        now = time.monotonic()
        last = float(getattr(self, "_monitoring_backend_notice_at", 0.0) or 0.0)
        if now - last >= 20.0:
            suffix = f" detail={detail}" if str(detail or "").strip() else ""
            self._append_search_log(
                f"Monitoring refresh skipped: backend API unreachable at {base}.{suffix}",
                level=Qgis.Info,
            )
            self._monitoring_backend_notice_at = now

    def handle_monitoring_refresh_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        source_filter = str(request.get("source_id") or "").strip().lower()
        status_filter = str(request.get("status") or "").strip()
        if not self._backend_streaming_available():
            self._set_monitoring_backend_unavailable(detail="health_check_failed")
            return
        try:
            self.dock.set_monitoring_status("Loading monitoring feed from backend...")
            subscriptions_resp = self._backend_json_request("/api/monitoring/subscriptions")
            events_resp = self._backend_json_request(
                "/api/monitoring/events",
                params={"limit": 200, "status": status_filter or None},
            )
            cues_resp = self._backend_json_request(
                "/api/cues",
                params={"limit": 200, "status": status_filter or None},
            )
            subscriptions = subscriptions_resp.get("subscriptions", []) if isinstance(subscriptions_resp, dict) else []
            events = events_resp.get("events", []) if isinstance(events_resp, dict) else []
            cues = cues_resp.get("cues", []) if isinstance(cues_resp, dict) else []
            if source_filter:
                subscriptions = [
                    row for row in subscriptions
                    if str(row.get("source_id") or "").strip().lower() == source_filter
                ]
                events = [
                    row for row in events
                    if str(row.get("source_id") or "").strip().lower() == source_filter
                ]
                cues = [
                    row for row in cues
                    if str(row.get("source_id") or "").strip().lower() == source_filter
                ]
            self.dock.set_monitoring_subscriptions(subscriptions)
            self.dock.set_monitoring_events(events)
            self.dock.set_monitoring_cues(cues)
            self.dock.set_monitoring_status(
                f"Monitoring ready: {len(subscriptions)} subscriptions, {len(events)} events, {len(cues)} cues."
            )
        except Exception as exc:
            if self._is_backend_unreachable_error(exc):
                self._set_monitoring_backend_unavailable(detail=str(exc))
                return
            self.dock.set_monitoring_status(f"Monitoring refresh failed: {exc}")
            self._append_search_log(f"Monitoring refresh failed: {exc}", level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Monitoring refresh failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )

    def handle_monitoring_create_subscription_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        try:
            geometry = self._resolve_monitoring_geometry(request.get("geometry_mode"))
            source_id = str(request.get("source_id") or "").strip()
            if not source_id:
                source_id = str(self.dock.monitoring_source_combo.currentData() or "").strip()
            if not source_id:
                source_id = str(self.dock.current_source_id() or "").strip()
            if not source_id:
                source_id = "merlin-s2"
            collection_ids = request.get("collection_ids")
            collection_ids = collection_ids if isinstance(collection_ids, list) else []
            filters = request.get("filters")
            filters = filters if isinstance(filters, dict) else {}
            normalized_collection_ids = [str(value or "").strip() for value in collection_ids if str(value or "").strip()]
            self._append_debug_log(
                "monitoring_subscription_create "
                f"source={source_id} collection_ids={','.join(normalized_collection_ids)} "
                f"filter_keys={','.join(sorted(str(k) for k in filters.keys())) if filters else ''}"
            )
            submit_payload = {
                "source_id": source_id,
                "name": str(request.get("name") or "").strip() or None,
                "collection_ids": normalized_collection_ids,
                "geometry": geometry,
                "filters": filters,
                "enabled": bool(request.get("enabled", True)),
            }
            created = self._backend_json_request(
                "/api/monitoring/subscriptions",
                method="POST",
                payload=submit_payload,
            )
            sub_id = str((created or {}).get("subscription_id") or (created or {}).get("id") or "").strip()
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Monitoring subscription created{f' ({sub_id})' if sub_id else ''}.",
                level=Qgis.Success,
                duration=8,
            )
            self.handle_monitoring_refresh_request(
                {"source_id": source_id, "status": str(self.dock.monitoring_status_filter_combo.currentData() or "").strip()}
            )
        except Exception as exc:
            self.dock.set_monitoring_status(f"Create subscription failed: {exc}")
            self._append_search_log(f"Create monitoring subscription failed: {exc}", level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Create subscription failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )

    def handle_monitoring_ack_event_request(self, event_id):
        if self.dock is None:
            return
        event_key = str(event_id or "").strip()
        if not event_key:
            return
        try:
            self._backend_json_request(
                f"/api/monitoring/events/{quote(event_key, safe='')}/ack",
                method="POST",
                payload={"status": "acked"},
            )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Monitoring event acknowledged ({event_key}).",
                level=Qgis.Success,
                duration=8,
            )
            self.handle_monitoring_refresh_request(
                {
                    "source_id": str(self.dock.monitoring_source_combo.currentData() or "").strip(),
                    "status": str(self.dock.monitoring_status_filter_combo.currentData() or "").strip(),
                }
            )
        except Exception as exc:
            self.dock.set_monitoring_status(f"Event ack failed: {exc}")
            self._append_search_log(f"Monitoring event ack failed: {exc}", level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Event ack failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )

    def handle_monitoring_create_cue_request(self, payload):
        if self.dock is None:
            return
        request = payload if isinstance(payload, dict) else {}
        event_id = str(request.get("event_id") or "").strip()
        if not event_id:
            return
        try:
            geometry = self._resolve_cue_geometry(request.get("geometry_mode"))
            source_id = str(request.get("source_id") or "").strip()
            if not source_id:
                source_id = str(self.dock.monitoring_source_combo.currentData() or "").strip()
            if not source_id:
                source_id = str(self.dock.current_source_id() or "").strip()
            if not source_id:
                source_id = "merlin-s2"
            self._append_debug_log(
                "monitoring_cue_create "
                f"source={source_id} event_id={event_id} priority={str(request.get('priority') or 'medium').strip() or 'medium'}"
            )
            submit_payload = {
                "event_id": event_id,
                "source_id": source_id,
                "status": str(request.get("status") or "queued_review").strip() or "queued_review",
                "priority": str(request.get("priority") or "medium").strip() or "medium",
                "geometry": geometry,
                "payload": {},
            }
            created = self._backend_json_request("/api/cues", method="POST", payload=submit_payload)
            cue_id = str((created or {}).get("cue_id") or (created or {}).get("id") or "").strip()
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Cue created{f' ({cue_id})' if cue_id else ''}.",
                level=Qgis.Success,
                duration=8,
            )
            self.handle_monitoring_refresh_request(
                {
                    "source_id": str(self.dock.monitoring_source_combo.currentData() or "").strip(),
                    "status": str(self.dock.monitoring_status_filter_combo.currentData() or "").strip(),
                }
            )
        except Exception as exc:
            self.dock.set_monitoring_status(f"Create cue failed: {exc}")
            self._append_search_log(f"Create cue failed: {exc}", level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Create cue failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
