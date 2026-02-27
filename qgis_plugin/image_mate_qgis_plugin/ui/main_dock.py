# -*- coding: utf-8 -*-
"""Main dock widget for Image Mate."""

import json
from datetime import datetime, timezone
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QDate
from qgis.PyQt.QtCore import QDateTime
from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtCore import QStringListModel
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QGraphicsScene,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QGroupBox,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsProject
from qgis.core import QgsRasterLayer
from qgis.core import QgsVectorLayer
from qgis.core import QgsWkbTypes

from ..services.resample_workflows import (
    RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M,
    RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M,
    RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M,
)
from ..services.asset_intel_service import normalize_domain_hierarchy
from ..services.mosaic_preview_resolution import should_enable_preview
from ..services.simulation_day_navigation import navigation_button_state
from ..workflow_plugins.manager import WorkflowPluginManager
from .main_dock_workflow import WorkflowDockMixin


class ImageMateMainDock(WorkflowDockMixin, QDockWidget):
    validate_requested = pyqtSignal()
    settings_saved = pyqtSignal()
    campaign_apply_requested = pyqtSignal(dict)
    search_requested = pyqtSignal(dict)
    download_selected_requested = pyqtSignal(dict)
    result_selected = pyqtSignal(str)
    location_jump_requested = pyqtSignal(str)
    location_suggestions_requested = pyqtSignal(str)
    execute_workflow_requested = pyqtSignal(dict)
    create_vrt_requested = pyqtSignal(dict)
    sharpen_image_requested = pyqtSignal(dict)
    resample_image_10m_requested = pyqtSignal(dict)
    resample_image_10p8_to_3m_requested = pyqtSignal(dict)
    resample_image_2m_to_1m_requested = pyqtSignal(dict)
    resample_image_3p76m_to_1m_requested = pyqtSignal(dict)
    vessel_detect_requested = pyqtSignal(dict)
    vessel_detect_extent_requested = pyqtSignal(dict)
    vessel_qa_layer_create_requested = pyqtSignal(dict)
    vessel_qa_status_set_requested = pyqtSignal(dict)
    vessel_qa_finalize_requested = pyqtSignal(dict)
    tasking_refresh_requested = pyqtSignal()
    tasking_submit_requested = pyqtSignal(dict)
    tasking_order_selected = pyqtSignal(str)
    mosaic_breakdown_requested = pyqtSignal(dict)
    mosaic_accept_requested = pyqtSignal(dict)
    mosaic_tracking_project_changed = pyqtSignal(str)
    mosaic_tracking_tile_selected = pyqtSignal(dict)
    mosaic_tracking_preview_toggled = pyqtSignal(dict)
    mosaic_refresh_status_requested = pyqtSignal(dict)
    mosaic_delete_requested = pyqtSignal(dict)
    mosaic_show_tiling_requested = pyqtSignal(dict)
    mosaic_mark_accepted_requested = pyqtSignal(dict)
    mosaic_retask_requested = pyqtSignal(dict)
    mosaic_cancel_requested = pyqtSignal(dict)
    mosaic_refresh_projects_requested = pyqtSignal()
    monitoring_refresh_requested = pyqtSignal(dict)
    monitoring_create_subscription_requested = pyqtSignal(dict)
    monitoring_ack_event_requested = pyqtSignal(str)
    monitoring_create_cue_requested = pyqtSignal(dict)
    simulation_config_changed = pyqtSignal(dict)
    simulation_start_requested = pyqtSignal(dict)
    simulation_cancel_requested = pyqtSignal()
    simulation_first_day_requested = pyqtSignal()
    simulation_prev_30_days_requested = pyqtSignal()
    simulation_prev_day_requested = pyqtSignal()
    simulation_next_day_requested = pyqtSignal()
    simulation_next_30_days_requested = pyqtSignal()
    simulation_last_day_requested = pyqtSignal()
    simulation_pick_target_requested = pyqtSignal()
    simulation_scenario_changed = pyqtSignal(str)
    asset_intel_search_requested = pyqtSignal(dict)
    asset_intel_asset_selected = pyqtSignal(str)
    asset_intel_polygon_size_from_selection_requested = pyqtSignal()
    asset_intel_create_requested = pyqtSignal(dict)
    asset_intel_update_requested = pyqtSignal(dict)
    asset_intel_delete_requested = pyqtSignal(str)
    asset_intel_note_create_requested = pyqtSignal(dict)
    asset_intel_note_update_requested = pyqtSignal(dict)
    asset_intel_note_delete_requested = pyqtSignal(int)
    asset_intel_structure_mutation_requested = pyqtSignal(dict)
    ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK = "for_each_image_in_stack"
    ADAPTER_NAME_FOR_EACH_IMAGE_IN_STACK = "For Each Image in Stack"

    def __init__(self, parent=None):
        super().__init__("ISR Mission Workbench", parent)
        self.setObjectName("imageMateMainDock")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.setMinimumWidth(0)
        self.setMinimumSize(0, 0)

        self._result_rows = []
        self._checked_result_ids = set()
        self._workflow_scene = QGraphicsScene(self)
        self._workflow_nodes = {}
        self._workflow_edges = []
        self._workflow_node_seq = 0
        self._workflow_connect_mode_active = False
        self._workflow_connect_source_node_id = ""
        self._workflow_canvas_locked = False
        self._workflow_plugin_manager = WorkflowPluginManager()
        self._workflow_function_specs = self._workflow_plugin_manager.specs()
        self._tasking_products = []
        self._tasking_orders = []
        self._tasking_selected_order_id = ""
        self._mosaic_breakdown_rows = []
        self._mosaic_tracking_rows = []
        self._mosaic_tracking_selection_guard = False
        self._mosaic_tracking_preview_guard = False
        self._mosaic_tracking_preview_tile_id = ""
        self._campaign_root_path = ""
        self._monitoring_subscriptions = []
        self._monitoring_events = []
        self._monitoring_cues = []
        self._simulation_constellation_config = {
            "schema_version": 1,
            "constellation_name": "default",
            "satellites": [
                {
                    "satellite_id": "SIM-SSO-475",
                    "name": "Simulation SSO 475km",
                    "priority": 1,
                    "enabled": True,
                    "swath_width_km": 6.5,
                    "tle": {
                        "line1": "1 99999U 26001A   26052.00000000  .00000010  00000+0  10000-3 0  9993",
                        "line2": "2 99999  97.4000 120.0000 0010000  90.0000   0.0000 15.31900000    09",
                    },
                }
            ],
        }
        self._simulation_manual_selected_ids = set()
        self._simulation_target_point = {"lat": None, "lon": None, "source": "manual", "label": ""}
        self._asset_intel_result_rows = []
        self._asset_intel_current_detail = {}
        self._asset_intel_system_rows = []
        self._asset_intel_unit_rows = []
        self._asset_intel_visible_unit_rows = []
        self._asset_intel_note_rows = []
        self._asset_intel_selected_system_id = None
        self._asset_intel_selected_unit_id = None
        self._asset_intel_selected_note_id = None
        self._asset_intel_facet_rows = {}
        self._asset_intel_type_facet_rows = []
        self._asset_intel_type_rows_by_sub_domain_2 = {}
        self._download_task_row_by_id = {}

        root = QWidget(self)
        root.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        root.setMinimumWidth(0)
        root.setMinimumSize(0, 0)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QLabel("ISR Mission Workbench")
        header.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header.setStyleSheet("font-weight: 600; font-size: 14px;")
        header.setWordWrap(True)
        subtitle = QLabel("Operational Prototype")
        subtitle.setTextInteractionFlags(Qt.TextSelectableByMouse)
        subtitle.setWordWrap(True)

        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.tabs.addTab(self._build_campaigns_tab(), "Campaigns")
        self.tabs.addTab(self._build_explore_tab(), "Collection Search")
        self.tabs.addTab(self._build_asset_intel_tab(), "Asset Intel")
        self.tabs.addTab(self._build_tasking_tab(), "Collection Requests")
        self.tabs.addTab(self._build_monitoring_tab(), "Watch & Alerts")
        self.tabs.addTab(self._build_simulation_tab(), "Simulation")
        self.tabs.addTab(self._build_workflow_tab(), "Exploitation")
        self.tabs.addTab(self._build_utilities_tab(), "Geoprocessing")
        self.tabs.addTab(self._build_status_tab(), "Ops Health")
        self._settings_tab_index = self.tabs.addTab(self._build_settings_tab(), "Integrations")
        self.tabs.tabBar().hide()

        self._main_tab_button_group = QButtonGroup(self)
        self._main_tab_button_group.setExclusive(True)
        self.main_tab_nav = QWidget()
        self.main_tab_nav.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.main_tab_nav_layout = QGridLayout(self.main_tab_nav)
        self.main_tab_nav_layout.setContentsMargins(0, 0, 0, 0)
        self.main_tab_nav_layout.setHorizontalSpacing(6)
        self.main_tab_nav_layout.setVerticalSpacing(4)
        self._build_main_tab_buttons()
        self.tabs.currentChanged.connect(self._sync_main_tab_button_selection)

        layout.addWidget(header)
        layout.addWidget(subtitle)
        layout.addWidget(self.main_tab_nav)
        layout.addWidget(self.tabs, 1)

        self._scroll_container = QScrollArea(self)
        self._scroll_container.setWidgetResizable(True)
        self._scroll_container.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll_container.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll_container.setWidget(root)
        self.setWidget(self._scroll_container)
        self._refresh_workflow_source_options()
        self._on_workflow_source_mode_changed()
        self._refresh_workflow_function_options()
        self._set_workflow_hint(
            "Tip: add a source node, then double-click it to select current-search imagery."
        )

    def minimumSizeHint(self):
        return QSize(120, 200)

    def sizeHint(self):
        return QSize(420, 640)

    def _build_main_tab_buttons(self):
        while self.main_tab_nav_layout.count():
            item = self.main_tab_nav_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        old_buttons = list(self._main_tab_button_group.buttons())
        for button in old_buttons:
            self._main_tab_button_group.removeButton(button)

        tab_count = self.tabs.count()
        if tab_count <= 0:
            return
        cols = max(1, (tab_count + 1) // 2)
        for index in range(tab_count):
            label = self.tabs.tabText(index)
            button = QPushButton(label)
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setMinimumHeight(28)
            button.setStyleSheet(
                "QPushButton { text-align: center; border: 1px solid #8896a6; border-radius: 4px; padding: 4px 8px; }"
                "QPushButton:checked { background: #d9e4f1; font-weight: 600; }"
            )
            button.clicked.connect(lambda _checked, idx=index: self.tabs.setCurrentIndex(idx))
            self._main_tab_button_group.addButton(button, index)
            row = 0 if index < cols else 1
            col = index if index < cols else index - cols
            self.main_tab_nav_layout.addWidget(button, row, col)

        self._sync_main_tab_button_selection(self.tabs.currentIndex())

    def _sync_main_tab_button_selection(self, current_index):
        try:
            selected = int(current_index)
        except Exception:
            selected = 0
        button = self._main_tab_button_group.button(selected)
        if button is not None:
            button.setChecked(True)

    def _focus_settings_tab(self):
        self.tabs.setCurrentIndex(self._settings_tab_index)

    def set_runtime_summary(self, summary_text):
        self.runtime_summary.setText(summary_text)

    def set_stream_status(self, status_text):
        self.stream_status.setText(str(status_text or "").strip() or "Stream status: idle")

    def set_sources(self, rows):
        prior = self.source_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        monitoring_prior = ""
        if hasattr(self, "monitoring_source_combo"):
            monitoring_prior = str(self.monitoring_source_combo.currentData() or "").strip()
            self.monitoring_source_combo.blockSignals(True)
            self.monitoring_source_combo.clear()
        for row in rows:
            label = row.get("title") or row.get("source_id") or "unknown"
            source_id = row.get("source_id") or ""
            enabled = bool(row.get("enabled"))
            if not enabled:
                label = f"{label} (disabled)"
            self.source_combo.addItem(label, source_id)
            if hasattr(self, "monitoring_source_combo"):
                self.monitoring_source_combo.addItem(label, source_id)
                mon_item = self.monitoring_source_combo.model().item(self.monitoring_source_combo.count() - 1)
                if mon_item is not None:
                    mon_item.setEnabled(enabled)
            model_item = self.source_combo.model().item(self.source_combo.count() - 1)
            if model_item is not None:
                model_item.setEnabled(enabled)
        if prior:
            idx = self.source_combo.findData(prior)
            if idx >= 0:
                self.source_combo.setCurrentIndex(idx)
        if hasattr(self, "monitoring_source_combo"):
            if monitoring_prior:
                mon_idx = self.monitoring_source_combo.findData(monitoring_prior)
                if mon_idx >= 0:
                    self.monitoring_source_combo.setCurrentIndex(mon_idx)
            self.monitoring_source_combo.blockSignals(False)
        self.source_combo.blockSignals(False)

    def set_collections(self, rows):
        prior = self.collection_combo.currentData()
        self.collection_combo.clear()
        for row in rows:
            label = row.get("title") or row.get("id") or "unknown"
            collection_id = row.get("id") or ""
            self.collection_combo.addItem(label, collection_id)
        if prior:
            idx = self.collection_combo.findData(prior)
            if idx >= 0:
                self.collection_combo.setCurrentIndex(idx)

    def set_default_dates(self, start_iso, end_iso):
        start = QDate.fromString(str(start_iso or ""), "yyyy-MM-dd")
        end = QDate.fromString(str(end_iso or ""), "yyyy-MM-dd")
        if start.isValid():
            self.start_date.setDate(start)
        if end.isValid():
            self.end_date.setDate(end)

    def append_search_log(self, text):
        self.search_log.append(text)

    def append_debug_log(self, text):
        self.debug_log.append(text)

    def set_search_enabled(self, enabled):
        self.search_btn.setEnabled(bool(enabled))
        if hasattr(self, "download_selected_btn"):
            if not bool(enabled):
                self.download_selected_btn.setEnabled(False)
            else:
                self._refresh_download_selected_button_state()

    def set_download_selected_enabled(self, enabled):
        if hasattr(self, "download_selected_btn"):
            self.download_selected_btn.setEnabled(bool(enabled))

    def set_download_monitor_progress(self, progress_pct, status_text=""):
        if hasattr(self, "download_progress_bar"):
            try:
                value = int(round(float(progress_pct)))
            except Exception:
                value = 0
            value = max(0, min(100, value))
            self.download_progress_bar.setValue(value)
        if hasattr(self, "download_progress_label"):
            text = str(status_text or "").strip()
            self.download_progress_label.setText(text or "Download monitor: idle")

    def upsert_download_task_status(self, task_id, payload):
        if not hasattr(self, "download_tasks_table"):
            return
        key = str(task_id or "").strip()
        if not key:
            return
        row_payload = payload if isinstance(payload, dict) else {}
        table = self.download_tasks_table
        row_idx = self._download_task_row_by_id.get(key)
        if row_idx is None:
            row_idx = int(table.rowCount())
            table.insertRow(row_idx)
            self._download_task_row_by_id[key] = row_idx

        progress_value = row_payload.get("progress_pct")
        try:
            progress_text = f"{float(progress_value):.1f}%"
        except Exception:
            progress_text = "--"

        values = [
            key,
            str(row_payload.get("status") or "--"),
            progress_text,
            str(row_payload.get("groups_total") if row_payload.get("groups_total") is not None else "--"),
            str(row_payload.get("items_total") if row_payload.get("items_total") is not None else "--"),
            str(row_payload.get("downloaded_files") if row_payload.get("downloaded_files") is not None else "--"),
            str(row_payload.get("started_utc") or "--"),
            str(row_payload.get("updated_utc") or "--"),
            str(row_payload.get("note") or ""),
        ]
        for col_idx, text in enumerate(values):
            item = table.item(row_idx, col_idx)
            if item is None:
                item = QTableWidgetItem("")
                table.setItem(row_idx, col_idx, item)
            item.setText(str(text))

    def load_settings(self, cfg):
        self.backend_api_base_url.setText(cfg.backend_api_base_url)
        self.sat_auth_mode.setCurrentText(cfg.satellogic_auth_mode)
        self.sat_contract.setText(cfg.satellogic_contract_id)
        self.sat_stac_url.setText(cfg.satellogic_stac_url)
        self.sat_authcfg_id.setText(cfg.satellogic_authcfg_id)

        self.cdse_enabled.setChecked(bool(cfg.cdse_enabled))
        self.cdse_stac_url.setText(cfg.cdse_stac_url)
        self.cdse_client_id.setText(str(getattr(cfg, "cdse_client_id", "") or ""))
        self.cdse_client_secret.setText(str(getattr(cfg, "cdse_client_secret", "") or ""))
        self.cdse_wmts_base_url.setText(cfg.cdse_wmts_base_url)
        self.cdse_wmts_instance_id.setText(cfg.cdse_wmts_instance_id)
        self.cdse_wmts_layer_id.setText(cfg.cdse_wmts_layer_id)
        self.cdse_wmts_use_backend_proxy.setChecked(bool(getattr(cfg, "cdse_wmts_use_backend_proxy", True)))
        self.cdse_authcfg_id.setText(cfg.cdse_authcfg_id)
        if hasattr(self, "asset_intel_db_path"):
            self.asset_intel_db_path.setText(str(cfg.asset_intel_db_path or "").strip())
        if hasattr(self, "vessel_model_default_path"):
            self.vessel_model_default_path.setText(str(cfg.vessel_model_default_path or "").strip())
        if hasattr(self, "vessel_conf_default"):
            self.vessel_conf_default.setValue(float(cfg.vessel_conf_threshold_default or 0.25))
        if hasattr(self, "vessel_iou_default"):
            self.vessel_iou_default.setValue(float(cfg.vessel_iou_threshold_default or 0.45))
        if hasattr(self, "vessel_max_det_default"):
            self.vessel_max_det_default.setValue(int(cfg.vessel_max_detections_default or 20))
        if hasattr(self, "campaign_managed_storage"):
            self.campaign_managed_storage.setChecked(bool(cfg.campaign_managed_storage))
        if hasattr(self, "campaign_base_dir"):
            self.campaign_base_dir.setText(str(cfg.campaign_base_dir or "").strip())
        if hasattr(self, "campaign_uid_input"):
            self.campaign_uid_input.setText(str(cfg.campaign_uid or "").strip())
        if hasattr(self, "campaign_name_input"):
            self.campaign_name_input.setText(str(cfg.campaign_name or "").strip())
        self._refresh_campaign_summary()

    def apply_settings_to(self, cfg):
        cfg.backend_api_base_url = self.backend_api_base_url.text().strip() or "http://localhost:8000"
        cfg.satellogic_auth_mode = self.sat_auth_mode.currentText().strip()
        cfg.satellogic_contract_id = self.sat_contract.text().strip()
        cfg.satellogic_stac_url = self.sat_stac_url.text().strip()
        cfg.satellogic_authcfg_id = self.sat_authcfg_id.text().strip()

        cfg.cdse_enabled = bool(self.cdse_enabled.isChecked())
        cfg.cdse_stac_url = self.cdse_stac_url.text().strip()
        cfg.cdse_client_id = self.cdse_client_id.text().strip()
        cfg.cdse_client_secret = self.cdse_client_secret.text().strip()
        cfg.cdse_wmts_base_url = self.cdse_wmts_base_url.text().strip()
        cfg.cdse_wmts_instance_id = self.cdse_wmts_instance_id.text().strip()
        cfg.cdse_wmts_layer_id = self.cdse_wmts_layer_id.text().strip() or "TRUE-COLOR"
        cfg.cdse_wmts_use_backend_proxy = bool(self.cdse_wmts_use_backend_proxy.isChecked())
        cfg.cdse_authcfg_id = self.cdse_authcfg_id.text().strip()
        if hasattr(self, "asset_intel_db_path"):
            cfg.asset_intel_db_path = self.asset_intel_db_path.text().strip()
        if hasattr(self, "vessel_model_default_path"):
            cfg.vessel_model_default_path = self.vessel_model_default_path.text().strip()
        if hasattr(self, "vessel_conf_default"):
            cfg.vessel_conf_threshold_default = float(self.vessel_conf_default.value())
        if hasattr(self, "vessel_iou_default"):
            cfg.vessel_iou_threshold_default = float(self.vessel_iou_default.value())
        if hasattr(self, "vessel_max_det_default"):
            cfg.vessel_max_detections_default = int(self.vessel_max_det_default.value())
        if hasattr(self, "campaign_managed_storage"):
            cfg.campaign_managed_storage = bool(self.campaign_managed_storage.isChecked())
        if hasattr(self, "campaign_base_dir"):
            cfg.campaign_base_dir = self.campaign_base_dir.text().strip()
        if hasattr(self, "campaign_uid_input"):
            cfg.campaign_uid = self.campaign_uid_input.text().strip()
        if hasattr(self, "campaign_name_input"):
            cfg.campaign_name = self.campaign_name_input.text().strip()
        return cfg

    def set_campaign_context(self, context):
        ctx = context if isinstance(context, dict) else {}
        self._campaign_root_path = str(ctx.get("campaign_root") or "").strip()
        if hasattr(self, "campaign_managed_storage"):
            self.campaign_managed_storage.setChecked(bool(ctx.get("managed_storage")))
        if hasattr(self, "campaign_base_dir"):
            self.campaign_base_dir.setText(str(ctx.get("base_dir") or "").strip())
        if hasattr(self, "campaign_uid_input"):
            self.campaign_uid_input.setText(str(ctx.get("campaign_uid") or "").strip())
        if hasattr(self, "campaign_name_input"):
            self.campaign_name_input.setText(str(ctx.get("campaign_name") or "").strip())
        if hasattr(self, "campaign_existing_combo"):
            current_uid = str(ctx.get("campaign_uid") or "").strip()
            campaigns = ctx.get("existing_campaigns") if isinstance(ctx.get("existing_campaigns"), list) else []
            self.campaign_existing_combo.blockSignals(True)
            self.campaign_existing_combo.clear()
            self.campaign_existing_combo.addItem("Select Existing Campaign...", "")
            target_index = 0
            for row in campaigns:
                if not isinstance(row, dict):
                    continue
                uid = str(row.get("uid") or "").strip()
                if not uid:
                    continue
                name = str(row.get("name") or "").strip() or uid
                label = name if name.lower() == uid.lower() else f"{name} ({uid})"
                self.campaign_existing_combo.addItem(label, uid)
                index = self.campaign_existing_combo.count() - 1
                self.campaign_existing_combo.setItemData(index, name, Qt.UserRole + 1)
                if current_uid and uid == current_uid:
                    target_index = index
            self.campaign_existing_combo.setCurrentIndex(target_index)
            self.campaign_existing_combo.blockSignals(False)
        if hasattr(self, "campaign_summary"):
            summary_lines = [
                f"Managed storage: {'enabled' if bool(ctx.get('managed_storage')) else 'disabled'}",
                f"Base directory: {str(ctx.get('base_dir') or '').strip() or '(not set)'}",
                f"Campaign UID: {str(ctx.get('campaign_uid') or '').strip() or '(auto)'}",
                f"Campaign name: {str(ctx.get('campaign_name') or '').strip() or '(none)'}",
                f"Campaign root: {str(ctx.get('campaign_root') or '').strip() or '(unavailable)'}",
                f"Campaign project: {str(ctx.get('project_path') or '').strip() or '(unavailable)'}",
            ]
            campaigns = ctx.get("existing_campaigns") if isinstance(ctx.get("existing_campaigns"), list) else []
            summary_lines.append(f"Existing campaigns: {len(campaigns)}")
            self.campaign_summary.setPlainText("\n".join(summary_lines))
        self._refresh_campaign_folder_button_state()

    def _refresh_campaign_summary(self):
        if not hasattr(self, "campaign_summary"):
            return
        managed = bool(self.campaign_managed_storage.isChecked()) if hasattr(self, "campaign_managed_storage") else False
        base_dir = self.campaign_base_dir.text().strip() if hasattr(self, "campaign_base_dir") else ""
        uid = self.campaign_uid_input.text().strip() if hasattr(self, "campaign_uid_input") else ""
        name = self.campaign_name_input.text().strip() if hasattr(self, "campaign_name_input") else ""
        lines = [
            f"Managed storage: {'enabled' if managed else 'disabled'}",
            f"Base directory: {base_dir or '(not set)'}",
            f"Campaign UID: {uid or '(auto)'}",
            f"Campaign name: {name or '(none)'}",
        ]
        self.campaign_summary.setPlainText("\n".join(lines))
        self._refresh_campaign_folder_button_state()

    def _browse_campaign_base_dir(self):
        current = self.campaign_base_dir.text().strip() if hasattr(self, "campaign_base_dir") else ""
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Campaign Base Directory",
            current,
        )
        selected_dir = str(selected_dir or "").strip()
        if not selected_dir:
            return
        self.campaign_base_dir.setText(selected_dir)
        self._refresh_campaign_summary()

    def _refresh_campaign_folder_button_state(self):
        if not hasattr(self, "campaign_open_folder_btn"):
            return
        root = str(getattr(self, "_campaign_root_path", "") or "").strip()
        base_dir = self.campaign_base_dir.text().strip() if hasattr(self, "campaign_base_dir") else ""
        uid = self.campaign_uid_input.text().strip() if hasattr(self, "campaign_uid_input") else ""
        has_candidate = bool(root or (base_dir and uid) or base_dir)
        self.campaign_open_folder_btn.setEnabled(has_candidate)

    def _open_campaign_folder(self):
        candidates = []
        root = str(getattr(self, "_campaign_root_path", "") or "").strip()
        if root:
            candidates.append(root)

        base_dir = self.campaign_base_dir.text().strip() if hasattr(self, "campaign_base_dir") else ""
        uid = self.campaign_uid_input.text().strip() if hasattr(self, "campaign_uid_input") else ""
        if base_dir and uid:
            candidates.append(str((Path(base_dir).expanduser() / uid)))
        if base_dir:
            candidates.append(base_dir)

        for candidate in candidates:
            try:
                path_obj = Path(candidate).expanduser().resolve()
            except Exception:
                path_obj = Path(candidate).expanduser()
            if not path_obj.exists():
                continue
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path_obj)))
            if not opened:
                QMessageBox.warning(
                    self,
                    "Campaign",
                    f"Failed to open folder:\n{path_obj}",
                )
            return

        QMessageBox.warning(
            self,
            "Campaign",
            "Campaign folder is not available yet. Apply or create campaign context first.",
        )

    def _browse_asset_intel_db_file(self):
        current = self.asset_intel_db_path.text().strip() if hasattr(self, "asset_intel_db_path") else ""
        file_path, _filter = QFileDialog.getOpenFileName(
            self,
            "Select Asset Intel SQLite Database",
            current,
            "SQLite Database (*.sqlite *.sqlite3 *.db);;All Files (*)",
        )
        file_path = str(file_path or "").strip()
        if not file_path:
            return
        self.asset_intel_db_path.setText(file_path)

    def _browse_vessel_model_file(self):
        current = self.vessel_model_default_path.text().strip() if hasattr(self, "vessel_model_default_path") else ""
        file_path, _filter = QFileDialog.getOpenFileName(
            self,
            "Select Vessel ONNX Model",
            current,
            "ONNX Model (*.onnx);;All Files (*)",
        )
        file_path = str(file_path or "").strip()
        if not file_path:
            return
        self.vessel_model_default_path.setText(file_path)

    def _on_campaign_existing_selected(self):
        if not hasattr(self, "campaign_existing_combo"):
            return
        selected_uid = str(self.campaign_existing_combo.currentData() or "").strip()
        if not selected_uid:
            return
        if hasattr(self, "campaign_uid_input"):
            self.campaign_uid_input.setText(selected_uid)
        if hasattr(self, "campaign_name_input"):
            name_value = str(self.campaign_existing_combo.currentData(Qt.UserRole + 1) or "").strip()
            if not name_value:
                label = str(self.campaign_existing_combo.currentText() or "").strip()
                name_value = label
                if label.endswith(f"({selected_uid})"):
                    name_value = label[: -(len(selected_uid) + 2)].strip()
            if name_value:
                self.campaign_name_input.setText(name_value)
        self._refresh_campaign_summary()

    def _emit_campaign_apply_request(self):
        payload = {
            "managed_storage": bool(self.campaign_managed_storage.isChecked()) if hasattr(self, "campaign_managed_storage") else True,
            "base_dir": self.campaign_base_dir.text().strip() if hasattr(self, "campaign_base_dir") else "",
            "campaign_uid": self.campaign_uid_input.text().strip() if hasattr(self, "campaign_uid_input") else "",
            "campaign_name": self.campaign_name_input.text().strip() if hasattr(self, "campaign_name_input") else "",
            "create_new": False,
        }
        self.campaign_apply_requested.emit(payload)

    def _emit_campaign_create_request(self):
        campaign_name = self.campaign_name_input.text().strip() if hasattr(self, "campaign_name_input") else ""
        campaign_uid = self.campaign_uid_input.text().strip() if hasattr(self, "campaign_uid_input") else ""
        if not campaign_name and not campaign_uid:
            campaign_name = datetime.now(tz=timezone.utc).strftime("New Campaign %Y-%m-%d %H:%M UTC")
            if hasattr(self, "campaign_name_input"):
                self.campaign_name_input.setText(campaign_name)
        payload = {
            "managed_storage": bool(self.campaign_managed_storage.isChecked()) if hasattr(self, "campaign_managed_storage") else True,
            "base_dir": self.campaign_base_dir.text().strip() if hasattr(self, "campaign_base_dir") else "",
            "campaign_uid": campaign_uid,
            "campaign_name": campaign_name,
            "create_new": True,
        }
        self.campaign_apply_requested.emit(payload)

    def set_contract_id(self, contract_id):
        self.contract_id.setText(str(contract_id or "").strip())

    def set_contract_enabled(self, enabled):
        self.contract_id.setEnabled(bool(enabled))

    def current_checked_stack_ids(self):
        ordered = []
        for row in self._result_rows:
            item_id = str(row.get("item_id") or "").strip()
            if item_id and item_id in self._checked_result_ids:
                ordered.append(item_id)
        return ordered

    def current_download_selected_payload(self):
        selected_item_ids = list(self.current_checked_stack_ids() or [])
        if not selected_item_ids:
            current_id = self.current_result_item_id()
            if current_id:
                selected_item_ids = [current_id]

        by_item_id = {}
        for row in self._result_rows:
            item_id = str(row.get("item_id") or "").strip()
            if item_id:
                by_item_id[item_id] = row

        groups = []
        for item_id in selected_item_ids:
            key = str(item_id or "").strip()
            if not key:
                continue
            row = by_item_id.get(key) or {}
            outcome_id = str(row.get("outcome_id") or "").strip()
            group_item_ids = []
            for group_id in row.get("group_item_ids") or []:
                group_key = str(group_id or "").strip()
                if group_key and group_key not in group_item_ids:
                    group_item_ids.append(group_key)
            if key and key not in group_item_ids:
                group_item_ids.insert(0, key)
            groups.append(
                {
                    "item_id": key,
                    "outcome_id": outcome_id,
                    "group_item_ids": group_item_ids,
                }
            )

        return {"groups": groups}

    def set_results(self, items):
        self.results_list.blockSignals(True)
        self.results_list.clear()
        self._result_rows = []
        self._checked_result_ids.clear()

        # Group items by outcome_id for multi-tile collections.
        groups = {}
        groupable_collections = {"l1d-sr", "l1d", "quickview-visual", "quickview-toa", "l1c"}
        for row in items or []:
            outcome_id = str(row.get("outcome_id") or "").strip()
            collection = str(row.get("collection") or "").strip().lower().replace("_", "-")

            # Group multi-tile collections by outcome_id, others individually.
            if collection in groupable_collections and outcome_id:
                group_key = f"outcome:{outcome_id}"
            else:
                group_key = str(row.get("id") or "").strip()

            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(row)

        # Display one entry per group.
        for _group_key, group_items in groups.items():
            row = group_items[0]
            item_id = str(row.get("id") or "").strip()
            outcome_id = str(row.get("outcome_id") or "").strip()
            source_id = str(row.get("source_id") or "").strip()
            dt = str(row.get("datetime") or "").strip()
            cloud = row.get("cloud_cover")
            gsd = row.get("gsd")
            group_item_ids = []
            for group_row in group_items:
                group_row_id = str(group_row.get("id") or "").strip()
                if group_row_id and group_row_id not in group_item_ids:
                    group_item_ids.append(group_row_id)
            if item_id and item_id not in group_item_ids:
                group_item_ids.insert(0, item_id)

            # Show tile count if grouped.
            tile_suffix = f" ({len(group_items)} tiles)" if len(group_items) > 1 else ""
            label = (
                f"{dt or 'unknown time'} | {source_id or 'unknown source'} | "
                f"cloud={cloud if cloud is not None else '--'} | gsd={gsd if gsd is not None else '--'}{tile_suffix} | {item_id}"
            )
            q_item = QListWidgetItem(label)
            q_item.setData(Qt.UserRole, item_id)
            q_item.setData(Qt.UserRole + 1, outcome_id)
            q_item.setData(Qt.UserRole + 2, group_item_ids)
            q_item.setFlags(q_item.flags() | Qt.ItemIsUserCheckable)
            q_item.setCheckState(Qt.Unchecked)
            self.results_list.addItem(q_item)

            self._result_rows.append(
                {
                    "item_id": item_id,
                    "outcome_id": outcome_id,
                    "label": label,
                    "group_item_ids": group_item_ids,
                }
            )

        self.results_list.blockSignals(False)
        self._refresh_workflow_source_options()
        # Auto-select and load the first result.
        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)
        self._refresh_download_selected_button_state()

    def current_asset_intel_payload(self):
        def _dimension_value(raw_text):
            text = str(raw_text or "").strip()
            if not text:
                return None
            try:
                value = float(text)
            except Exception:
                return None
            # -1 (or any negative value) means default/no filter.
            if value < 0:
                return None
            return value

        length_min_m = _dimension_value(
            self.asset_intel_length_min_input.text()
            if hasattr(self, "asset_intel_length_min_input")
            else ""
        )
        length_max_m = _dimension_value(
            self.asset_intel_length_max_input.text()
            if hasattr(self, "asset_intel_length_max_input")
            else ""
        )
        width_min_m = _dimension_value(
            self.asset_intel_width_min_input.text()
            if hasattr(self, "asset_intel_width_min_input")
            else ""
        )
        width_max_m = _dimension_value(
            self.asset_intel_width_max_input.text()
            if hasattr(self, "asset_intel_width_max_input")
            else ""
        )
        main_domain = str(self.asset_intel_main_domain_combo.currentData() or "").strip()
        return {
            "query_text": self.asset_intel_query_input.text().strip(),
            "domain": main_domain,
            "main_domain": main_domain,
            "sub_domain_1": str(self.asset_intel_sub_domain_1_combo.currentData() or "").strip(),
            "sub_domain_2": str(self.asset_intel_sub_domain_2_combo.currentData() or "").strip(),
            "type": str(self.asset_intel_type_combo.currentData() or "").strip(),
            "origin": str(self.asset_intel_origin_combo.currentData() or "").strip(),
            "proliferation": str(self.asset_intel_proliferation_combo.currentData() or "").strip(),
            "builder": str(self.asset_intel_builder_combo.currentData() or "").strip(),
            "length_min_m": length_min_m,
            "length_max_m": length_max_m,
            "width_min_m": width_min_m,
            "width_max_m": width_max_m,
            "limit": int(self.asset_intel_limit_spin.value()),
        }

    def current_asset_intel_asset_id(self):
        item = self.asset_intel_results_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "").strip()

    def _emit_asset_intel_search_request(self):
        self.asset_intel_search_requested.emit(self.current_asset_intel_payload())
        if hasattr(self, "asset_intel_query_results_tabs") and hasattr(self, "asset_intel_results_tab"):
            index = self.asset_intel_query_results_tabs.indexOf(self.asset_intel_results_tab)
            if index >= 0:
                self.asset_intel_query_results_tabs.setCurrentIndex(index)

    def _emit_asset_intel_polygon_size_from_selection_request(self):
        self.asset_intel_polygon_size_from_selection_requested.emit()

    def set_asset_intel_target_select_mode(self, enabled):
        if not hasattr(self, "asset_intel_extract_size_btn"):
            return
        active = bool(enabled)
        self.asset_intel_extract_size_btn.setCheckable(True)
        self.asset_intel_extract_size_btn.setChecked(active)
        if active:
            self.asset_intel_extract_size_btn.setText("Select Mode")
            self.asset_intel_extract_size_btn.setToolTip("Select Mode: click a polygon on the map canvas.")
        else:
            self.asset_intel_extract_size_btn.setText("Select Target from Map")
            self.asset_intel_extract_size_btn.setToolTip(
                "Enter Select Mode, click a polygon in the map, and apply +/-5m length/width filters."
            )

    def _reset_asset_intel_filters(self):
        self.asset_intel_query_input.clear()
        for combo in (
            self.asset_intel_main_domain_combo,
            self.asset_intel_sub_domain_1_combo,
            self.asset_intel_sub_domain_2_combo,
            self.asset_intel_type_combo,
            self.asset_intel_origin_combo,
            self.asset_intel_proliferation_combo,
            self.asset_intel_builder_combo,
        ):
            combo.setCurrentIndex(0)
        self.asset_intel_length_min_input.setText("-1")
        self.asset_intel_length_max_input.setText("-1")
        self.asset_intel_width_min_input.setText("-1")
        self.asset_intel_width_max_input.setText("-1")
        self.asset_intel_limit_spin.setValue(250)
        self._emit_asset_intel_search_request()

    def _emit_asset_intel_asset_selected(self):
        asset_id = self.current_asset_intel_asset_id()
        if asset_id:
            self.asset_intel_asset_selected.emit(asset_id)

    def _open_asset_intel_details_tab(self):
        if not hasattr(self, "asset_intel_query_results_tabs") or not hasattr(self, "asset_intel_details_tab"):
            return
        index = self.asset_intel_query_results_tabs.indexOf(self.asset_intel_details_tab)
        if index >= 0:
            self.asset_intel_query_results_tabs.setCurrentIndex(index)

    def _on_asset_intel_result_double_clicked(self, _item=None):
        self._emit_asset_intel_asset_selected()
        self._open_asset_intel_details_tab()

    def select_asset_intel_asset(self, asset_id):
        target = str(asset_id or "").strip().lower()
        if not target:
            return
        for idx in range(self.asset_intel_results_list.count()):
            item = self.asset_intel_results_list.item(idx)
            if item is None:
                continue
            row_asset_id = str(item.data(Qt.UserRole) or "").strip().lower()
            if row_asset_id == target:
                self.asset_intel_results_list.setCurrentRow(idx)
                return

    def _open_selected_asset_intel_source_link(self):
        item = self.asset_intel_sources_list.currentItem()
        if item is None:
            return
        url = str(item.data(Qt.UserRole) or "").strip()
        if not url:
            return
        QDesktopServices.openUrl(QUrl(url))

    def _show_asset_intel_asset_editor_dialog(self, title, initial_payload, allow_edit_asset_id):
        payload = initial_payload if isinstance(initial_payload, dict) else {}
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(640, 620)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        asset_id_input = QLineEdit(str(payload.get("asset_id") or "").strip())
        asset_id_input.setPlaceholderText("leave blank to auto-generate")
        asset_id_input.setReadOnly(not allow_edit_asset_id)
        title_input = QLineEdit(str(payload.get("title") or "").strip())
        title_input.setPlaceholderText("required")

        domain_hierarchy = normalize_domain_hierarchy(
            payload.get("domain"),
            payload.get("sub_domain_1"),
            payload.get("sub_domain_2"),
        )
        initial_domain = str(payload.get("domain") or "").strip()
        initial_sub_domain_1 = str(payload.get("sub_domain_1") or "").strip()
        initial_sub_domain_2 = str(payload.get("sub_domain_2") or "").strip()
        if not initial_sub_domain_1:
            initial_sub_domain_1 = str(domain_hierarchy.get("sub_domain_1") or "").strip()
        if not initial_sub_domain_2:
            initial_sub_domain_2 = str(domain_hierarchy.get("sub_domain_2") or "").strip()
        initial_main_domain = str(domain_hierarchy.get("main_domain") or "").strip()
        if not initial_main_domain and initial_domain and "," not in initial_domain:
            initial_main_domain = initial_domain

        facet_rows = self._asset_intel_facet_rows if isinstance(self._asset_intel_facet_rows, dict) else {}
        domain_rows = facet_rows.get("domain_main") or facet_rows.get("domain") or []
        sub_domain_1_rows = facet_rows.get("sub_domain_1") or []
        sub_domain_2_rows = facet_rows.get("sub_domain_2") or []
        origin_rows = facet_rows.get("origin") or []
        proliferation_rows = facet_rows.get("proliferation") or []
        builder_rows = facet_rows.get("builder") or []

        domain_input = self._build_asset_intel_editor_selector_combo(
            domain_rows,
            initial_value=initial_main_domain,
            placeholder_text="Search/select or type new domain",
        )
        sub_domain_1_input = self._build_asset_intel_editor_selector_combo(
            sub_domain_1_rows,
            initial_value=initial_sub_domain_1,
            placeholder_text="Search/select or type new sub domain 1",
        )
        sub_domain_2_input = self._build_asset_intel_editor_selector_combo(
            sub_domain_2_rows,
            initial_value=initial_sub_domain_2,
            placeholder_text="Search/select or type new sub domain 2",
        )
        type_input = self._build_asset_intel_editor_selector_combo(
            self._asset_intel_type_rows_for_sub_domain_2(initial_sub_domain_2),
            initial_value=str(payload.get("type") or "").strip(),
            placeholder_text="Search/select or type new type",
        )
        origin_input = self._build_asset_intel_editor_selector_combo(
            origin_rows,
            initial_value=str(payload.get("origin") or "").strip(),
            placeholder_text="Search/select or type new origin",
        )
        proliferation_input = self._build_asset_intel_editor_selector_combo(
            proliferation_rows,
            initial_value=str(payload.get("proliferation") or "").strip(),
            placeholder_text="Search/select or type new proliferation",
        )
        builder_input = self._build_asset_intel_editor_selector_combo(
            builder_rows,
            initial_value=str(payload.get("builder") or "").strip(),
            placeholder_text="Search/select or type new builder",
        )

        def _refresh_editor_type_options(_value=None):
            selected_sub_domain_2 = self._asset_intel_selector_value(sub_domain_2_input)
            keep_type = self._asset_intel_selector_value(type_input)
            self._set_asset_intel_editor_selector_items(
                type_input,
                self._asset_intel_type_rows_for_sub_domain_2(selected_sub_domain_2),
                keep_value=keep_type,
            )

        sub_domain_2_input.currentTextChanged.connect(_refresh_editor_type_options)
        _refresh_editor_type_options()

        weg_url_input = QLineEdit(str(payload.get("weg_url") or "").strip())
        length_raw_input = QLineEdit(str(payload.get("length_raw") or "").strip())
        width_raw_input = QLineEdit(str(payload.get("width_raw") or "").strip())
        draft_raw_input = QLineEdit(str(payload.get("draft_raw") or "").strip())
        tonnage_raw_input = QLineEdit(str(payload.get("tonnage_raw") or "").strip())
        length_m_input = QLineEdit(str(payload.get("length_m") or "").strip())
        width_m_input = QLineEdit(str(payload.get("width_m") or "").strip())
        draft_m_input = QLineEdit(str(payload.get("draft_m") or "").strip())
        tonnage_mt_input = QLineEdit(str(payload.get("tonnage_mt") or "").strip())

        form.addRow("Asset ID", asset_id_input)
        form.addRow("Title", title_input)
        form.addRow("Type", type_input)
        form.addRow("Domain", domain_input)
        form.addRow("Sub Domain 1", sub_domain_1_input)
        form.addRow("Sub Domain 2", sub_domain_2_input)
        form.addRow("Origin", origin_input)
        form.addRow("Proliferation", proliferation_input)
        form.addRow("Builder", builder_input)
        form.addRow("WEG URL", weg_url_input)
        form.addRow("Length (raw)", length_raw_input)
        form.addRow("Width/Beam (raw)", width_raw_input)
        form.addRow("Draft (raw)", draft_raw_input)
        form.addRow("Tonnage (raw)", tonnage_raw_input)
        form.addRow("Length (m)", length_m_input)
        form.addRow("Width (m)", width_m_input)
        form.addRow("Draft (m)", draft_m_input)
        form.addRow("Tonnage (metric t)", tonnage_mt_input)

        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return None

        title_value = title_input.text().strip()
        if not title_value:
            QMessageBox.warning(self, "Asset Intel", "Asset title is required.")
            return None
        domain_value = self._asset_intel_selector_value(domain_input)
        sub_domain_1_value = self._asset_intel_selector_value(sub_domain_1_input)
        sub_domain_2_value = self._asset_intel_selector_value(sub_domain_2_input)
        return {
            "asset_id": asset_id_input.text().strip(),
            "title": title_value,
            "type": self._asset_intel_selector_value(type_input),
            "domain": domain_value,
            "sub_domain_1": sub_domain_1_value,
            "sub_domain_2": sub_domain_2_value,
            "origin": self._asset_intel_selector_value(origin_input),
            "proliferation": self._asset_intel_selector_value(proliferation_input),
            "builder": self._asset_intel_selector_value(builder_input),
            "weg_url": weg_url_input.text().strip(),
            "length_raw": length_raw_input.text().strip(),
            "width_raw": width_raw_input.text().strip(),
            "draft_raw": draft_raw_input.text().strip(),
            "tonnage_raw": tonnage_raw_input.text().strip(),
            "length_m": length_m_input.text().strip(),
            "width_m": width_m_input.text().strip(),
            "draft_m": draft_m_input.text().strip(),
            "tonnage_mt": tonnage_mt_input.text().strip(),
        }

    def _open_asset_intel_create_dialog(self):
        payload = self._show_asset_intel_asset_editor_dialog(
            "Add Asset Intel Entry",
            {},
            allow_edit_asset_id=True,
        )
        if isinstance(payload, dict):
            self.asset_intel_create_requested.emit(payload)

    def _open_asset_intel_update_dialog(self):
        asset = (
            self._asset_intel_current_detail.get("asset")
            if isinstance(self._asset_intel_current_detail, dict)
            else {}
        )
        if not isinstance(asset, dict) or not str(asset.get("asset_id") or "").strip():
            QMessageBox.information(self, "Asset Intel", "Select an asset first.")
            return
        payload = self._show_asset_intel_asset_editor_dialog(
            "Modify Asset Intel Entry",
            asset,
            allow_edit_asset_id=False,
        )
        if isinstance(payload, dict):
            payload["asset_id"] = str(asset.get("asset_id") or "").strip()
            self.asset_intel_update_requested.emit(payload)

    def _emit_asset_intel_delete_request(self):
        asset_id = self.current_asset_intel_asset_id()
        if not asset_id:
            QMessageBox.information(self, "Asset Intel", "Select an asset first.")
            return
        confirm = QMessageBox.question(
            self,
            "Delete Asset Intel Entry",
            f"Delete asset '{asset_id}' and all linked systems/notes?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.asset_intel_delete_requested.emit(asset_id)

    @staticmethod
    def _asset_intel_parse_optional_float(raw_text):
        value_text = str(raw_text or "").strip()
        if not value_text:
            return None
        try:
            return float(value_text)
        except Exception:
            return None

    def _asset_intel_selected_asset(self):
        payload = self._asset_intel_current_detail if isinstance(self._asset_intel_current_detail, dict) else {}
        asset = payload.get("asset") if isinstance(payload.get("asset"), dict) else {}
        asset_id = str(asset.get("asset_id") or self.current_asset_intel_asset_id() or "").strip()
        if not asset_id:
            return {}
        out = dict(asset)
        out["asset_id"] = asset_id
        return out

    def _asset_intel_selected_unit_row(self):
        row_index = self.asset_intel_units_table.currentRow()
        if row_index < 0 or row_index >= len(self._asset_intel_visible_unit_rows):
            return {}
        row = self._asset_intel_visible_unit_rows[row_index]
        return row if isinstance(row, dict) else {}

    def _emit_asset_intel_structure_mutation(self, action, payload, *, status_text=""):
        mutation_payload = {
            "action": str(action or "").strip().lower(),
            "payload": payload if isinstance(payload, dict) else {},
        }
        status_line = str(status_text or "").strip()
        if status_line:
            mutation_payload["status_text"] = status_line
        self.asset_intel_structure_mutation_requested.emit(mutation_payload)

    def _show_asset_intel_unit_editor_dialog(self, title, initial_payload):
        payload = initial_payload if isinstance(initial_payload, dict) else {}
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(520, 220)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        display_name_input = QLineEdit(str(payload.get("display_name") or "").strip(), dialog)
        status_input = QLineEdit(str(payload.get("status") or "").strip(), dialog)
        status_input.setPlaceholderText("active, reserve, retired, unknown")
        source_input = QLineEdit(str(payload.get("source") or "").strip(), dialog)
        source_input.setPlaceholderText("manual")

        form.addRow("Unit Name", display_name_input)
        form.addRow("Status", status_input)
        form.addRow("Source", source_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return None

        return {
            "display_name": display_name_input.text().strip(),
            "status": status_input.text().strip(),
            "source": source_input.text().strip() or "manual",
        }

    def _show_asset_intel_system_editor_dialog(self, title, initial_payload):
        payload = initial_payload if isinstance(initial_payload, dict) else {}
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(620, 320)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        name_input = QLineEdit(str(payload.get("name") or payload.get("system_name") or "").strip(), dialog)
        name_input.setPlaceholderText("required")
        category_input = QLineEdit(
            str(payload.get("category") or payload.get("system_category") or "").strip(),
            dialog,
        )
        description_input = QTextEdit(dialog)
        description_input.setPlainText(str(payload.get("description") or "").strip())
        source_input = QLineEdit(str(payload.get("source") or "").strip(), dialog)
        source_input.setPlaceholderText("manual")

        form.addRow("System Name", name_input)
        form.addRow("Category", category_input)
        form.addRow("Source", source_input)
        layout.addLayout(form)
        layout.addWidget(QLabel("Description"))
        layout.addWidget(description_input, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return None

        name_value = name_input.text().strip()
        if not name_value:
            QMessageBox.warning(self, "Asset Intel", "System name is required.")
            return None

        return {
            "name": name_value,
            "category": category_input.text().strip(),
            "description": description_input.toPlainText().strip(),
            "source": source_input.text().strip() or "manual",
        }

    def _show_asset_intel_identifier_editor_dialog(self, title, initial_payload):
        payload = initial_payload if isinstance(initial_payload, dict) else {}
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(520, 220)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        identifier_type_combo = QComboBox(dialog)
        identifier_type_combo.setEditable(True)
        for value in ["pennant", "hull_number", "tail_number", "serial", "callsign", "name"]:
            identifier_type_combo.addItem(value, value)
        initial_type = str(payload.get("identifier_type") or "").strip().lower()
        if initial_type:
            idx = identifier_type_combo.findData(initial_type)
            if idx >= 0:
                identifier_type_combo.setCurrentIndex(idx)
            else:
                identifier_type_combo.setEditText(initial_type)

        identifier_value_input = QLineEdit(str(payload.get("identifier_raw") or "").strip(), dialog)
        identifier_value_input.setPlaceholderText("required")
        is_primary_checkbox = QCheckBox("Primary Identifier", dialog)
        is_primary_checkbox.setChecked(bool(payload.get("is_primary")))

        form.addRow("Identifier Type", identifier_type_combo)
        form.addRow("Identifier Value", identifier_value_input)
        form.addRow(is_primary_checkbox)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return None

        identifier_type = self._asset_intel_selector_value(identifier_type_combo).strip().lower()
        identifier_raw = identifier_value_input.text().strip()
        if not identifier_type:
            QMessageBox.warning(self, "Asset Intel", "Identifier type is required.")
            return None
        if not identifier_raw:
            QMessageBox.warning(self, "Asset Intel", "Identifier value is required.")
            return None
        return {
            "identifier_type": identifier_type,
            "identifier_raw": identifier_raw,
            "is_primary": bool(is_primary_checkbox.isChecked()),
        }

    def _show_asset_intel_system_fit_editor_dialog(self, title, initial_payload):
        payload = initial_payload if isinstance(initial_payload, dict) else {}
        available_system_rows = [
            row for row in self._asset_intel_system_rows if isinstance(row, dict) and int(row.get("system_id") or 0) > 0
        ]
        if not available_system_rows:
            QMessageBox.information(
                self,
                "Asset Intel",
                "No onboard systems are available. Add a system first.",
            )
            return None

        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(560, 260)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        system_combo = QComboBox(dialog)
        for row in available_system_rows:
            system_id = int(row.get("system_id") or 0)
            name = str(row.get("name") or "").strip() or f"System {system_id}"
            category = str(row.get("category") or "").strip()
            label = f"{name} [{category}]" if category else name
            system_combo.addItem(label, system_id)
        selected_system_id = int(payload.get("system_id") or 0)
        if selected_system_id > 0:
            idx = system_combo.findData(selected_system_id)
            if idx >= 0:
                system_combo.setCurrentIndex(idx)

        fit_status_combo = QComboBox(dialog)
        fit_status_combo.setEditable(True)
        for value in ["unknown", "fielded", "planned", "retired", "prototype"]:
            fit_status_combo.addItem(value, value)
        selected_fit_status = str(payload.get("fit_status") or "").strip().lower()
        if selected_fit_status:
            idx = fit_status_combo.findData(selected_fit_status)
            if idx >= 0:
                fit_status_combo.setCurrentIndex(idx)
            else:
                fit_status_combo.setEditText(selected_fit_status)

        quantity_input = QLineEdit(dialog)
        quantity_value = payload.get("quantity")
        quantity_input.setText("" if quantity_value is None else str(quantity_value))
        quantity_input.setPlaceholderText("optional numeric value")
        source_input = QLineEdit(str(payload.get("source") or "").strip(), dialog)
        source_input.setPlaceholderText("manual")

        form.addRow("Onboard System", system_combo)
        form.addRow("Fit Status", fit_status_combo)
        form.addRow("Quantity", quantity_input)
        form.addRow("Source", source_input)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return None

        selected_system_id = int(system_combo.currentData() or 0)
        if selected_system_id <= 0:
            QMessageBox.warning(self, "Asset Intel", "Select an onboard system.")
            return None

        quantity_text = quantity_input.text().strip()
        quantity = None
        if quantity_text:
            quantity = self._asset_intel_parse_optional_float(quantity_text)
            if quantity is None:
                QMessageBox.warning(self, "Asset Intel", "Quantity must be numeric.")
                return None

        return {
            "system_id": selected_system_id,
            "fit_status": self._asset_intel_selector_value(fit_status_combo).strip() or "unknown",
            "quantity": quantity,
            "source": source_input.text().strip() or "manual",
        }

    def _open_asset_intel_new_unit_dialog(self):
        asset = self._asset_intel_selected_asset()
        asset_id = str(asset.get("asset_id") or "").strip()
        if not asset_id:
            QMessageBox.information(self, "Asset Intel", "Select an asset first.")
            return
        payload = self._show_asset_intel_unit_editor_dialog("New Fielded Unit", {})
        if not isinstance(payload, dict):
            return
        payload["asset_id"] = asset_id
        self._emit_asset_intel_structure_mutation(
            "create_unit",
            payload,
            status_text="Asset Intel: fielded unit created.",
        )

    def _open_asset_intel_edit_unit_dialog(self, row_index):
        if row_index < 0 or row_index >= len(self._asset_intel_visible_unit_rows):
            return
        row = self._asset_intel_visible_unit_rows[row_index]
        if not isinstance(row, dict):
            return
        unit_id = int(row.get("unit_id") or 0)
        if unit_id <= 0:
            return
        payload = self._show_asset_intel_unit_editor_dialog("Modify Fielded Unit", row)
        if not isinstance(payload, dict):
            return
        payload["unit_id"] = unit_id
        self._emit_asset_intel_structure_mutation(
            "update_unit",
            payload,
            status_text=f"Asset Intel: fielded unit {unit_id} updated.",
        )

    def _open_asset_intel_new_system_dialog(self):
        asset = self._asset_intel_selected_asset()
        asset_id = str(asset.get("asset_id") or "").strip()
        if not asset_id:
            QMessageBox.information(self, "Asset Intel", "Select an asset first.")
            return
        payload = self._show_asset_intel_system_editor_dialog("New Onboard System", {})
        if not isinstance(payload, dict):
            return
        payload["asset_id"] = asset_id
        self._emit_asset_intel_structure_mutation(
            "create_system",
            payload,
            status_text="Asset Intel: onboard system created.",
        )

    def _open_asset_intel_edit_system_dialog(self, row_index):
        if row_index < 0 or row_index >= len(self._asset_intel_system_rows):
            return
        row = self._asset_intel_system_rows[row_index]
        if not isinstance(row, dict):
            return
        system_id = int(row.get("system_id") or 0)
        if system_id <= 0:
            return
        payload = self._show_asset_intel_system_editor_dialog("Modify Onboard System", row)
        if not isinstance(payload, dict):
            return
        payload["system_id"] = system_id
        self._emit_asset_intel_structure_mutation(
            "update_system",
            payload,
            status_text=f"Asset Intel: onboard system {system_id} updated.",
        )

    def _open_asset_intel_new_identifier_dialog(self):
        selected_unit = self._asset_intel_selected_unit_row()
        unit_id = int(selected_unit.get("unit_id") or 0)
        if unit_id <= 0:
            QMessageBox.information(self, "Asset Intel", "Select a fielded unit first.")
            return
        payload = self._show_asset_intel_identifier_editor_dialog("New Identifier", {})
        if not isinstance(payload, dict):
            return
        payload["unit_id"] = unit_id
        self._emit_asset_intel_structure_mutation(
            "create_unit_identifier",
            payload,
            status_text="Asset Intel: identifier created.",
        )

    def _open_asset_intel_edit_identifier_dialog(self, row_index):
        selected_unit = self._asset_intel_selected_unit_row()
        unit_id = int(selected_unit.get("unit_id") or 0)
        if unit_id <= 0:
            return
        identifiers = selected_unit.get("identifiers") if isinstance(selected_unit.get("identifiers"), list) else []
        if row_index < 0 or row_index >= len(identifiers):
            return
        row = identifiers[row_index]
        if not isinstance(row, dict):
            return
        identifier_id = int(row.get("id") or 0)
        if identifier_id <= 0:
            return
        payload = self._show_asset_intel_identifier_editor_dialog("Modify Identifier", row)
        if not isinstance(payload, dict):
            return
        payload["unit_id"] = unit_id
        payload["identifier_id"] = identifier_id
        self._emit_asset_intel_structure_mutation(
            "update_unit_identifier",
            payload,
            status_text=f"Asset Intel: identifier {identifier_id} updated.",
        )

    def _open_asset_intel_new_system_fit_dialog(self):
        selected_unit = self._asset_intel_selected_unit_row()
        unit_id = int(selected_unit.get("unit_id") or 0)
        if unit_id <= 0:
            QMessageBox.information(self, "Asset Intel", "Select a fielded unit first.")
            return
        payload = self._show_asset_intel_system_fit_editor_dialog("New Unit-System Fit", {})
        if not isinstance(payload, dict):
            return
        payload["unit_id"] = unit_id
        self._emit_asset_intel_structure_mutation(
            "create_unit_system_fit",
            payload,
            status_text="Asset Intel: unit-system fit created.",
        )

    def _open_asset_intel_edit_system_fit_dialog(self, row_index):
        selected_unit = self._asset_intel_selected_unit_row()
        unit_id = int(selected_unit.get("unit_id") or 0)
        if unit_id <= 0:
            return
        linked_systems = selected_unit.get("linked_systems") if isinstance(selected_unit.get("linked_systems"), list) else []
        if row_index < 0 or row_index >= len(linked_systems):
            return
        row = linked_systems[row_index]
        if not isinstance(row, dict):
            return
        fit_id = int(row.get("fit_id") or 0)
        if fit_id <= 0:
            return
        payload = self._show_asset_intel_system_fit_editor_dialog("Modify Unit-System Fit", row)
        if not isinstance(payload, dict):
            return
        payload["fit_id"] = fit_id
        payload["unit_id"] = unit_id
        self._emit_asset_intel_structure_mutation(
            "update_unit_system_fit",
            payload,
            status_text=f"Asset Intel: unit-system fit {fit_id} updated.",
        )

    def _on_asset_intel_system_scope_action_clicked(self):
        scope_index = self.asset_intel_system_scope_tabs.currentIndex()
        if scope_index == 0:
            self._open_asset_intel_new_unit_dialog()
        else:
            self._open_asset_intel_new_system_dialog()

    def _refresh_asset_intel_system_scope_action_button(self):
        if not hasattr(self, "asset_intel_system_scope_action_btn"):
            return
        scope_index = self.asset_intel_system_scope_tabs.currentIndex()
        has_asset = bool(str(self._asset_intel_selected_asset().get("asset_id") or "").strip())
        if scope_index == 0:
            self.asset_intel_system_scope_action_btn.setText("New Units")
            self.asset_intel_system_scope_action_btn.setToolTip("Add a new fielded unit.")
        else:
            self.asset_intel_system_scope_action_btn.setText("New System")
            self.asset_intel_system_scope_action_btn.setToolTip("Add a new onboard system.")
        self.asset_intel_system_scope_action_btn.setEnabled(has_asset)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonDblClick:
            identifier_table = getattr(self, "asset_intel_unit_identifier_table", None)
            if identifier_table is not None and watched is identifier_table.viewport():
                index = identifier_table.indexAt(event.pos())
                if not index.isValid():
                    self._open_asset_intel_new_identifier_dialog()
                    return True
            fit_table = getattr(self, "asset_intel_unit_system_fit_table", None)
            if fit_table is not None and watched is fit_table.viewport():
                index = fit_table.indexAt(event.pos())
                if not index.isValid():
                    self._open_asset_intel_new_system_fit_dialog()
                    return True
        return super().eventFilter(watched, event)

    def _on_asset_intel_system_selection_changed(self):
        self.asset_intel_system_attr_table.setRowCount(0)
        self._asset_intel_selected_system_id = None
        row_index = self.asset_intel_systems_table.currentRow()
        if row_index < 0 or row_index >= len(self._asset_intel_system_rows):
            self._refresh_asset_intel_note_target_options()
            return
        system_row = self._asset_intel_system_rows[row_index]
        system_id = int(system_row.get("system_id") or 0)
        self._asset_intel_selected_system_id = system_id if system_id > 0 else None
        attrs = system_row.get("attributes") if isinstance(system_row.get("attributes"), list) else []
        self.asset_intel_system_attr_table.setRowCount(len(attrs))
        for idx, attr in enumerate(attrs):
            key = str(attr.get("key") or "").strip()
            value = str(attr.get("value") or "").strip()
            unit = str(attr.get("unit") or "").strip()
            self.asset_intel_system_attr_table.setItem(idx, 0, QTableWidgetItem(key))
            self.asset_intel_system_attr_table.setItem(idx, 1, QTableWidgetItem(value))
            self.asset_intel_system_attr_table.setItem(idx, 2, QTableWidgetItem(unit))
        self._refresh_asset_intel_note_target_options()

    def _apply_asset_intel_unit_filter(self):
        query = str(self.asset_intel_unit_filter_input.text() or "").strip().lower()
        self.asset_intel_units_table.setRowCount(0)
        self.asset_intel_unit_identifier_table.setRowCount(0)
        self.asset_intel_unit_system_fit_table.setRowCount(0)
        self._asset_intel_visible_unit_rows = []
        for row in self._asset_intel_unit_rows:
            if not isinstance(row, dict):
                continue
            if query:
                haystack = " ".join(
                    [
                        str(row.get("display_name") or "").strip(),
                        str(row.get("primary_identifier") or "").strip(),
                        str(row.get("primary_identifier_type") or "").strip(),
                        str(row.get("status") or "").strip(),
                    ]
                ).lower()
                identifiers = row.get("identifiers") if isinstance(row.get("identifiers"), list) else []
                for identifier_row in identifiers:
                    if not isinstance(identifier_row, dict):
                        continue
                    haystack += " " + str(identifier_row.get("identifier_raw") or "").strip().lower()
                if query not in haystack:
                    continue
            self._asset_intel_visible_unit_rows.append(row)

        self.asset_intel_units_table.setRowCount(len(self._asset_intel_visible_unit_rows))
        for idx, row in enumerate(self._asset_intel_visible_unit_rows):
            primary_identifier = str(row.get("primary_identifier") or "").strip()
            display_name = str(row.get("display_name") or "").strip()
            identifier_type = str(row.get("primary_identifier_type") or "").strip()
            status = str(row.get("status") or "").strip()
            linked_system_count = int(row.get("linked_system_count") or 0)
            note_count = int(row.get("note_count") or 0)
            source = str(row.get("source") or "").strip()

            self.asset_intel_units_table.setItem(idx, 0, QTableWidgetItem(primary_identifier))
            self.asset_intel_units_table.setItem(idx, 1, QTableWidgetItem(display_name))
            self.asset_intel_units_table.setItem(idx, 2, QTableWidgetItem(identifier_type))
            self.asset_intel_units_table.setItem(idx, 3, QTableWidgetItem(status))
            self.asset_intel_units_table.setItem(idx, 4, QTableWidgetItem(str(linked_system_count)))
            self.asset_intel_units_table.setItem(idx, 5, QTableWidgetItem(str(note_count)))
            self.asset_intel_units_table.setItem(idx, 6, QTableWidgetItem(source))

        target_row = -1
        if self._asset_intel_selected_unit_id is not None:
            for idx, row in enumerate(self._asset_intel_visible_unit_rows):
                unit_id = int(row.get("unit_id") or 0)
                if unit_id > 0 and unit_id == int(self._asset_intel_selected_unit_id):
                    target_row = idx
                    break
        if target_row >= 0:
            self.asset_intel_units_table.setCurrentCell(target_row, 0)
        elif self.asset_intel_units_table.rowCount() > 0:
            self.asset_intel_units_table.setCurrentCell(0, 0)
        else:
            self._on_asset_intel_unit_selection_changed()

    def _on_asset_intel_unit_selection_changed(self):
        self.asset_intel_unit_identifier_table.setRowCount(0)
        self.asset_intel_unit_system_fit_table.setRowCount(0)
        self._asset_intel_selected_unit_id = None
        row_index = self.asset_intel_units_table.currentRow()
        if row_index < 0 or row_index >= len(self._asset_intel_visible_unit_rows):
            self._refresh_asset_intel_note_target_options()
            return

        unit_row = self._asset_intel_visible_unit_rows[row_index]
        unit_id = int(unit_row.get("unit_id") or 0)
        self._asset_intel_selected_unit_id = unit_id if unit_id > 0 else None

        identifiers = unit_row.get("identifiers") if isinstance(unit_row.get("identifiers"), list) else []
        self.asset_intel_unit_identifier_table.setRowCount(len(identifiers))
        for idx, identifier_row in enumerate(identifiers):
            identifier_type = str(identifier_row.get("identifier_type") or "").strip()
            identifier_raw = str(identifier_row.get("identifier_raw") or "").strip()
            is_primary = bool(identifier_row.get("is_primary"))
            self.asset_intel_unit_identifier_table.setItem(idx, 0, QTableWidgetItem(identifier_type))
            self.asset_intel_unit_identifier_table.setItem(idx, 1, QTableWidgetItem(identifier_raw))
            self.asset_intel_unit_identifier_table.setItem(idx, 2, QTableWidgetItem("Yes" if is_primary else ""))

        linked_systems = unit_row.get("linked_systems") if isinstance(unit_row.get("linked_systems"), list) else []
        self.asset_intel_unit_system_fit_table.setRowCount(len(linked_systems))
        for idx, linked_row in enumerate(linked_systems):
            system_name = str(linked_row.get("system_name") or "").strip()
            system_category = str(linked_row.get("system_category") or "").strip()
            fit_status = str(linked_row.get("fit_status") or "").strip()
            quantity_value = linked_row.get("quantity")
            quantity_text = "" if quantity_value is None else str(quantity_value)
            self.asset_intel_unit_system_fit_table.setItem(idx, 0, QTableWidgetItem(system_name))
            self.asset_intel_unit_system_fit_table.setItem(idx, 1, QTableWidgetItem(system_category))
            self.asset_intel_unit_system_fit_table.setItem(idx, 2, QTableWidgetItem(fit_status))
            self.asset_intel_unit_system_fit_table.setItem(idx, 3, QTableWidgetItem(quantity_text))
        self._refresh_asset_intel_note_target_options()

    def _refresh_asset_intel_note_target_options(self):
        selected_data = str(self.asset_intel_note_target_combo.currentData() or "").strip()
        self.asset_intel_note_target_combo.blockSignals(True)
        self.asset_intel_note_target_combo.clear()
        self.asset_intel_note_target_combo.addItem("Asset (General)", "asset")
        for row in self._asset_intel_unit_rows:
            if not isinstance(row, dict):
                continue
            unit_id = int(row.get("unit_id") or 0)
            if unit_id <= 0:
                continue
            primary_identifier = str(row.get("primary_identifier") or "").strip()
            display_name = str(row.get("display_name") or "").strip() or f"Unit {unit_id}"
            label = f"{primary_identifier} ({display_name})" if primary_identifier else display_name
            self.asset_intel_note_target_combo.addItem(f"Unit: {label}", f"unit:{unit_id}")
        for row in self._asset_intel_system_rows:
            if not isinstance(row, dict):
                continue
            system_id = int(row.get("system_id") or 0)
            if system_id <= 0:
                continue
            name = str(row.get("name") or "").strip() or f"System {system_id}"
            category = str(row.get("category") or "").strip()
            label = f"{name} [{category}]" if category else name
            self.asset_intel_note_target_combo.addItem(f"System: {label}", f"system:{system_id}")
        target_index = 0
        if self._asset_intel_selected_unit_id is not None:
            idx = self.asset_intel_note_target_combo.findData(f"unit:{int(self._asset_intel_selected_unit_id)}")
            if idx >= 0:
                target_index = idx
        elif self._asset_intel_selected_system_id is not None:
            idx = self.asset_intel_note_target_combo.findData(f"system:{int(self._asset_intel_selected_system_id)}")
            if idx >= 0:
                target_index = idx
        elif selected_data is not None:
            idx = self.asset_intel_note_target_combo.findData(selected_data)
            if idx >= 0:
                target_index = idx
        self.asset_intel_note_target_combo.setCurrentIndex(target_index)
        self.asset_intel_note_target_combo.blockSignals(False)

    def _on_asset_intel_note_selection_changed(self):
        row_index = self.asset_intel_notes_table.currentRow()
        if row_index < 0 or row_index >= len(self._asset_intel_note_rows):
            self._clear_asset_intel_note_form()
            return
        row = self._asset_intel_note_rows[row_index]
        note_id = int(row.get("note_id") or 0)
        self._asset_intel_selected_note_id = note_id if note_id > 0 else None
        self.asset_intel_note_id_label.setText(
            f"Note ID: {note_id}" if note_id > 0 else "Note ID: (new)"
        )
        self.asset_intel_note_analyst_input.setText(str(row.get("analyst_name") or "").strip())
        self.asset_intel_note_title_input.setText(str(row.get("note_title") or "").strip())
        self.asset_intel_note_tags_input.setText(str(row.get("tags_csv") or "").strip())
        self.asset_intel_note_location_input.setText(str(row.get("location_text") or "").strip())
        self.asset_intel_note_source_ref_input.setText(str(row.get("source_ref") or "").strip())
        self.asset_intel_note_text_input.setPlainText(str(row.get("note_text") or "").strip())
        self.asset_intel_note_ai_checkbox.setChecked(bool(row.get("is_ai_generated")))
        for combo, value in (
            (self.asset_intel_note_type_combo, str(row.get("note_type") or "").strip()),
            (self.asset_intel_note_priority_combo, str(row.get("priority") or "").strip()),
            (self.asset_intel_note_confidence_combo, str(row.get("confidence") or "").strip()),
            (self.asset_intel_note_source_reliability_combo, str(row.get("source_reliability") or "").strip()),
            (self.asset_intel_note_info_credibility_combo, str(row.get("information_credibility") or "").strip()),
        ):
            idx = combo.findData(value)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        fleet_unit_id = row.get("fleet_unit_id")
        system_id = row.get("system_id")
        if fleet_unit_id is not None and int(fleet_unit_id or 0) > 0:
            target_value = f"unit:{int(fleet_unit_id)}"
        elif system_id is not None and int(system_id or 0) > 0:
            target_value = f"system:{int(system_id)}"
        else:
            target_value = "asset"
        idx = self.asset_intel_note_target_combo.findData(target_value)
        self.asset_intel_note_target_combo.setCurrentIndex(idx if idx >= 0 else 0)
        event_text = str(row.get("event_time_utc") or "").strip()
        event_dt = QDateTime.fromString(event_text, Qt.ISODate)
        if event_dt.isValid():
            self.asset_intel_note_event_datetime.setDateTime(event_dt)

    def _clear_asset_intel_note_form(self):
        self._asset_intel_selected_note_id = None
        self.asset_intel_note_id_label.setText("Note ID: (new)")
        self.asset_intel_note_analyst_input.clear()
        self.asset_intel_note_title_input.clear()
        self.asset_intel_note_tags_input.clear()
        self.asset_intel_note_location_input.clear()
        self.asset_intel_note_source_ref_input.clear()
        self.asset_intel_note_text_input.clear()
        self.asset_intel_note_ai_checkbox.setChecked(False)
        self.asset_intel_note_type_combo.setCurrentIndex(0)
        self.asset_intel_note_priority_combo.setCurrentIndex(1)
        self.asset_intel_note_confidence_combo.setCurrentIndex(0)
        self.asset_intel_note_source_reliability_combo.setCurrentIndex(0)
        self.asset_intel_note_info_credibility_combo.setCurrentIndex(0)
        self.asset_intel_note_event_datetime.setDateTime(QDateTime.currentDateTimeUtc())
        target_value = "asset"
        if self._asset_intel_selected_unit_id is not None:
            target_value = f"unit:{int(self._asset_intel_selected_unit_id)}"
        elif self._asset_intel_selected_system_id is not None:
            target_value = f"system:{int(self._asset_intel_selected_system_id)}"
        idx = self.asset_intel_note_target_combo.findData(target_value)
        self.asset_intel_note_target_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _collect_asset_intel_note_payload(self):
        asset_id = self.current_asset_intel_asset_id()
        if not asset_id:
            QMessageBox.information(self, "Asset Intel", "Select an asset first.")
            return None
        analyst_name = self.asset_intel_note_analyst_input.text().strip()
        note_text = self.asset_intel_note_text_input.toPlainText().strip()
        if not analyst_name:
            QMessageBox.warning(self, "Asset Intel", "Analyst name is required.")
            return None
        if not note_text:
            QMessageBox.warning(self, "Asset Intel", "Note text is required.")
            return None
        target_data = str(self.asset_intel_note_target_combo.currentData() or "").strip().lower()
        target_system_id = 0
        target_unit_id = 0
        if target_data.startswith("system:"):
            try:
                target_system_id = int(target_data.split(":", 1)[1])
            except Exception:
                target_system_id = 0
        elif target_data.startswith("unit:"):
            try:
                target_unit_id = int(target_data.split(":", 1)[1])
            except Exception:
                target_unit_id = 0
        return {
            "asset_id": asset_id,
            "system_id": target_system_id if target_system_id > 0 else None,
            "fleet_unit_id": target_unit_id if target_unit_id > 0 else None,
            "analyst_name": analyst_name,
            "note_title": self.asset_intel_note_title_input.text().strip(),
            "note_text": note_text,
            "note_type": str(self.asset_intel_note_type_combo.currentData() or "").strip(),
            "priority": str(self.asset_intel_note_priority_combo.currentData() or "").strip(),
            "confidence": str(self.asset_intel_note_confidence_combo.currentData() or "").strip(),
            "source_reliability": str(self.asset_intel_note_source_reliability_combo.currentData() or "").strip(),
            "information_credibility": str(self.asset_intel_note_info_credibility_combo.currentData() or "").strip(),
            "event_time_utc": self.asset_intel_note_event_datetime.dateTime().toUTC().toString(Qt.ISODate),
            "reported_time_utc": QDateTime.currentDateTimeUtc().toString(Qt.ISODate),
            "location_text": self.asset_intel_note_location_input.text().strip(),
            "tags_csv": self.asset_intel_note_tags_input.text().strip(),
            "source_ref": self.asset_intel_note_source_ref_input.text().strip(),
            "is_ai_generated": bool(self.asset_intel_note_ai_checkbox.isChecked()),
        }

    def _emit_asset_intel_note_create_request(self):
        payload = self._collect_asset_intel_note_payload()
        if isinstance(payload, dict):
            self.asset_intel_note_create_requested.emit(payload)

    def _emit_asset_intel_note_update_request(self):
        if not self._asset_intel_selected_note_id:
            QMessageBox.information(self, "Asset Intel", "Select a note to update.")
            return
        payload = self._collect_asset_intel_note_payload()
        if isinstance(payload, dict):
            payload["note_id"] = int(self._asset_intel_selected_note_id)
            self.asset_intel_note_update_requested.emit(payload)

    def _emit_asset_intel_note_delete_request(self):
        if not self._asset_intel_selected_note_id:
            QMessageBox.information(self, "Asset Intel", "Select a note to delete.")
            return
        confirm = QMessageBox.question(
            self,
            "Delete Analyst Note",
            "Delete the selected analyst note?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.asset_intel_note_delete_requested.emit(int(self._asset_intel_selected_note_id))

    def set_asset_intel_status(self, text):
        self.asset_intel_status_label.setText(str(text or "").strip() or "Asset Intel: idle")

    @staticmethod
    def _set_facet_combo_items(combo, rows):
        current = str(combo.currentData() or "").strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Any", "")
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            count = int(row.get("count") or 0)
            label = f"{value} ({count})" if count > 0 else value
            combo.addItem(label, value)
        if current:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    @staticmethod
    def _facet_rows_to_values(rows):
        out = []
        seen = set()
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            value = str(row.get("value") or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(value)
        return out

    @staticmethod
    def _asset_intel_selector_value(combo):
        current_data = str(combo.currentData() or "").strip() if combo is not None else ""
        current_text = str(combo.currentText() or "").strip() if combo is not None else ""
        return current_text or current_data

    def _set_asset_intel_editor_selector_items(self, combo, rows, *, keep_value=""):
        if combo is None:
            return
        selected_value = str(keep_value or self._asset_intel_selector_value(combo) or "").strip()
        values = self._facet_rows_to_values(rows)
        combo.blockSignals(True)
        combo.clear()
        for value in values:
            combo.addItem(value, value)
        if selected_value:
            idx = combo.findData(selected_value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.setEditText(selected_value)
        combo.blockSignals(False)

    def _build_asset_intel_editor_selector_combo(self, rows, *, initial_value="", placeholder_text=""):
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setToolTip("Search/select existing value or type a new one.")
        line_edit = combo.lineEdit()
        if line_edit is not None and placeholder_text:
            line_edit.setPlaceholderText(placeholder_text)
        completer = combo.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCompletionMode(QCompleter.PopupCompletion)
        self._set_asset_intel_editor_selector_items(
            combo,
            rows,
            keep_value=str(initial_value or "").strip(),
        )
        return combo

    def _asset_intel_type_rows_for_sub_domain_2(self, sub_domain_2):
        key = str(sub_domain_2 or "").strip().lower()
        if key and key in self._asset_intel_type_rows_by_sub_domain_2:
            return self._asset_intel_type_rows_by_sub_domain_2.get(key) or []
        return self._asset_intel_type_facet_rows

    def _refresh_asset_intel_type_options_for_sub_domain_2(self):
        if not hasattr(self, "asset_intel_type_combo"):
            return
        selected_sub_domain_2 = str(self.asset_intel_sub_domain_2_combo.currentData() or "").strip().lower()
        type_rows = self._asset_intel_type_rows_for_sub_domain_2(selected_sub_domain_2)
        self._set_facet_combo_items(self.asset_intel_type_combo, type_rows)

    def _on_asset_intel_sub_domain_2_changed(self):
        self._refresh_asset_intel_type_options_for_sub_domain_2()

    def set_asset_intel_facets(self, facets):
        facet_rows = facets if isinstance(facets, dict) else {}
        self._asset_intel_facet_rows = dict(facet_rows)
        main_domain_rows = facet_rows.get("domain_main") or facet_rows.get("domain") or []
        self._set_facet_combo_items(self.asset_intel_main_domain_combo, main_domain_rows)
        self._set_facet_combo_items(self.asset_intel_sub_domain_1_combo, facet_rows.get("sub_domain_1") or [])
        self._set_facet_combo_items(self.asset_intel_sub_domain_2_combo, facet_rows.get("sub_domain_2") or [])
        self._asset_intel_type_facet_rows = (
            facet_rows.get("type") if isinstance(facet_rows.get("type"), list) else []
        )
        type_by_sub_domain_2 = facet_rows.get("type_by_sub_domain_2")
        mapped = {}
        if isinstance(type_by_sub_domain_2, dict):
            for key, rows in type_by_sub_domain_2.items():
                sub_domain_2 = str(key or "").strip().lower()
                if not sub_domain_2:
                    continue
                mapped[sub_domain_2] = rows if isinstance(rows, list) else []
        self._asset_intel_type_rows_by_sub_domain_2 = mapped
        self._refresh_asset_intel_type_options_for_sub_domain_2()
        self._set_facet_combo_items(self.asset_intel_origin_combo, facet_rows.get("origin") or [])
        self._set_facet_combo_items(self.asset_intel_proliferation_combo, facet_rows.get("proliferation") or [])
        self._set_facet_combo_items(self.asset_intel_builder_combo, facet_rows.get("builder") or [])

    def set_asset_intel_results(self, rows):
        prior_asset_id = self.current_asset_intel_asset_id().lower()
        self.asset_intel_results_list.blockSignals(True)
        self.asset_intel_results_list.clear()
        self._asset_intel_result_rows = []
        target_row = -1
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            asset_id = str(row.get("asset_id") or "").strip()
            title = str(row.get("title") or "").strip()
            type_value = str(row.get("type") or "").strip()
            origin = str(row.get("origin") or "").strip()
            domain = str(row.get("domain") or "").strip()
            page_range = ""
            start_page = row.get("start_page")
            end_page = row.get("end_page")
            if isinstance(start_page, int) and isinstance(end_page, int) and start_page > 0:
                page_range = f"p{start_page}-{end_page}"
            label = " | ".join(
                [part for part in (title or asset_id, type_value, origin, domain, page_range) if part]
            )
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, asset_id)
            item.setData(Qt.UserRole + 1, row)
            self.asset_intel_results_list.addItem(item)
            self._asset_intel_result_rows.append(row)
            if prior_asset_id and asset_id.lower() == prior_asset_id:
                target_row = self.asset_intel_results_list.count() - 1
        self.asset_intel_results_list.blockSignals(False)
        if self.asset_intel_results_list.count() > 0:
            if target_row >= 0:
                self.asset_intel_results_list.setCurrentRow(target_row)
            else:
                self.asset_intel_results_list.setCurrentRow(0)
        else:
            self.set_asset_intel_detail(None)

    def set_asset_intel_detail(self, detail):
        payload = detail if isinstance(detail, dict) else {}
        asset = payload.get("asset") if isinstance(payload.get("asset"), dict) else {}
        overview_rows = payload.get("overview") if isinstance(payload.get("overview"), list) else []
        systems = payload.get("systems") if isinstance(payload.get("systems"), list) else []
        fielded_units = payload.get("fielded_units") if isinstance(payload.get("fielded_units"), list) else []
        sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
        raw_rows = payload.get("raw_text") if isinstance(payload.get("raw_text"), list) else []
        notes = payload.get("analyst_notes") if isinstance(payload.get("analyst_notes"), list) else []
        self._asset_intel_current_detail = payload

        if not asset:
            self.asset_intel_overview_text.setPlainText("No asset selected.")
            self.asset_intel_systems_table.setRowCount(0)
            self.asset_intel_system_attr_table.setRowCount(0)
            self.asset_intel_units_table.setRowCount(0)
            self.asset_intel_unit_identifier_table.setRowCount(0)
            self.asset_intel_unit_system_fit_table.setRowCount(0)
            self.asset_intel_notes_table.setRowCount(0)
            self._asset_intel_system_rows = []
            self._asset_intel_unit_rows = []
            self._asset_intel_visible_unit_rows = []
            self._asset_intel_note_rows = []
            self._asset_intel_selected_system_id = None
            self._asset_intel_selected_unit_id = None
            self._refresh_asset_intel_note_target_options()
            self._clear_asset_intel_note_form()
            self.asset_intel_unit_filter_input.clear()
            self.asset_intel_sources_list.clear()
            self.asset_intel_raw_text.clear()
            self._refresh_asset_intel_system_scope_action_button()
            return

        overview_lines = [
            f"Title: {str(asset.get('title') or '').strip()}",
            f"Asset ID: {str(asset.get('asset_id') or '').strip()}",
            f"WEG URL: {str(asset.get('weg_url') or '').strip() or '(unavailable)'}",
            f"Page Range: {asset.get('start_page')} - {asset.get('end_page')}",
            "",
        ]
        for row in overview_rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key") or "").strip()
            value = str(row.get("value") or "").strip()
            if key and value:
                overview_lines.append(f"{key}: {value}")
        self.asset_intel_overview_text.setPlainText("\n".join(overview_lines).strip())

        self.asset_intel_systems_table.setRowCount(0)
        self.asset_intel_system_attr_table.setRowCount(0)
        self._asset_intel_system_rows = []
        for row in systems:
            if not isinstance(row, dict):
                continue
            self._asset_intel_system_rows.append(row)
        self.asset_intel_systems_table.setRowCount(len(self._asset_intel_system_rows))
        for idx, row in enumerate(self._asset_intel_system_rows):
            name = str(row.get("name") or "").strip()
            category = str(row.get("category") or "").strip()
            summary = str(row.get("description") or "").strip()
            page_start = int(row.get("page_start") or 0)
            page_end = int(row.get("page_end") or 0)
            note_count = int(row.get("note_count") or 0)
            page_text = f"p{page_start}-{page_end}" if page_start > 0 else ""
            self.asset_intel_systems_table.setItem(idx, 0, QTableWidgetItem(name))
            self.asset_intel_systems_table.setItem(idx, 1, QTableWidgetItem(category))
            self.asset_intel_systems_table.setItem(idx, 2, QTableWidgetItem(summary))
            self.asset_intel_systems_table.setItem(idx, 3, QTableWidgetItem(page_text))
            self.asset_intel_systems_table.setItem(idx, 4, QTableWidgetItem(str(note_count)))
        if self.asset_intel_systems_table.rowCount() > 0:
            self.asset_intel_systems_table.setCurrentCell(0, 0)
        self._on_asset_intel_system_selection_changed()

        self._asset_intel_selected_unit_id = None
        self._asset_intel_unit_rows = []
        self._asset_intel_visible_unit_rows = []
        for row in fielded_units:
            if not isinstance(row, dict):
                continue
            self._asset_intel_unit_rows.append(row)
        self.asset_intel_unit_filter_input.clear()
        self._apply_asset_intel_unit_filter()

        self.asset_intel_notes_table.setRowCount(0)
        self._asset_intel_note_rows = [row for row in notes if isinstance(row, dict)]
        self.asset_intel_notes_table.setRowCount(len(self._asset_intel_note_rows))
        for idx, row in enumerate(self._asset_intel_note_rows):
            event_time = str(row.get("event_time_utc") or row.get("created_utc") or "").strip()
            analyst = str(row.get("analyst_name") or "").strip()
            fleet_unit_identifier = str(row.get("fleet_unit_identifier") or "").strip()
            fleet_unit_name = str(row.get("fleet_unit_name") or "").strip()
            system_name = str(row.get("system_name") or "").strip()
            if fleet_unit_identifier:
                scope_name = f"Unit {fleet_unit_identifier}"
            elif fleet_unit_name:
                scope_name = f"Unit {fleet_unit_name}"
            elif system_name:
                scope_name = f"System {system_name}"
            else:
                scope_name = "Asset"
            note_type = str(row.get("note_type") or "").strip()
            priority = str(row.get("priority") or "").strip()
            title = str(row.get("note_title") or "").strip()
            self.asset_intel_notes_table.setItem(idx, 0, QTableWidgetItem(event_time))
            self.asset_intel_notes_table.setItem(idx, 1, QTableWidgetItem(analyst))
            self.asset_intel_notes_table.setItem(idx, 2, QTableWidgetItem(scope_name))
            self.asset_intel_notes_table.setItem(idx, 3, QTableWidgetItem(note_type))
            self.asset_intel_notes_table.setItem(idx, 4, QTableWidgetItem(priority))
            self.asset_intel_notes_table.setItem(idx, 5, QTableWidgetItem(title))
        self._refresh_asset_intel_note_target_options()
        self._clear_asset_intel_note_form()
        if self.asset_intel_notes_table.rowCount() > 0:
            self.asset_intel_notes_table.setCurrentCell(0, 0)

        self.asset_intel_sources_list.clear()
        for source in sources:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "").strip()
            if not url:
                continue
            ctx = str(source.get("source_context") or "").strip()
            page_no = int(source.get("page_no") or 0)
            label = f"{url}"
            suffix_parts = []
            if ctx:
                suffix_parts.append(ctx)
            if page_no > 0:
                suffix_parts.append(f"p{page_no}")
            if suffix_parts:
                label = f"{url}  [{', '.join(suffix_parts)}]"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, url)
            self.asset_intel_sources_list.addItem(item)

        raw_lines = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            text_value = str(row.get("text") or "").strip()
            block_type = str(row.get("block_type") or "").strip()
            page_no = int(row.get("page_no") or 0)
            if not text_value:
                continue
            prefix = f"[{block_type or 'raw'} p{page_no}] "
            raw_lines.append(prefix + text_value)
        self.asset_intel_raw_text.setPlainText("\n\n".join(raw_lines).strip())
        self._refresh_asset_intel_system_scope_action_button()

    def current_source_id(self):
        return str(self.source_combo.currentData() or "").strip()

    def current_result_item_id(self):
        if not hasattr(self, "results_list"):
            return ""
        item = self.results_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "").strip()

    def current_monitoring_event_row(self):
        if not hasattr(self, "monitoring_events_list"):
            return {}
        item = self.monitoring_events_list.currentItem()
        if item is None:
            return {}
        row = item.data(Qt.UserRole + 1)
        return row if isinstance(row, dict) else {}

    def create_new_layer_on_selection_enabled(self):
        return bool(self.create_new_layer_on_selection.isChecked())

    def current_search_payload(self):
        return {
            "source_id": self.current_source_id(),
            "collection_id": str(self.collection_combo.currentData() or "").strip(),
            "start_date": self.start_date.date().toString("yyyy-MM-dd"),
            "end_date": self.end_date.date().toString("yyyy-MM-dd"),
            "contract_id": self.contract_id.text().strip(),
            "max_cloud_cover": int(self.max_cloud.value()),
            "limit": int(self.limit.value()),
            "satellite_name": self.satellite_name.text().strip(),
            "min_gsd": float(self.min_gsd.value()) if self.min_gsd.value() > 0 else None,
            "max_gsd": float(self.max_gsd.value()) if self.max_gsd.value() > 0 else None,
            "require_full_aoi_overlap": bool(self.require_full_aoi_overlap.isChecked()),
            "remove_existing_layers": bool(self.remove_existing_layers.isChecked()),
        }

    def _emit_search_request(self):
        # Validate date range
        start = self.start_date.date()
        end = self.end_date.date()
        
        if start > end:
            QMessageBox.warning(
                self,
                "Invalid Date Range",
                f"Start date ({start.toString('yyyy-MM-dd')}) cannot be after end date ({end.toString('yyyy-MM-dd')}).\n\n"
                "Please adjust the date range and try again."
            )
            return
        
        if hasattr(self, "download_selected_btn"):
            self.download_selected_btn.setEnabled(False)
        self.search_requested.emit(self.current_search_payload())

    def _emit_download_selected_request(self):
        payload = self.current_download_selected_payload()
        groups = payload.get("groups") if isinstance(payload, dict) else []
        if not isinstance(groups, list) or not groups:
            QMessageBox.information(
                self,
                "Download Selected",
                "Select at least one search result (checked or highlighted) before downloading.",
            )
            return
        self.download_selected_requested.emit(payload)

    def _emit_location_jump_request(self):
        query = self.location_query_input.text().strip()
        if not query:
            self.location_query_input.setFocus()
            return
        self.location_jump_requested.emit(query)

    def _on_location_query_edited(self, text):
        query = str(text or "").strip()
        self._location_suggestions_query = query
        if len(query) < 2:
            self.set_location_suggestions([], for_query=query)
            self._location_suggestions_timer.stop()
            return
        self._location_suggestions_timer.start()

    def _emit_location_suggestions_request(self):
        query = str(self._location_suggestions_query or "").strip()
        if len(query) < 2:
            return
        self.location_suggestions_requested.emit(query)

    def set_location_suggestions(self, suggestions, *, for_query=None):
        if not hasattr(self, "location_query_input"):
            return
        expected_query = str(for_query or "").strip()
        current_query = self.location_query_input.text().strip()
        if expected_query and current_query != expected_query:
            return

        values = []
        seen = set()
        for row in suggestions or []:
            text = str(row or "").strip()
            if text and text not in seen:
                seen.add(text)
                values.append(text)

        self._location_suggestions_model.setStringList(values)
        if values and self.location_query_input.hasFocus():
            self.location_completer.complete()

    def _emit_result_selected(self):
        item = self.results_list.currentItem()
        if item is None:
            return
        item_id = str(item.data(Qt.UserRole) or "").strip()
        if item_id:
            self.result_selected.emit(item_id)
        self._refresh_download_selected_button_state()

    def _on_results_item_changed(self, item):
        if item is None:
            return
        item_id = str(item.data(Qt.UserRole) or "").strip()
        if not item_id:
            return
        if item.checkState() == Qt.Checked:
            self._checked_result_ids.add(item_id)
        else:
            self._checked_result_ids.discard(item_id)
        self._refresh_workflow_source_options()
        self._refresh_download_selected_button_state()

    def _refresh_download_selected_button_state(self):
        if not hasattr(self, "download_selected_btn"):
            return
        has_results = bool(self.results_list.count() > 0) if hasattr(self, "results_list") else False
        groups = self.current_download_selected_payload().get("groups") if has_results else []
        has_selection = bool(isinstance(groups, list) and len(groups) > 0)
        self.download_selected_btn.setEnabled(bool(has_results and has_selection))

    def _show_results_context_menu(self, pos):
        item = self.results_list.itemAt(pos)
        if item is None:
            return

        item_id = str(item.data(Qt.UserRole) or "").strip()
        outcome_id = str(item.data(Qt.UserRole + 1) or "").strip()

        menu = QMenu(self.results_list)
        act_copy_outcome = menu.addAction("Copy Capture Group ID")
        act_copy_item = menu.addAction("Copy Capture ID")
        if not outcome_id:
            act_copy_outcome.setEnabled(False)

        selected = menu.exec_(self.results_list.mapToGlobal(pos))
        if selected == act_copy_outcome and outcome_id:
            QApplication.clipboard().setText(outcome_id)
        elif selected == act_copy_item and item_id:
            QApplication.clipboard().setText(item_id)

    def set_tasking_status(self, text):
        if hasattr(self, "tasking_status_label"):
            self.tasking_status_label.setText(str(text or "").strip() or "Request status: idle")

    def set_tasking_products(self, rows):
        self._tasking_products = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        self._refresh_tasking_product_options()

    def set_tasking_projects(self, projects):
        if not hasattr(self, "tasking_project_combo"):
            return
        current_text = self.tasking_project_combo.currentText().strip()
        self.tasking_project_combo.blockSignals(True)
        self.tasking_project_combo.clear()
        for project in projects or []:
            value = str(project or "").strip()
            if value:
                self.tasking_project_combo.addItem(value)
        if current_text:
            idx = self.tasking_project_combo.findText(current_text)
            if idx >= 0:
                self.tasking_project_combo.setCurrentIndex(idx)
            else:
                self.tasking_project_combo.setEditText(current_text)
        self.tasking_project_combo.blockSignals(False)

    def set_tasking_orders(self, rows):
        self._tasking_orders = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        if not hasattr(self, "tasking_orders_table"):
            return
        table = self.tasking_orders_table
        prior_id = self._current_tasking_order_id()
        sort_column = table.horizontalHeader().sortIndicatorSection()
        sort_order = table.horizontalHeader().sortIndicatorOrder()
        if sort_column < 0 or sort_column >= table.columnCount():
            sort_column = 0
            sort_order = Qt.DescendingOrder

        table.blockSignals(True)
        table.setSortingEnabled(False)
        table.clearContents()
        table.setRowCount(0)

        for idx, row in enumerate(self._tasking_orders):
            order_id = str(row.get("id") or "").strip() or "unknown"
            status = str(row.get("status") or "").strip() or "--"
            created = str(row.get("created_at") or row.get("updated_at") or "").strip() or "--"
            sku = str(row.get("sku") or "").strip() or "--"
            project_name = str(row.get("project_name") or "").strip() or "--"
            order_name = str(row.get("order_name") or "").strip() or "--"
            target_type = str(row.get("target_type") or "").strip() or "--"
            values = [created, status, sku, project_name, order_name, target_type, order_id]
            table.insertRow(idx)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == table.columnCount() - 1:
                    item.setData(Qt.UserRole, order_id)
                    item.setData(Qt.UserRole + 1, row)
                table.setItem(idx, col, item)

        table.setSortingEnabled(True)
        if table.rowCount() > 0:
            table.sortItems(sort_column, sort_order)
        table.blockSignals(False)

        self._refresh_tasking_order_filter_options()
        self._apply_tasking_order_filters(preferred_order_id=prior_id)

    def _refresh_tasking_order_filter_options(self):
        if (
            not hasattr(self, "tasking_orders_status_filter_combo")
            or not hasattr(self, "tasking_orders_project_filter_combo")
        ):
            return
        status_combo = self.tasking_orders_status_filter_combo
        project_combo = self.tasking_orders_project_filter_combo
        prior_status = str(status_combo.currentData() or "").strip()
        prior_project = str(project_combo.currentData() or "").strip()

        statuses = sorted({
            str(row.get("status") or "").strip()
            for row in self._tasking_orders
            if str(row.get("status") or "").strip()
        }, key=lambda value: value.lower())
        projects = sorted({
            str(row.get("project_name") or "").strip()
            for row in self._tasking_orders
            if str(row.get("project_name") or "").strip()
        }, key=lambda value: value.lower())

        status_combo.blockSignals(True)
        status_combo.clear()
        status_combo.addItem("All Statuses", "")
        for value in statuses:
            status_combo.addItem(value, value)
        if prior_status:
            idx = status_combo.findData(prior_status)
            if idx >= 0:
                status_combo.setCurrentIndex(idx)
        status_combo.blockSignals(False)

        project_combo.blockSignals(True)
        project_combo.clear()
        project_combo.addItem("All Missions", "")
        for value in projects:
            project_combo.addItem(value, value)
        if prior_project:
            idx = project_combo.findData(prior_project)
            if idx >= 0:
                project_combo.setCurrentIndex(idx)
        project_combo.blockSignals(False)

    def _update_tasking_orders_meta_label(self, *, visible_count=None):
        if not hasattr(self, "tasking_orders_meta_label"):
            return
        total_count = len(self._tasking_orders)
        if visible_count is None or visible_count == total_count:
            self.tasking_orders_meta_label.setText(
                f"Loaded {total_count} tasking order{'s' if total_count != 1 else ''}."
            )
            return
        self.tasking_orders_meta_label.setText(
            f"Loaded {total_count} tasking order{'s' if total_count != 1 else ''}; showing {visible_count} after filters."
        )

    def _current_tasking_order_id(self):
        if not hasattr(self, "tasking_orders_table"):
            return ""
        table = self.tasking_orders_table
        selection_model = table.selectionModel()
        selected_rows = selection_model.selectedRows() if selection_model is not None else []
        if not selected_rows:
            return ""
        row_index = selected_rows[0].row()
        id_item = table.item(row_index, table.columnCount() - 1)
        if id_item is None:
            return ""
        return str(id_item.data(Qt.UserRole) or "").strip()

    def _select_tasking_order_row(self, order_id):
        if not order_id or not hasattr(self, "tasking_orders_table"):
            return False
        table = self.tasking_orders_table
        for row_index in range(table.rowCount()):
            if table.isRowHidden(row_index):
                continue
            id_item = table.item(row_index, table.columnCount() - 1)
            if id_item is None:
                continue
            if str(id_item.data(Qt.UserRole) or "").strip() == order_id:
                table.selectRow(row_index)
                return True
        return False

    def _select_first_visible_tasking_order(self):
        if not hasattr(self, "tasking_orders_table"):
            return False
        table = self.tasking_orders_table
        for row_index in range(table.rowCount()):
            if table.isRowHidden(row_index):
                continue
            table.selectRow(row_index)
            return True
        table.clearSelection()
        return False

    def _apply_tasking_order_filters(self, preferred_order_id=""):
        if not hasattr(self, "tasking_orders_table"):
            return

        table = self.tasking_orders_table
        selected_order_id = str(preferred_order_id or "").strip() or self._current_tasking_order_id()
        query = ""
        status_filter = ""
        project_filter = ""
        if hasattr(self, "tasking_orders_filter_input"):
            query = str(self.tasking_orders_filter_input.text() or "").strip().lower()
        if hasattr(self, "tasking_orders_status_filter_combo"):
            status_filter = str(self.tasking_orders_status_filter_combo.currentData() or "").strip().lower()
        if hasattr(self, "tasking_orders_project_filter_combo"):
            project_filter = str(self.tasking_orders_project_filter_combo.currentData() or "").strip().lower()

        table.blockSignals(True)
        visible_count = 0
        for row_index in range(table.rowCount()):
            id_item = table.item(row_index, table.columnCount() - 1)
            row_payload = id_item.data(Qt.UserRole + 1) if id_item is not None else {}
            row_payload = row_payload if isinstance(row_payload, dict) else {}
            status = str(row_payload.get("status") or "").strip().lower()
            project_name = str(row_payload.get("project_name") or "").strip().lower()
            search_values = [
                str(row_payload.get("created_at") or row_payload.get("updated_at") or "").strip().lower(),
                status,
                str(row_payload.get("sku") or "").strip().lower(),
                project_name,
                str(row_payload.get("order_name") or "").strip().lower(),
                str(row_payload.get("target_type") or "").strip().lower(),
                str(row_payload.get("id") or "").strip().lower(),
            ]

            is_visible = True
            if status_filter and status != status_filter:
                is_visible = False
            if is_visible and project_filter and project_name != project_filter:
                is_visible = False
            if is_visible and query and query not in " | ".join(search_values):
                is_visible = False

            table.setRowHidden(row_index, not is_visible)
            if is_visible:
                visible_count += 1
        table.blockSignals(False)

        self._update_tasking_orders_meta_label(visible_count=visible_count)
        if visible_count == 0:
            table.clearSelection()
            self.set_tasking_order_detail(None)
            return
        if selected_order_id and self._select_tasking_order_row(selected_order_id):
            return
        if not self._select_first_visible_tasking_order():
            self.set_tasking_order_detail(None)

    def set_tasking_order_detail(self, row):
        if not hasattr(self, "tasking_order_detail"):
            return
        if not isinstance(row, dict):
            self.tasking_order_detail.setPlainText("Select a tasking order to view details.")
            return
        self.tasking_order_detail.setPlainText(json.dumps(row, indent=2, sort_keys=True))

    def _refresh_tasking_product_options(self):
        if not hasattr(self, "tasking_product_combo"):
            return
        target_type = str(self.tasking_target_type_combo.currentData() or "point").strip().lower()
        prior_sku = str(self.tasking_product_combo.currentData() or "").strip()
        self.tasking_product_combo.blockSignals(True)
        self.tasking_product_combo.clear()
        matches = []
        for row in self._tasking_products:
            target_types = row.get("target_types")
            target_types = target_types if isinstance(target_types, list) else []
            normalized_targets = {str(value or "").strip().lower() for value in target_types}
            if normalized_targets and target_type not in normalized_targets:
                continue
            sku = str(row.get("sku") or "").strip()
            if not sku:
                continue
            label = str(row.get("label") or sku).strip()
            notes = str(row.get("notes") or "").strip()
            self.tasking_product_combo.addItem(f"{label} ({sku})", sku)
            idx = self.tasking_product_combo.count() - 1
            if notes:
                self.tasking_product_combo.setItemData(idx, notes, Qt.ToolTipRole)
            matches.append(sku)
        if self.tasking_product_combo.count() == 0:
            self.tasking_product_combo.addItem("No tasking products available", "")
        if prior_sku and prior_sku in matches:
            idx = self.tasking_product_combo.findData(prior_sku)
            if idx >= 0:
                self.tasking_product_combo.setCurrentIndex(idx)
        self.tasking_product_combo.blockSignals(False)

    def _on_tasking_target_type_changed(self):
        if not hasattr(self, "tasking_target_type_combo") or not hasattr(self, "tasking_geometry_mode_combo"):
            return
        target_type = str(self.tasking_target_type_combo.currentData() or "point").strip().lower()
        prior_mode = str(self.tasking_geometry_mode_combo.currentData() or "").strip()
        self.tasking_geometry_mode_combo.blockSignals(True)
        self.tasking_geometry_mode_combo.clear()
        if target_type == "area":
            self.tasking_geometry_mode_combo.addItem("Current Map Extent", "map_extent")
            self.tasking_geometry_mode_combo.addItem("Selected Result Footprint", "selected_result_footprint")
            self.tasking_cadence_label.setText("Refresh Cadence")
            self.tasking_cadence_input.setPlaceholderText("optional (e.g. P15D)")
        else:
            self.tasking_geometry_mode_combo.addItem("Map Center", "map_center")
            self.tasking_geometry_mode_combo.addItem("Selected Result Centroid", "selected_result_centroid")
            self.tasking_cadence_label.setText("Revisit Cadence")
            self.tasking_cadence_input.setPlaceholderText("optional (e.g. P15D)")
        if prior_mode:
            idx = self.tasking_geometry_mode_combo.findData(prior_mode)
            if idx >= 0:
                self.tasking_geometry_mode_combo.setCurrentIndex(idx)
        self.tasking_geometry_mode_combo.blockSignals(False)
        self._refresh_tasking_product_options()

    def _emit_tasking_submit_request(self):
        target_type = str(self.tasking_target_type_combo.currentData() or "").strip().lower()
        geometry_mode = str(self.tasking_geometry_mode_combo.currentData() or "").strip()
        order_name = self.tasking_order_name_input.text().strip()
        project_name = self.tasking_project_combo.currentText().strip()
        sku = str(self.tasking_product_combo.currentData() or "").strip()
        cadence = self.tasking_cadence_input.text().strip()
        start_dt = self.tasking_start_datetime.dateTime()
        end_dt = self.tasking_end_datetime.dateTime()
        if start_dt > end_dt:
            QMessageBox.warning(self, "Collection Requests", "Start time cannot be after end time.")
            return
        if not order_name:
            QMessageBox.warning(self, "Collection Requests", "Request name is required.")
            return
        if not sku:
            QMessageBox.warning(self, "Collection Requests", "Select a collection package.")
            return
        payload = {
            "target_type": target_type,
            "geometry_mode": geometry_mode,
            "order_name": order_name,
            "project_name": project_name,
            "sku": sku,
            "start_date": start_dt.toUTC().toString("yyyy-MM-ddTHH:mm:ss'Z'"),
            "end_date": end_dt.toUTC().toString("yyyy-MM-ddTHH:mm:ss'Z'"),
            "cadence": cadence,
            "contract_id": self.contract_id.text().strip(),
        }
        self.tasking_submit_requested.emit(payload)

    def set_mosaic_create_status(self, text):
        if hasattr(self, "mosaic_create_status_label"):
            self.mosaic_create_status_label.setText(str(text or "").strip() or "Mosaic create: idle.")

    def set_mosaic_breakdown_rows(self, rows):
        self._mosaic_breakdown_rows = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        if not hasattr(self, "mosaic_breakdown_table"):
            return
        table = self.mosaic_breakdown_table
        table.setRowCount(len(self._mosaic_breakdown_rows))
        total_area_km2 = 0.0
        for idx, row in enumerate(self._mosaic_breakdown_rows):
            tile_id = str(row.get("tile_id") or "").strip()
            area_km2 = float(row.get("clipped_area_km2") or 0.0)
            total_area_km2 += max(0.0, area_km2)
            grid_x = str(row.get("grid_x") if row.get("grid_x") is not None else "")
            grid_y = str(row.get("grid_y") if row.get("grid_y") is not None else "")
            tile_item = QTableWidgetItem(tile_id)
            tile_item.setData(Qt.UserRole, tile_id)
            tile_item.setData(Qt.UserRole + 1, row)
            table.setItem(idx, 0, tile_item)
            table.setItem(idx, 1, QTableWidgetItem(f"{area_km2:.4f}"))
            table.setItem(idx, 2, QTableWidgetItem(grid_x))
            table.setItem(idx, 3, QTableWidgetItem(grid_y))
        if hasattr(self, "mosaic_estimated_area_label"):
            self.mosaic_estimated_area_label.setText(f"Total clipped area: {total_area_km2:,.2f} km2")

    def set_mosaic_estimated_price(self, price_usd):
        if hasattr(self, "mosaic_estimated_price_label"):
            try:
                value = float(price_usd or 0.0)
            except Exception:
                value = 0.0
            self.mosaic_estimated_price_label.setText(f"Estimated price: ${value:,.2f}")

    def set_mosaic_projects(self, project_ids):
        if not hasattr(self, "mosaic_tracking_project_combo"):
            return
        prior = str(self.mosaic_tracking_project_combo.currentData() or "").strip()
        self.mosaic_tracking_project_combo.blockSignals(True)
        self.mosaic_tracking_project_combo.clear()
        rows = [str(value or "").strip() for value in (project_ids or []) if str(value or "").strip()]
        for value in rows:
            self.mosaic_tracking_project_combo.addItem(value, value)
        if rows:
            idx = self.mosaic_tracking_project_combo.findData(prior) if prior else -1
            if idx >= 0:
                self.mosaic_tracking_project_combo.setCurrentIndex(idx)
            else:
                self.mosaic_tracking_project_combo.setCurrentIndex(0)
        self.mosaic_tracking_project_combo.blockSignals(False)

    def set_mosaic_current_project(self, project_id):
        if not hasattr(self, "mosaic_tracking_project_combo"):
            return
        value = str(project_id or "").strip()
        if not value:
            return
        idx = self.mosaic_tracking_project_combo.findData(value)
        if idx < 0:
            self.mosaic_tracking_project_combo.addItem(value, value)
            idx = self.mosaic_tracking_project_combo.findData(value)
        if idx >= 0:
            self.mosaic_tracking_project_combo.setCurrentIndex(idx)

    def current_mosaic_project_id(self):
        if not hasattr(self, "mosaic_tracking_project_combo"):
            return ""
        return str(self.mosaic_tracking_project_combo.currentData() or "").strip()

    def current_mosaic_selected_tile_id(self):
        if not hasattr(self, "mosaic_tracking_table"):
            return ""
        table = self.mosaic_tracking_table
        selection_model = table.selectionModel()
        selected_rows = selection_model.selectedRows() if selection_model is not None else []
        if not selected_rows:
            return ""
        row_index = selected_rows[0].row()
        item = table.item(row_index, 0)
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "").strip()

    def select_mosaic_tracking_tile(self, tile_id, *, scroll=True):
        tile_key = str(tile_id or "").strip()
        if not tile_key or not hasattr(self, "mosaic_tracking_table"):
            return False
        table = self.mosaic_tracking_table
        target_row = -1
        target_item = None
        for row_idx in range(table.rowCount()):
            item = table.item(row_idx, 0)
            if item is None:
                continue
            row_tile_id = str(item.data(Qt.UserRole) or "").strip()
            if row_tile_id == tile_key:
                target_row = row_idx
                target_item = item
                break
        if target_row < 0:
            return False

        self._mosaic_tracking_selection_guard = True
        table.blockSignals(True)
        try:
            table.clearSelection()
            table.selectRow(target_row)
            table.setCurrentCell(target_row, 0)
        finally:
            table.blockSignals(False)
            self._mosaic_tracking_selection_guard = False

        if bool(scroll) and target_item is not None:
            table.scrollToItem(target_item)
        return True

    def set_mosaic_tracking_rows(self, rows):
        self._mosaic_tracking_rows = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        if not hasattr(self, "mosaic_tracking_table"):
            return
        table = self.mosaic_tracking_table
        table.setRowCount(len(self._mosaic_tracking_rows))
        for idx, row in enumerate(self._mosaic_tracking_rows):
            tile_id = str(row.get("tile_id") or "").strip()
            area_km2 = float(row.get("clipped_area_km2") or 0.0)
            api_status = str(row.get("api_status") or "").strip() or "--"
            qa_status = str(row.get("qa_status") or "").strip() or "--"
            latest_collection_id = str(row.get("latest_collection_id") or "").strip() or "--"
            attempt_count = int(row.get("attempt_count") or 0)
            preview_allowed = should_enable_preview(
                api_status=api_status,
                latest_collection_id=latest_collection_id if latest_collection_id != "--" else "",
            )

            tile_item = QTableWidgetItem(tile_id)
            tile_item.setData(Qt.UserRole, tile_id)
            tile_item.setData(Qt.UserRole + 1, row)
            table.setItem(idx, 0, tile_item)
            table.setItem(idx, 1, QTableWidgetItem(f"{area_km2:,.2f}"))
            table.setItem(idx, 2, QTableWidgetItem(api_status))
            table.setItem(idx, 3, QTableWidgetItem(qa_status))
            table.setItem(idx, 4, QTableWidgetItem(latest_collection_id))
            table.setItem(idx, 5, QTableWidgetItem(str(attempt_count)))

            preview_checkbox = QCheckBox()
            preview_checkbox.setEnabled(preview_allowed)
            if preview_allowed:
                preview_checkbox.setToolTip("Toggle imagery preview for this completed collection.")
            else:
                preview_checkbox.setToolTip("Preview becomes available when API status is Completed.")
            should_check = (
                preview_allowed
                and bool(self._mosaic_tracking_preview_tile_id)
                and self._mosaic_tracking_preview_tile_id == tile_id
            )
            preview_checkbox.setChecked(should_check)
            preview_checkbox.toggled.connect(
                lambda checked=False, tile_key=tile_id: self._on_mosaic_tracking_preview_toggled(tile_key, checked)
            )
            table.setCellWidget(idx, 6, preview_checkbox)

            accept_btn = QPushButton("Accept")
            accept_btn.clicked.connect(
                lambda _checked=False, tile_key=tile_id: self._emit_mosaic_mark_accepted_for_tile(tile_key)
            )
            if qa_status.strip().lower() == "accepted":
                accept_btn.setEnabled(False)
            table.setCellWidget(idx, 7, accept_btn)

            retask_btn = QPushButton("Re-Task")
            retask_btn.clicked.connect(
                lambda _checked=False, tile_key=tile_id: self._emit_mosaic_retask_for_tile(tile_key)
            )
            if qa_status.strip().lower() == "accepted":
                retask_btn.setEnabled(False)
            table.setCellWidget(idx, 8, retask_btn)

            cancel_btn = QPushButton("Cancel")
            cancel_btn.clicked.connect(
                lambda _checked=False, tile_key=tile_id: self._emit_mosaic_cancel_for_tile(tile_key)
            )
            if qa_status.strip().lower() == "accepted" or latest_collection_id == "--":
                cancel_btn.setEnabled(False)
            table.setCellWidget(idx, 9, cancel_btn)

    def set_mosaic_tracking_preview_tile(self, tile_id):
        tile_key = str(tile_id or "").strip()
        self._mosaic_tracking_preview_tile_id = tile_key
        if not hasattr(self, "mosaic_tracking_table"):
            return
        table = self.mosaic_tracking_table
        self._mosaic_tracking_preview_guard = True
        try:
            for row_idx in range(table.rowCount()):
                row_item = table.item(row_idx, 0)
                row_tile_id = str(row_item.data(Qt.UserRole) or "").strip() if row_item is not None else ""
                preview_widget = table.cellWidget(row_idx, 6)
                if not isinstance(preview_widget, QCheckBox):
                    continue
                should_check = bool(tile_key and row_tile_id == tile_key and preview_widget.isEnabled())
                preview_widget.blockSignals(True)
                preview_widget.setChecked(should_check)
                preview_widget.blockSignals(False)
        finally:
            self._mosaic_tracking_preview_guard = False

    def _on_mosaic_tracking_preview_toggled(self, tile_id, checked):
        if bool(getattr(self, "_mosaic_tracking_preview_guard", False)):
            return
        tile_key = str(tile_id or "").strip()
        enabled = bool(checked)
        if enabled:
            self.set_mosaic_tracking_preview_tile(tile_key)
        elif self._mosaic_tracking_preview_tile_id == tile_key:
            self.set_mosaic_tracking_preview_tile("")
        self.mosaic_tracking_preview_toggled.emit(
            {
                "project_id": self.current_mosaic_project_id(),
                "tile_id": tile_key,
                "enabled": enabled,
            }
        )

    def set_mosaic_tracking_status(self, text):
        if hasattr(self, "mosaic_tracking_status_label"):
            self.mosaic_tracking_status_label.setText(str(text or "").strip() or "Mosaic tracking: idle.")

    def _on_mosaic_aoi_source_changed(self):
        if not hasattr(self, "mosaic_aoi_source_combo"):
            return
        mode = str(self.mosaic_aoi_source_combo.currentData() or "map_extent").strip().lower()
        use_layer = mode == "polygon_layer"
        if hasattr(self, "mosaic_aoi_layer_combo"):
            self.mosaic_aoi_layer_combo.setEnabled(use_layer)
        if hasattr(self, "mosaic_aoi_layer_refresh_btn"):
            self.mosaic_aoi_layer_refresh_btn.setEnabled(use_layer)

    def _refresh_mosaic_polygon_layer_options(self):
        if not hasattr(self, "mosaic_aoi_layer_combo"):
            return
        prior = str(self.mosaic_aoi_layer_combo.currentData() or "").strip()
        self.mosaic_aoi_layer_combo.blockSignals(True)
        self.mosaic_aoi_layer_combo.clear()
        for row in self._project_polygon_layer_options():
            self.mosaic_aoi_layer_combo.addItem(row.get("name"), row.get("id"))
        if prior:
            idx = self.mosaic_aoi_layer_combo.findData(prior)
            if idx >= 0:
                self.mosaic_aoi_layer_combo.setCurrentIndex(idx)
        self.mosaic_aoi_layer_combo.blockSignals(False)

    def _emit_mosaic_breakdown_request(self):
        payload = {
            "aoi_source": str(self.mosaic_aoi_source_combo.currentData() or "map_extent").strip(),
            "aoi_layer_id": str(self.mosaic_aoi_layer_combo.currentData() or "").strip(),
        }
        self.mosaic_breakdown_requested.emit(payload)

    def _emit_mosaic_accept_request(self):
        project_id = str(self.mosaic_project_id_input.text() or "").strip() if hasattr(self, "mosaic_project_id_input") else ""
        if not project_id:
            QMessageBox.warning(self, "Mosaic", "Project ID is required.")
            return
        payload = {
            "project_id": project_id,
            "add_tasking": bool(
                self.mosaic_add_tasking_checkbox.isChecked()
                if hasattr(self, "mosaic_add_tasking_checkbox")
                else True
            ),
        }
        self.mosaic_accept_requested.emit(payload)

    def _on_mosaic_tracking_project_changed(self, _index=None):
        project_id = self.current_mosaic_project_id()
        self.mosaic_tracking_project_changed.emit(project_id)
        if hasattr(self, "mosaic_show_tiling_checkbox") and bool(self.mosaic_show_tiling_checkbox.isChecked()):
            self._emit_mosaic_show_tiling_request(True)

    def _on_mosaic_tracking_selection_changed(self):
        if bool(getattr(self, "_mosaic_tracking_selection_guard", False)):
            return
        self.mosaic_tracking_tile_selected.emit(
            {
                "project_id": self.current_mosaic_project_id(),
                "tile_id": self.current_mosaic_selected_tile_id(),
            }
        )

    def _emit_mosaic_refresh_status_request(self):
        payload = {
            "project_id": self.current_mosaic_project_id(),
        }
        self.mosaic_refresh_status_requested.emit(payload)

    def _emit_mosaic_delete_request(self):
        project_id = self.current_mosaic_project_id()
        if not project_id:
            QMessageBox.warning(self, "Mosaic", "Select a project first.")
            return
        decision = QMessageBox.question(
            self,
            "Delete Mosaic",
            (
                f"Delete Mosaic project '{project_id}'?\n\n"
                "This removes the entire project directory under the campaign folder."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if decision != QMessageBox.Yes:
            return
        self.mosaic_delete_requested.emit({"project_id": project_id})

    def _emit_mosaic_show_tiling_request(self, checked=None):
        enabled = bool(checked)
        if checked is None and hasattr(self, "mosaic_show_tiling_checkbox"):
            enabled = bool(self.mosaic_show_tiling_checkbox.isChecked())
        project_id = self.current_mosaic_project_id()
        if enabled and not project_id:
            QMessageBox.warning(self, "Mosaic", "Select a project first.")
            if hasattr(self, "mosaic_show_tiling_checkbox"):
                self.mosaic_show_tiling_checkbox.blockSignals(True)
                self.mosaic_show_tiling_checkbox.setChecked(False)
                self.mosaic_show_tiling_checkbox.blockSignals(False)
            return
        self.mosaic_show_tiling_requested.emit({"project_id": project_id, "enabled": bool(enabled)})

    def _emit_mosaic_mark_accepted_request(self):
        project_id = self.current_mosaic_project_id()
        tile_id = self.current_mosaic_selected_tile_id()
        if not project_id or not tile_id:
            QMessageBox.warning(self, "Mosaic", "Select a project and tile first.")
            return
        self._emit_mosaic_mark_accepted_for_tile(tile_id)

    def _emit_mosaic_mark_accepted_for_tile(self, tile_id):
        project_id = self.current_mosaic_project_id()
        tile_key = str(tile_id or "").strip()
        if not project_id or not tile_key:
            QMessageBox.warning(self, "Mosaic", "Select a project and tile first.")
            return
        self.mosaic_mark_accepted_requested.emit(
            {
                "project_id": project_id,
                "tile_id": tile_key,
            }
        )

    def _emit_mosaic_retask_request(self):
        project_id = self.current_mosaic_project_id()
        tile_id = self.current_mosaic_selected_tile_id()
        if not project_id or not tile_id:
            QMessageBox.warning(self, "Mosaic", "Select a project and tile first.")
            return
        self._emit_mosaic_retask_for_tile(tile_id)

    def _emit_mosaic_retask_for_tile(self, tile_id):
        project_id = self.current_mosaic_project_id()
        tile_key = str(tile_id or "").strip()
        if not project_id or not tile_key:
            QMessageBox.warning(self, "Mosaic", "Select a project and tile first.")
            return
        self.mosaic_retask_requested.emit(
            {
                "project_id": project_id,
                "tile_id": tile_key,
            }
        )

    def _emit_mosaic_cancel_for_tile(self, tile_id):
        project_id = self.current_mosaic_project_id()
        tile_key = str(tile_id or "").strip()
        if not project_id or not tile_key:
            QMessageBox.warning(self, "Mosaic", "Select a project and tile first.")
            return
        self.mosaic_cancel_requested.emit(
            {
                "project_id": project_id,
                "tile_id": tile_key,
            }
        )

    def _on_tasking_order_selection_changed(self):
        if not hasattr(self, "tasking_orders_table"):
            return
        table = self.tasking_orders_table
        selection_model = table.selectionModel()
        selected_rows = selection_model.selectedRows() if selection_model is not None else []
        if not selected_rows:
            self._tasking_selected_order_id = ""
            self.set_tasking_order_detail(None)
            return
        row_index = selected_rows[0].row()
        id_item = table.item(row_index, table.columnCount() - 1)
        if id_item is None:
            self._tasking_selected_order_id = ""
            self.set_tasking_order_detail(None)
            return
        row = id_item.data(Qt.UserRole + 1)
        if isinstance(row, dict):
            self.set_tasking_order_detail(row)
        order_id = str(id_item.data(Qt.UserRole) or "").strip()
        if order_id and order_id != self._tasking_selected_order_id:
            self._tasking_selected_order_id = order_id
            self.tasking_order_selected.emit(order_id)

    def set_monitoring_status(self, text):
        if hasattr(self, "monitoring_status_label"):
            self.monitoring_status_label.setText(str(text or "").strip() or "Watch status: idle")

    def set_monitoring_subscriptions(self, rows):
        self._monitoring_subscriptions = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        if not hasattr(self, "monitoring_subscriptions_list"):
            return
        self.monitoring_subscriptions_list.clear()
        for row in self._monitoring_subscriptions:
            sub_id = str(row.get("subscription_id") or row.get("id") or "").strip() or "unknown"
            source_id = str(row.get("source_id") or "").strip() or "--"
            enabled = bool(row.get("enabled", True))
            name = str(row.get("name") or "").strip() or "--"
            label = f"{name} | {source_id} | {'enabled' if enabled else 'disabled'} | {sub_id}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, sub_id)
            item.setData(Qt.UserRole + 1, row)
            self.monitoring_subscriptions_list.addItem(item)

    def set_monitoring_events(self, rows):
        self._monitoring_events = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        if not hasattr(self, "monitoring_events_list"):
            return
        self.monitoring_events_list.clear()
        for row in self._monitoring_events:
            event_id = str(row.get("event_id") or row.get("id") or "").strip() or "unknown"
            status = str(row.get("status") or "").strip() or "--"
            event_type = str(row.get("event_type") or "").strip() or "--"
            source_id = str(row.get("source_id") or "").strip() or "--"
            created = str(row.get("created_at") or row.get("created") or "").strip() or "--"
            scene_id = str(row.get("scene_id") or "").strip()
            label = f"{created} | {status} | {event_type} | {source_id} | {scene_id or '--'} | {event_id}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, event_id)
            item.setData(Qt.UserRole + 1, row)
            self.monitoring_events_list.addItem(item)

    def set_monitoring_cues(self, rows):
        self._monitoring_cues = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        if not hasattr(self, "monitoring_cues_list"):
            return
        self.monitoring_cues_list.clear()
        for row in self._monitoring_cues:
            cue_id = str(row.get("cue_id") or row.get("id") or "").strip() or "unknown"
            status = str(row.get("status") or "").strip() or "--"
            priority = str(row.get("priority") or "").strip() or "--"
            source_id = str(row.get("source_id") or "").strip() or "--"
            created = str(row.get("created_at") or row.get("created") or "").strip() or "--"
            label = f"{created} | {status} | {priority} | {source_id} | {cue_id}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, cue_id)
            item.setData(Qt.UserRole + 1, row)
            self.monitoring_cues_list.addItem(item)

    def _on_monitoring_item_selected(self):
        current = None
        for widget_name in ("monitoring_events_list", "monitoring_subscriptions_list", "monitoring_cues_list"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            item = widget.currentItem()
            if item is not None:
                current = item
                break
        if current is None:
            self.monitoring_detail_text.setPlainText("Select a monitoring row to inspect details.")
            return
        row = current.data(Qt.UserRole + 1)
        if isinstance(row, dict):
            self.monitoring_detail_text.setPlainText(json.dumps(row, indent=2, sort_keys=True))
        else:
            self.monitoring_detail_text.setPlainText("")

    def _emit_monitoring_refresh_request(self):
        payload = {
            "source_id": str(self.monitoring_source_combo.currentData() or "").strip(),
            "status": str(self.monitoring_status_filter_combo.currentData() or "").strip(),
        }
        self.monitoring_refresh_requested.emit(payload)

    def _emit_monitoring_create_subscription_request(self):
        raw_filters = self.monitoring_filters_input.text().strip()
        filters = {}
        if raw_filters:
            try:
                parsed = json.loads(raw_filters)
            except Exception as exc:
                QMessageBox.warning(self, "Watch & Alerts", f"Invalid filters JSON: {exc}")
                return
            if not isinstance(parsed, dict):
                QMessageBox.warning(self, "Watch & Alerts", "Filters JSON must be an object.")
                return
            filters = parsed
        collection_ids = [
            value.strip()
            for value in self.monitoring_collection_ids_input.text().split(",")
            if value.strip()
        ]
        selected_source = str(self.monitoring_source_combo.currentData() or "").strip()
        if not selected_source:
            selected_source = str(self.current_source_id() or "").strip()
        payload = {
            "source_id": selected_source or "merlin-s2",
            "name": self.monitoring_name_input.text().strip(),
            "collection_ids": collection_ids,
            "geometry_mode": str(self.monitoring_geometry_mode_combo.currentData() or "").strip(),
            "filters": filters,
            "enabled": bool(self.monitoring_enabled_checkbox.isChecked()),
        }
        self.monitoring_create_subscription_requested.emit(payload)

    def _emit_monitoring_ack_event_request(self):
        item = self.monitoring_events_list.currentItem()
        if item is None:
            QMessageBox.warning(self, "Watch & Alerts", "Select an event first.")
            return
        event_id = str(item.data(Qt.UserRole) or "").strip()
        if not event_id:
            QMessageBox.warning(self, "Watch & Alerts", "Selected event does not have an id.")
            return
        self.monitoring_ack_event_requested.emit(event_id)

    def _emit_monitoring_create_cue_request(self):
        item = self.monitoring_events_list.currentItem()
        if item is None:
            QMessageBox.warning(self, "Watch & Alerts", "Select an event first.")
            return
        event_id = str(item.data(Qt.UserRole) or "").strip()
        if not event_id:
            QMessageBox.warning(self, "Watch & Alerts", "Selected event does not have an id.")
            return
        selected_source = str(self.monitoring_source_combo.currentData() or "").strip()
        if not selected_source:
            selected_source = str(self.current_source_id() or "").strip()
        payload = {
            "event_id": event_id,
            "source_id": selected_source or "merlin-s2",
            "priority": str(self.monitoring_cue_priority_combo.currentData() or "medium").strip(),
            "geometry_mode": str(self.monitoring_cue_geometry_mode_combo.currentData() or "").strip(),
            "status": "queued_review",
        }
        self.monitoring_create_cue_requested.emit(payload)

    def set_simulation_constellation(self, config):
        self._simulation_constellation_config = self._normalize_simulation_config(config)
        satellites = self._simulation_constellation_config.get("satellites", [])
        self._simulation_manual_selected_ids = {
            str(row.get("satellite_id") or "").strip()
            for row in satellites
            if bool(row.get("enabled", True)) and str(row.get("satellite_id") or "").strip()
        }
        if hasattr(self, "simulation_satellite_count_spin"):
            self.simulation_satellite_count_spin.setMaximum(max(1, len(satellites)))
            if self.simulation_satellite_count_spin.value() > len(satellites):
                self.simulation_satellite_count_spin.setValue(max(1, len(satellites)))
        self._refresh_simulation_satellite_table()
        self._on_simulation_selection_mode_changed()

    def set_simulation_status(self, text):
        if hasattr(self, "simulation_status_label"):
            self.simulation_status_label.setText(str(text or "").strip() or "Simulation status: idle")

    def set_simulation_progress(self, current, total, text):
        if hasattr(self, "simulation_progress_label"):
            self.simulation_progress_label.setText(str(text or "").strip() or "")
        if not hasattr(self, "simulation_progress_bar"):
            return
        try:
            cur = int(current or 0)
        except Exception:
            cur = 0
        try:
            tot = int(total or 0)
        except Exception:
            tot = 0
        tot = max(1, tot)
        cur = max(0, min(cur, tot))
        self.simulation_progress_bar.setRange(0, tot)
        self.simulation_progress_bar.setValue(cur)

    def set_simulation_summary(self, payload):
        row = payload if isinstance(payload, dict) else {}
        try:
            aoi_area_km2 = float(row.get("aoi_area_km2", 0.0) or 0.0)
        except Exception:
            aoi_area_km2 = 0.0
        try:
            unique_area_km2 = float(row.get("total_unique_area_km2", 0.0) or 0.0)
        except Exception:
            unique_area_km2 = 0.0
        coverage_pct = 0.0
        if aoi_area_km2 > 0.0:
            coverage_pct = max(0.0, min(100.0, (unique_area_km2 / aoi_area_km2) * 100.0))
        if hasattr(self, "simulation_summary_aoi_label"):
            self.simulation_summary_aoi_label.setText(
                f"AOI area: {aoi_area_km2:,.2f} km2"
            )
        if hasattr(self, "simulation_summary_unique_label"):
            self.simulation_summary_unique_label.setText(
                f"Total unique area covered: {unique_area_km2:,.2f} km2"
            )
        if hasattr(self, "simulation_summary_coverage_label"):
            self.simulation_summary_coverage_label.setText(
                f"AOI covered: {coverage_pct:,.2f}%"
            )
        if hasattr(self, "simulation_summary_total_label"):
            self.simulation_summary_total_label.setText(
                f"Total area imaged: {float(row.get('total_area_imaged_km2', 0.0) or 0.0):,.2f} km2"
            )
        if hasattr(self, "simulation_summary_passes_label"):
            self.simulation_summary_passes_label.setText(
                f"Total collection passes: {int(row.get('total_collection_passes', 0) or 0)}"
            )

    def show_simulation_results_tab(self):
        tabs = getattr(self, "simulation_tabs", None)
        if tabs is None:
            return
        idx = tabs.indexOf(getattr(self, "simulation_results_tab", None))
        if idx >= 0:
            tabs.setCurrentIndex(idx)

    def current_simulation_scenario_id(self):
        combo = getattr(self, "simulation_scenario_combo", None)
        if combo is None:
            return "coverage_analysis"
        return str(combo.currentData() or "coverage_analysis").strip() or "coverage_analysis"

    def set_simulation_target_point(self, lat, lon, source="manual", label=""):
        try:
            lat_value = float(lat)
            lon_value = float(lon)
        except Exception:
            return
        source_value = str(source or "manual").strip() or "manual"
        label_value = str(label or "").strip()
        self._simulation_target_point = {
            "lat": float(lat_value),
            "lon": float(lon_value),
            "source": source_value,
            "label": label_value,
        }
        if hasattr(self, "simulation_target_lat_spin"):
            self.simulation_target_lat_spin.blockSignals(True)
            self.simulation_target_lat_spin.setValue(float(lat_value))
            self.simulation_target_lat_spin.blockSignals(False)
        if hasattr(self, "simulation_target_lon_spin"):
            self.simulation_target_lon_spin.blockSignals(True)
            self.simulation_target_lon_spin.setValue(float(lon_value))
            self.simulation_target_lon_spin.blockSignals(False)
        if hasattr(self, "simulation_target_source_label"):
            self.simulation_target_source_label.setText(f"Target source: {source_value}")
        if hasattr(self, "simulation_target_label_input"):
            self.simulation_target_label_input.blockSignals(True)
            self.simulation_target_label_input.setText(label_value)
            self.simulation_target_label_input.blockSignals(False)

    def set_simulation_revisit_summary(self, payload):
        row = payload if isinstance(payload, dict) else {}
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        try:
            target_lat = float(target.get("lat"))
            target_lon = float(target.get("lon"))
            target_text = f"{target_lat:.6f}, {target_lon:.6f}"
        except Exception:
            target_text = "--, --"

        def _fmt_float(value, suffix=""):
            try:
                number = float(value)
                return f"{number:,.2f}{suffix}"
            except Exception:
                return "--"

        def _fmt_days(value):
            try:
                minutes = float(value)
            except Exception:
                return "--"
            return f"{(minutes / 1440.0):,.3f} d"

        total_events = int(row.get("total_collection_events", 0) or 0)
        min_revisit = _fmt_float(row.get("min_revisit_min"), " min")
        min_revisit_days = _fmt_days(row.get("min_revisit_min"))
        mean_revisit = _fmt_float(row.get("mean_revisit_min"), " min")
        mean_revisit_days = _fmt_days(row.get("mean_revisit_min"))
        max_revisit = _fmt_float(row.get("max_revisit_min"), " min")
        max_revisit_days = _fmt_days(row.get("max_revisit_min"))
        longest_gap = _fmt_float(row.get("longest_gap_min"), " min")
        longest_gap_days = _fmt_days(row.get("longest_gap_min"))

        if hasattr(self, "simulation_revisit_group"):
            self.simulation_revisit_group.setTitle(f"Point Revisit Summary ({target_text}):")
        if hasattr(self, "simulation_revisit_events_group"):
            self.simulation_revisit_events_group.setTitle(
                f"Point Revisit Events : {total_events} Collections"
            )

        table = getattr(self, "simulation_revisit_summary_table", None)
        if table is None:
            return
        rows = [
            ("Min revisit", min_revisit, min_revisit_days),
            ("Mean revisit", mean_revisit, mean_revisit_days),
            ("Max revisit", max_revisit, max_revisit_days),
            ("Longest gap", longest_gap, longest_gap_days),
        ]
        table.setRowCount(len(rows))
        for row_idx, values in enumerate(rows):
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                table.setItem(row_idx, col_idx, item)
        table.resizeRowsToContents()

    def set_simulation_revisit_events(self, rows):
        table = getattr(self, "simulation_revisit_events_table", None)
        if table is None:
            return
        event_rows = [row for row in (rows or []) if isinstance(row, dict)]
        if hasattr(self, "simulation_revisit_events_group"):
            self.simulation_revisit_events_group.setTitle(
                f"Point Revisit Events : {len(event_rows)} Collections"
            )
        table.setRowCount(len(event_rows))
        for row_idx, row in enumerate(event_rows):
            event_utc = str(row.get("event_utc") or "").strip()
            sat_id = str(row.get("satellite_id") or "").strip()
            pass_start = str(row.get("pass_start_utc") or "").strip()
            pass_end = str(row.get("pass_end_utc") or "").strip()
            try:
                dist_km = f"{float(row.get('closest_distance_km', 0.0) or 0.0):,.2f}"
            except Exception:
                dist_km = "--"
            try:
                off_nadir = f"{float(row.get('closest_off_nadir_deg', 0.0) or 0.0):,.2f}"
            except Exception:
                off_nadir = "--"

            values = [event_utc, sat_id, pass_start, pass_end, dist_km, off_nadir]
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                table.setItem(row_idx, col_idx, item)
        table.resizeRowsToContents()

    def set_simulation_result_mode(self, scenario_id):
        scenario = str(scenario_id or "coverage_analysis").strip().lower()
        is_revisit = scenario == "point_revisit_analysis"
        if hasattr(self, "simulation_day_group"):
            self.simulation_day_group.setVisible(not is_revisit)
        if hasattr(self, "simulation_summary_group"):
            self.simulation_summary_group.setVisible(not is_revisit)
        if hasattr(self, "simulation_revisit_group"):
            self.simulation_revisit_group.setVisible(is_revisit)
        if hasattr(self, "simulation_revisit_events_group"):
            self.simulation_revisit_events_group.setVisible(is_revisit)
        if hasattr(self, "simulation_target_group"):
            self.simulation_target_group.setVisible(is_revisit)
        if hasattr(self, "simulation_aoi_source_combo"):
            self.simulation_aoi_source_combo.setVisible(not is_revisit)
        if hasattr(self, "simulation_aoi_layer_combo"):
            self.simulation_aoi_layer_combo.setVisible(not is_revisit)
        if hasattr(self, "simulation_aoi_layer_refresh_btn"):
            self.simulation_aoi_layer_refresh_btn.setVisible(not is_revisit)
        if hasattr(self, "simulation_aoi_layer_label"):
            self.simulation_aoi_layer_label.setVisible(not is_revisit)
        if hasattr(self, "simulation_aoi_source_label"):
            self.simulation_aoi_source_label.setVisible(not is_revisit)
        if hasattr(self, "simulation_aoi_layer_pick"):
            self.simulation_aoi_layer_pick.setVisible(not is_revisit)

    def _on_simulation_scenario_changed(self, _index=None):
        scenario_id = self.current_simulation_scenario_id()
        self.set_simulation_result_mode(scenario_id)
        self.simulation_scenario_changed.emit(str(scenario_id or "").strip())

    def _on_simulation_target_coordinate_changed(self, _value=None):
        if not hasattr(self, "simulation_target_lat_spin") or not hasattr(self, "simulation_target_lon_spin"):
            return
        lat_value = float(self.simulation_target_lat_spin.value())
        lon_value = float(self.simulation_target_lon_spin.value())
        label_value = str(self._simulation_target_point.get("label") or "").strip()
        if hasattr(self, "simulation_target_label_input"):
            label_value = str(self.simulation_target_label_input.text() or "").strip()
        self._simulation_target_point = {
            "lat": lat_value,
            "lon": lon_value,
            "source": "manual",
            "label": label_value,
        }
        if hasattr(self, "simulation_target_source_label"):
            self.simulation_target_source_label.setText("Target source: manual")

    def _on_simulation_target_label_changed(self, _text=None):
        state = self._simulation_target_point if isinstance(self._simulation_target_point, dict) else {}
        source_value = str(state.get("source") or "manual").strip() or "manual"
        label_value = ""
        if hasattr(self, "simulation_target_label_input"):
            label_value = str(self.simulation_target_label_input.text() or "").strip()
        lat_value = state.get("lat")
        lon_value = state.get("lon")
        if lat_value is None and hasattr(self, "simulation_target_lat_spin"):
            lat_value = float(self.simulation_target_lat_spin.value())
        if lon_value is None and hasattr(self, "simulation_target_lon_spin"):
            lon_value = float(self.simulation_target_lon_spin.value())
        try:
            lat_value = float(lat_value)
            lon_value = float(lon_value)
        except Exception:
            return
        self._simulation_target_point = {
            "lat": lat_value,
            "lon": lon_value,
            "source": source_value,
            "label": label_value,
        }

    def _on_simulation_pick_target_clicked(self):
        self.simulation_pick_target_requested.emit()

    def set_simulation_day(self, payload):
        row = payload if isinstance(payload, dict) else {}
        nav = navigation_button_state(
            index=row.get("index", 0),
            total_days=row.get("total_days", 0),
        )
        idx = int(nav.get("index", 0) or 0)
        total = int(nav.get("total_days", 0) or 0)
        if hasattr(self, "simulation_day_label"):
            date_text = str(row.get("date") or "--").strip() or "--"
            if total > 0:
                self.simulation_day_label.setText(f"{date_text} ({idx + 1}/{total})")
            else:
                self.simulation_day_label.setText(date_text)
        if hasattr(self, "simulation_day_imaged_label"):
            self.simulation_day_imaged_label.setText(
                f"Imaged today: {float(row.get('day_imaged_km2', 0.0) or 0.0):,.2f} km2"
            )
        if hasattr(self, "simulation_day_total_label"):
            self.simulation_day_total_label.setText(
                f"Total imaged up to day: {float(row.get('cumulative_imaged_km2', 0.0) or 0.0):,.2f} km2"
            )
        if hasattr(self, "simulation_day_unique_label"):
            self.simulation_day_unique_label.setText(
                f"Unique covered up to day: {float(row.get('cumulative_unique_km2', 0.0) or 0.0):,.2f} km2"
            )
        if hasattr(self, "simulation_day_passes_label"):
            self.simulation_day_passes_label.setText(
                f"Collection passes today: {int(row.get('collection_passes', 0) or 0)}"
            )
        if hasattr(self, "simulation_first_day_btn"):
            self.simulation_first_day_btn.setEnabled(bool(nav.get("can_first")))
        if hasattr(self, "simulation_prev_30_days_btn"):
            self.simulation_prev_30_days_btn.setEnabled(bool(nav.get("can_prev_30")))
        if hasattr(self, "simulation_prev_day_btn"):
            self.simulation_prev_day_btn.setEnabled(bool(nav.get("can_prev_1")))
        if hasattr(self, "simulation_next_day_btn"):
            self.simulation_next_day_btn.setEnabled(bool(nav.get("can_next_1")))
        if hasattr(self, "simulation_next_30_days_btn"):
            self.simulation_next_30_days_btn.setEnabled(bool(nav.get("can_next_30")))
        if hasattr(self, "simulation_last_day_btn"):
            self.simulation_last_day_btn.setEnabled(bool(nav.get("can_last")))

    def set_simulation_controls_enabled(self, enabled):
        enabled_flag = bool(enabled)
        widget_names = [
            "simulation_selection_mode_combo",
            "simulation_satellite_count_spin",
            "simulation_scenario_combo",
            "simulation_aoi_source_combo",
            "simulation_aoi_layer_combo",
            "simulation_aoi_layer_refresh_btn",
            "simulation_off_nadir_spin",
            "simulation_start_dt",
            "simulation_end_dt",
            "simulation_time_step_spin",
            "simulation_sat_table",
            "simulation_add_sat_btn",
            "simulation_edit_sat_btn",
            "simulation_remove_sat_btn",
            "simulation_import_sat_btn",
            "simulation_export_sat_btn",
            "simulation_target_lat_spin",
            "simulation_target_lon_spin",
            "simulation_pick_target_btn",
            "simulation_target_label_input",
        ]
        for name in widget_names:
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(enabled_flag)
        if hasattr(self, "simulation_start_btn"):
            self.simulation_start_btn.setEnabled(enabled_flag)
        if hasattr(self, "simulation_cancel_btn"):
            self.simulation_cancel_btn.setEnabled(not enabled_flag)

    def _normalize_simulation_config(self, config):
        raw = config if isinstance(config, dict) else {}
        satellites_raw = raw.get("satellites")
        satellites_raw = satellites_raw if isinstance(satellites_raw, list) else []
        satellites = []
        seen = set()
        for row in satellites_raw:
            sat = row if isinstance(row, dict) else {}
            satellite_id = str(sat.get("satellite_id") or sat.get("id") or "").strip()
            if not satellite_id or satellite_id in seen:
                continue
            seen.add(satellite_id)
            try:
                priority = int(float(sat.get("priority", 100)))
            except Exception:
                priority = 100
            swath_width_km = self._simulation_parse_swath_width_km(
                sat.get("swath_width_km"),
                sat.get("swath_km"),
                sat.get("swath_width_m"),
            )
            tle = sat.get("tle") if isinstance(sat.get("tle"), dict) else {}
            satellites.append(
                {
                    "satellite_id": satellite_id,
                    "name": str(sat.get("name") or satellite_id).strip() or satellite_id,
                    "priority": int(priority),
                    "enabled": bool(sat.get("enabled", True)),
                    "swath_width_km": float(swath_width_km),
                    "tle": {
                        "line1": str(tle.get("line1") or sat.get("tle_line1") or "").strip(),
                        "line2": str(tle.get("line2") or sat.get("tle_line2") or "").strip(),
                    },
                }
            )
        satellites.sort(
            key=lambda row: (
                int(row.get("priority", 100)),
                str(row.get("satellite_id") or "").strip(),
            )
        )
        try:
            schema_version = int(float(raw.get("schema_version", 1)))
        except Exception:
            schema_version = 1
        return {
            "schema_version": int(schema_version),
            "constellation_name": str(raw.get("constellation_name") or "default").strip() or "default",
            "satellites": satellites,
        }

    @staticmethod
    def _simulation_parse_swath_width_km(swath_width_km_value, swath_km_value, swath_width_m_value):
        default_km = 6.5
        for value in (swath_width_km_value, swath_km_value):
            if value is None:
                continue
            try:
                width_km = float(value)
            except Exception:
                continue
            if width_km > 0.0:
                return float(width_km)
        if swath_width_m_value is not None:
            try:
                width_m = float(swath_width_m_value)
            except Exception:
                width_m = 0.0
            if width_m > 0.0:
                return float(width_m) / 1000.0
        return float(default_km)

    def _refresh_simulation_satellite_table(self):
        if not hasattr(self, "simulation_sat_table"):
            return
        satellites = self._simulation_constellation_config.get("satellites", [])
        self.simulation_sat_table.blockSignals(True)
        self.simulation_sat_table.setRowCount(len(satellites))
        for row_idx, sat in enumerate(satellites):
            sat_id = str(sat.get("satellite_id") or "").strip()

            include_item = QTableWidgetItem("")
            include_item.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsUserCheckable
            )
            include_item.setCheckState(
                Qt.Checked if sat_id in self._simulation_manual_selected_ids else Qt.Unchecked
            )
            include_item.setData(Qt.UserRole, sat_id)
            self.simulation_sat_table.setItem(row_idx, 0, include_item)

            enabled_item = QTableWidgetItem("")
            enabled_item.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsUserCheckable
            )
            enabled_item.setCheckState(Qt.Checked if bool(sat.get("enabled", True)) else Qt.Unchecked)
            enabled_item.setData(Qt.UserRole, sat_id)
            self.simulation_sat_table.setItem(row_idx, 1, enabled_item)

            sat_id_item = QTableWidgetItem(sat_id)
            sat_id_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.simulation_sat_table.setItem(row_idx, 2, sat_id_item)

            name_item = QTableWidgetItem(str(sat.get("name") or sat_id))
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.simulation_sat_table.setItem(row_idx, 3, name_item)

            try:
                swath_km = float(sat.get("swath_width_km", 6.5) or 6.5)
            except Exception:
                swath_km = 6.5
            swath_item = QTableWidgetItem(f"{swath_km:.2f}")
            swath_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.simulation_sat_table.setItem(row_idx, 4, swath_item)

            prio_item = QTableWidgetItem(str(int(sat.get("priority", 100))))
            prio_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.simulation_sat_table.setItem(row_idx, 5, prio_item)

        self.simulation_sat_table.blockSignals(False)
        if hasattr(self, "simulation_satellite_count_spin"):
            max_count = max(1, len(satellites))
            self.simulation_satellite_count_spin.setMaximum(max_count)
            if self.simulation_satellite_count_spin.value() > max_count:
                self.simulation_satellite_count_spin.setValue(max_count)
        if hasattr(self, "simulation_sat_count_label"):
            self.simulation_sat_count_label.setText(f"Satellites configured: {len(satellites)}")

    def _on_simulation_sat_table_item_changed(self, item):
        if item is None:
            return
        sat_id = str(item.data(Qt.UserRole) or "").strip()
        if not sat_id:
            return
        satellites = self._simulation_constellation_config.get("satellites", [])
        target = None
        for row in satellites:
            if str(row.get("satellite_id") or "").strip() == sat_id:
                target = row
                break
        if target is None:
            return
        if int(item.column()) == 0:
            if item.checkState() == Qt.Checked:
                self._simulation_manual_selected_ids.add(sat_id)
            else:
                self._simulation_manual_selected_ids.discard(sat_id)
            return
        if int(item.column()) == 1:
            target["enabled"] = bool(item.checkState() == Qt.Checked)
            self._emit_simulation_config_changed()

    def _simulation_selected_satellite_index(self):
        if not hasattr(self, "simulation_sat_table"):
            return -1
        row_idx = int(self.simulation_sat_table.currentRow())
        satellites = self._simulation_constellation_config.get("satellites", [])
        if row_idx < 0 or row_idx >= len(satellites):
            return -1
        return row_idx

    def _open_simulation_satellite_dialog(self, *, existing=None):
        row = existing if isinstance(existing, dict) else {}

        dialog = QDialog(self)
        dialog.setWindowTitle("Simulation Satellite")
        dialog.resize(620, 320)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()

        sat_id_edit = QLineEdit(dialog)
        sat_id_edit.setText(str(row.get("satellite_id") or "").strip())
        sat_id_edit.setPlaceholderText("SAT-001")

        name_edit = QLineEdit(dialog)
        name_edit.setText(str(row.get("name") or "").strip())
        name_edit.setPlaceholderText("Satellite Name")

        enabled_check = QCheckBox("Enabled", dialog)
        enabled_check.setChecked(bool(row.get("enabled", True)))

        priority_spin = QSpinBox(dialog)
        priority_spin.setRange(-9999, 9999)
        try:
            priority_spin.setValue(int(float(row.get("priority", 100))))
        except Exception:
            priority_spin.setValue(100)

        swath_width_km_spin = QDoubleSpinBox(dialog)
        swath_width_km_spin.setDecimals(2)
        swath_width_km_spin.setRange(0.1, 1000.0)
        swath_width_km_spin.setSingleStep(0.1)
        swath_width_km_spin.setValue(
            float(
                self._simulation_parse_swath_width_km(
                    row.get("swath_width_km"),
                    row.get("swath_km"),
                    row.get("swath_width_m"),
                )
            )
        )

        tle = row.get("tle") if isinstance(row.get("tle"), dict) else {}
        tle_line1_edit = QLineEdit(dialog)
        tle_line1_edit.setText(str(tle.get("line1") or "").strip())
        tle_line1_edit.setPlaceholderText("1 ...")
        tle_line2_edit = QLineEdit(dialog)
        tle_line2_edit.setText(str(tle.get("line2") or "").strip())
        tle_line2_edit.setPlaceholderText("2 ...")

        form.addRow("Satellite ID", sat_id_edit)
        form.addRow("Name", name_edit)
        form.addRow("Priority", priority_spin)
        form.addRow("Swath Width (km)", swath_width_km_spin)
        form.addRow(enabled_check)
        form.addRow("TLE Line 1", tle_line1_edit)
        form.addRow("TLE Line 2", tle_line2_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return None

        satellite_id = sat_id_edit.text().strip()
        if not satellite_id:
            QMessageBox.warning(self, "Simulation", "Satellite ID is required.")
            return None
        line1 = tle_line1_edit.text().strip()
        line2 = tle_line2_edit.text().strip()
        if not line1 or not line2:
            QMessageBox.warning(self, "Simulation", "TLE line1 and line2 are required.")
            return None
        return {
            "satellite_id": satellite_id,
            "name": name_edit.text().strip() or satellite_id,
            "priority": int(priority_spin.value()),
            "enabled": bool(enabled_check.isChecked()),
            "swath_width_km": float(swath_width_km_spin.value()),
            "tle": {
                "line1": line1,
                "line2": line2,
            },
        }

    def _on_simulation_add_satellite(self):
        created = self._open_simulation_satellite_dialog(existing=None)
        if not isinstance(created, dict):
            return
        sat_id = str(created.get("satellite_id") or "").strip()
        satellites = self._simulation_constellation_config.get("satellites", [])
        if any(str(row.get("satellite_id") or "").strip() == sat_id for row in satellites):
            QMessageBox.warning(self, "Simulation", f"Satellite ID '{sat_id}' already exists.")
            return
        satellites.append(created)
        self._simulation_manual_selected_ids.add(sat_id)
        self._simulation_constellation_config = self._normalize_simulation_config(self._simulation_constellation_config)
        self._refresh_simulation_satellite_table()
        self._emit_simulation_config_changed()

    def _on_simulation_edit_satellite(self):
        row_idx = self._simulation_selected_satellite_index()
        if row_idx < 0:
            QMessageBox.warning(self, "Simulation", "Select a satellite row first.")
            return
        satellites = self._simulation_constellation_config.get("satellites", [])
        existing = satellites[row_idx]
        updated = self._open_simulation_satellite_dialog(existing=existing)
        if not isinstance(updated, dict):
            return
        updated_id = str(updated.get("satellite_id") or "").strip()
        for idx, row in enumerate(satellites):
            if idx == row_idx:
                continue
            if str(row.get("satellite_id") or "").strip() == updated_id:
                QMessageBox.warning(self, "Simulation", f"Satellite ID '{updated_id}' already exists.")
                return
        old_id = str(existing.get("satellite_id") or "").strip()
        satellites[row_idx] = updated
        if old_id != updated_id:
            if old_id in self._simulation_manual_selected_ids:
                self._simulation_manual_selected_ids.discard(old_id)
                self._simulation_manual_selected_ids.add(updated_id)
        self._simulation_constellation_config = self._normalize_simulation_config(self._simulation_constellation_config)
        self._refresh_simulation_satellite_table()
        self._emit_simulation_config_changed()

    def _on_simulation_remove_satellite(self):
        row_idx = self._simulation_selected_satellite_index()
        if row_idx < 0:
            QMessageBox.warning(self, "Simulation", "Select a satellite row first.")
            return
        satellites = self._simulation_constellation_config.get("satellites", [])
        removed = satellites.pop(row_idx)
        sat_id = str(removed.get("satellite_id") or "").strip()
        self._simulation_manual_selected_ids.discard(sat_id)
        self._refresh_simulation_satellite_table()
        self._emit_simulation_config_changed()

    def _on_simulation_import_satellites(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Simulation Constellation / TLE",
            "",
            "JSON/TLE files (*.json *.tle *.txt);;All files (*.*)",
        )
        if not file_path:
            return
        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Simulation", f"Failed to read file:\n{exc}")
            return

        merged = None
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("satellites"), list):
            merged = self._normalize_simulation_config(parsed)
        else:
            imported = self._parse_simulation_tle_text(text)
            if not imported:
                QMessageBox.warning(
                    self,
                    "Simulation",
                    "No valid TLE entries were found. Expected 2-line or 3-line TLE blocks.",
                )
                return
            satellites = self._simulation_constellation_config.get("satellites", [])
            existing_ids = {str(row.get("satellite_id") or "").strip() for row in satellites}
            for row in imported:
                sat_id = str(row.get("satellite_id") or "").strip()
                if sat_id in existing_ids:
                    suffix = 2
                    candidate = f"{sat_id}_{suffix}"
                    while candidate in existing_ids:
                        suffix += 1
                        candidate = f"{sat_id}_{suffix}"
                    row["satellite_id"] = candidate
                    row["name"] = candidate
                existing_ids.add(str(row.get("satellite_id") or "").strip())
                satellites.append(row)
            merged = self._normalize_simulation_config(self._simulation_constellation_config)

        self._simulation_constellation_config = merged
        self._simulation_manual_selected_ids = {
            str(row.get("satellite_id") or "").strip()
            for row in self._simulation_constellation_config.get("satellites", [])
            if str(row.get("satellite_id") or "").strip()
        }
        self._refresh_simulation_satellite_table()
        self._emit_simulation_config_changed()
        self.set_simulation_status(f"Simulation imported: {file_path}")

    def _on_simulation_export_config(self):
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Simulation Constellation",
            "simulation_constellation.json",
            "JSON files (*.json);;All files (*.*)",
        )
        if not output_path:
            return
        try:
            normalized = self._normalize_simulation_config(self._simulation_constellation_config)
            Path(output_path).write_text(
                json.dumps(normalized, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            self.set_simulation_status(f"Simulation config exported: {output_path}")
        except Exception as exc:
            QMessageBox.warning(self, "Simulation", f"Failed to export config:\n{exc}")

    @staticmethod
    def _parse_simulation_tle_text(text):
        lines = [str(line or "").strip() for line in str(text or "").splitlines() if str(line or "").strip()]
        out = []
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            line1 = ""
            line2 = ""
            name = ""
            if line.startswith("1 ") and (idx + 1) < len(lines) and lines[idx + 1].startswith("2 "):
                name = f"SAT-{len(out) + 1:03d}"
                line1 = lines[idx]
                line2 = lines[idx + 1]
                idx += 2
            elif (
                not line.startswith("1 ")
                and (idx + 2) < len(lines)
                and lines[idx + 1].startswith("1 ")
                and lines[idx + 2].startswith("2 ")
            ):
                name = line
                line1 = lines[idx + 1]
                line2 = lines[idx + 2]
                idx += 3
            else:
                idx += 1
                continue
            sat_id = name.replace(" ", "_").replace("/", "_").strip("_") or f"SAT-{len(out) + 1:03d}"
            out.append(
                {
                    "satellite_id": sat_id,
                    "name": name or sat_id,
                    "priority": 100,
                    "enabled": True,
                    "swath_width_km": 6.5,
                    "tle": {
                        "line1": line1,
                        "line2": line2,
                    },
                }
            )
        return out

    def _emit_simulation_config_changed(self):
        self.simulation_config_changed.emit(
            {
                "config": self._normalize_simulation_config(self._simulation_constellation_config),
            }
        )

    def _on_simulation_selection_mode_changed(self):
        mode = str(self.simulation_selection_mode_combo.currentData() or "top_n").strip().lower()
        manual_mode = mode == "manual"
        if hasattr(self, "simulation_satellite_count_spin"):
            self.simulation_satellite_count_spin.setEnabled(not manual_mode)
        if hasattr(self, "simulation_satellite_count_label"):
            self.simulation_satellite_count_label.setEnabled(not manual_mode)
        if hasattr(self, "simulation_sat_selection_hint"):
            if manual_mode:
                self.simulation_sat_selection_hint.setText(
                    "Manual mode: use the Include column to select satellites."
                )
            else:
                self.simulation_sat_selection_hint.setText(
                    "Top N mode: enabled satellites are sorted by priority."
                )

    def _refresh_simulation_polygon_layer_options(self):
        if not hasattr(self, "simulation_aoi_layer_combo"):
            return
        prior = str(self.simulation_aoi_layer_combo.currentData() or "").strip()
        self.simulation_aoi_layer_combo.blockSignals(True)
        self.simulation_aoi_layer_combo.clear()
        for row in self._project_polygon_layer_options():
            self.simulation_aoi_layer_combo.addItem(row.get("name"), row.get("id"))
        if prior:
            idx = self.simulation_aoi_layer_combo.findData(prior)
            if idx >= 0:
                self.simulation_aoi_layer_combo.setCurrentIndex(idx)
        self.simulation_aoi_layer_combo.blockSignals(False)

    @staticmethod
    def _project_polygon_layer_options():
        options = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
                continue
            layer_id = str(layer.id() or "").strip()
            if not layer_id:
                continue
            layer_name = str(layer.name() or "").strip() or layer_id
            options.append({"id": layer_id, "name": layer_name})
        options.sort(key=lambda row: str(row.get("name") or "").lower())
        return options

    def _emit_simulation_start_request(self):
        start_dt = self.simulation_start_dt.dateTime()
        end_dt = self.simulation_end_dt.dateTime()
        if start_dt >= end_dt:
            QMessageBox.warning(self, "Simulation", "Start (UTC) must be before End (UTC).")
            return
        satellites = self._simulation_constellation_config.get("satellites", [])
        if not satellites:
            QMessageBox.warning(self, "Simulation", "Add at least one satellite to constellation config.")
            return
        selection_mode = str(self.simulation_selection_mode_combo.currentData() or "top_n").strip().lower()
        selected_satellite_ids = sorted(self._simulation_manual_selected_ids)
        if selection_mode == "manual" and not selected_satellite_ids:
            QMessageBox.warning(self, "Simulation", "Manual mode requires at least one included satellite.")
            return
        scenario_id = str(self.simulation_scenario_combo.currentData() or "coverage_analysis").strip()
        aoi_source = str(self.simulation_aoi_source_combo.currentData() or "map_extent").strip()
        aoi_layer_id = str(self.simulation_aoi_layer_combo.currentData() or "").strip()

        target_lat = None
        target_lon = None
        target_source = "manual"
        target_label = ""
        if scenario_id == "point_revisit_analysis":
            if not hasattr(self, "simulation_target_lat_spin") or not hasattr(self, "simulation_target_lon_spin"):
                QMessageBox.warning(self, "Simulation", "Point target controls are missing.")
                return
            target_lat = float(self.simulation_target_lat_spin.value())
            target_lon = float(self.simulation_target_lon_spin.value())
            if target_lat < -90.0 or target_lat > 90.0:
                QMessageBox.warning(self, "Simulation", "Target latitude must be in [-90, 90].")
                return
            if target_lon < -180.0 or target_lon > 180.0:
                QMessageBox.warning(self, "Simulation", "Target longitude must be in [-180, 180].")
                return
            state = self._simulation_target_point if isinstance(self._simulation_target_point, dict) else {}
            target_source = str(state.get("source") or "manual").strip() or "manual"
            if hasattr(self, "simulation_target_label_input"):
                target_label = str(self.simulation_target_label_input.text() or "").strip()
            self._simulation_target_point = {
                "lat": float(target_lat),
                "lon": float(target_lon),
                "source": target_source,
                "label": target_label,
            }
        else:
            if aoi_source == "polygon_layer" and not aoi_layer_id:
                QMessageBox.warning(self, "Simulation", "Select an AOI polygon layer.")
                return

        payload = {
            "scenario_id": scenario_id,
            "selection_mode": selection_mode,
            "satellite_count": int(self.simulation_satellite_count_spin.value()),
            "selected_satellite_ids": selected_satellite_ids,
            "off_nadir_deg": float(self.simulation_off_nadir_spin.value()),
            "start_utc": start_dt.toUTC().toString("yyyy-MM-ddTHH:mm:ss'Z'"),
            "end_utc": end_dt.toUTC().toString("yyyy-MM-ddTHH:mm:ss'Z'"),
            "time_step_sec": int(self.simulation_time_step_spin.value()),
            "aoi_source": aoi_source,
            "aoi_layer_id": aoi_layer_id,
            "target_lat_deg": target_lat,
            "target_lon_deg": target_lon,
            "target_source": target_source,
            "target_label": target_label,
            "constellation_config": self._normalize_simulation_config(self._simulation_constellation_config),
        }
        self.simulation_start_requested.emit(payload)

    def _build_campaigns_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        summary = QLabel(
            "Set one base directory for campaign-managed storage. "
            "The plugin will manage project, imagery, and output files under the active campaign."
        )
        summary.setWordWrap(True)

        campaign_group = QGroupBox("Collection Campaign")
        campaign_form = QFormLayout(campaign_group)

        self.campaign_managed_storage = QCheckBox("Enable managed campaign storage")
        self.campaign_managed_storage.setChecked(True)
        self.campaign_managed_storage.toggled.connect(lambda _checked: self._refresh_campaign_summary())

        base_widget = QWidget()
        base_layout = QHBoxLayout(base_widget)
        base_layout.setContentsMargins(0, 0, 0, 0)
        base_layout.setSpacing(6)
        self.campaign_base_dir = QLineEdit()
        self.campaign_base_dir.setPlaceholderText("Campaign base directory")
        self.campaign_base_dir.textChanged.connect(lambda _text: self._refresh_campaign_summary())
        self.campaign_base_browse_btn = QPushButton("Browse...")
        self.campaign_base_browse_btn.clicked.connect(self._browse_campaign_base_dir)
        base_layout.addWidget(self.campaign_base_dir, 1)
        base_layout.addWidget(self.campaign_base_browse_btn)

        self.campaign_uid_input = QLineEdit()
        self.campaign_uid_input.setPlaceholderText("auto-generated if empty")
        self.campaign_uid_input.textChanged.connect(lambda _text: self._refresh_campaign_summary())

        self.campaign_name_input = QLineEdit()
        self.campaign_name_input.setPlaceholderText("Optional campaign name")
        self.campaign_name_input.textChanged.connect(lambda _text: self._refresh_campaign_summary())

        self.campaign_existing_combo = QComboBox()
        self.campaign_existing_combo.addItem("Select Existing Campaign...", "")
        self.campaign_existing_combo.currentIndexChanged.connect(
            lambda _index: self._on_campaign_existing_selected()
        )

        campaign_form.addRow(self.campaign_managed_storage)
        campaign_form.addRow("Base Directory", base_widget)
        campaign_form.addRow("Existing Campaign", self.campaign_existing_combo)
        campaign_form.addRow("Campaign UID", self.campaign_uid_input)
        campaign_form.addRow("Campaign Name", self.campaign_name_input)

        button_row = QHBoxLayout()
        self.campaign_create_btn = QPushButton("Create New Campaign")
        self.campaign_create_btn.clicked.connect(self._emit_campaign_create_request)
        self.campaign_apply_btn = QPushButton("Apply Campaign Context")
        self.campaign_apply_btn.clicked.connect(self._emit_campaign_apply_request)
        self.campaign_open_folder_btn = QPushButton("Open Campaign Folder")
        self.campaign_open_folder_btn.setToolTip("Open the active campaign folder in file explorer.")
        self.campaign_open_folder_btn.clicked.connect(self._open_campaign_folder)
        button_row.addWidget(self.campaign_create_btn)
        button_row.addWidget(self.campaign_apply_btn)
        button_row.addWidget(self.campaign_open_folder_btn)
        button_row.addStretch(1)

        self.campaign_summary = QTextEdit()
        self.campaign_summary.setReadOnly(True)
        self.campaign_summary.setMinimumHeight(120)
        self.campaign_summary.setPlaceholderText("Campaign context details will appear here.")

        layout.addWidget(summary)
        layout.addWidget(campaign_group)
        layout.addLayout(button_row)
        layout.addWidget(self.campaign_summary, 1)
        self._refresh_campaign_summary()
        return tab

    def _build_explore_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        form = QFormLayout()
        self.source_combo = QComboBox()
        self.source_combo.setMinimumWidth(0)
        self.collection_combo = QComboBox()
        self.collection_combo.setMinimumWidth(0)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setMinimumWidth(0)
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.setMinimumWidth(0)
        self.max_cloud = QSpinBox()
        self.max_cloud.setRange(0, 100)
        self.max_cloud.setValue(40)
        self.max_cloud.setMinimumWidth(0)
        self.min_gsd = QDoubleSpinBox()
        self.min_gsd.setRange(0.0, 1000.0)
        self.min_gsd.setDecimals(2)
        self.min_gsd.setSingleStep(0.1)
        self.min_gsd.setSpecialValueText("none")
        self.min_gsd.setValue(0.0)
        self.min_gsd.setMinimumWidth(0)
        self.max_gsd = QDoubleSpinBox()
        self.max_gsd.setRange(0.0, 1000.0)
        self.max_gsd.setDecimals(2)
        self.max_gsd.setSingleStep(0.1)
        self.max_gsd.setSpecialValueText("none")
        self.max_gsd.setValue(0.0)
        self.max_gsd.setMinimumWidth(0)
        self.limit = QSpinBox()
        self.limit.setRange(1, 1000)
        self.limit.setValue(250)
        self.limit.setMinimumWidth(0)
        self.contract_id = QLineEdit()
        self.contract_id.setPlaceholderText("optional (defaults to .env / client setting)")
        self.contract_id.setMinimumWidth(0)
        self.satellite_name = QLineEdit()
        self.satellite_name.setPlaceholderText("optional")
        self.satellite_name.setMinimumWidth(0)
        self.require_full_aoi_overlap = QCheckBox("Only captures fully covering AOI")
        self.require_full_aoi_overlap.setChecked(False)
        self.require_full_aoi_overlap.setToolTip(
            "When enabled, search results must fully contain the current AOI. "
            "Sentinel-2 typically works better with this disabled."
        )
        self.require_full_aoi_overlap.setMinimumWidth(0)
        self.location_query_input = QLineEdit()
        self.location_query_input.setPlaceholderText(
            "Place name or lat, lon (example: 34.6037, -58.3816)"
        )
        self.location_query_input.setMinimumWidth(0)
        self.location_query_input.textEdited.connect(self._on_location_query_edited)
        self.location_query_input.returnPressed.connect(self._emit_location_jump_request)
        self._location_suggestions_query = ""
        self._location_suggestions_model = QStringListModel(self)
        self.location_completer = QCompleter(self._location_suggestions_model, self)
        self.location_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.location_completer.setFilterMode(Qt.MatchContains)
        self.location_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.location_query_input.setCompleter(self.location_completer)
        self._location_suggestions_timer = QTimer(self)
        self._location_suggestions_timer.setSingleShot(True)
        self._location_suggestions_timer.setInterval(300)
        self._location_suggestions_timer.timeout.connect(self._emit_location_suggestions_request)
        self.location_jump_btn = QPushButton("Center")
        self.location_jump_btn.clicked.connect(self._emit_location_jump_request)
        jump_row_widget = QWidget()
        jump_row_layout = QHBoxLayout(jump_row_widget)
        jump_row_layout.setContentsMargins(0, 0, 0, 0)
        jump_row_layout.setSpacing(6)
        jump_row_layout.addWidget(self.location_query_input, 1)
        jump_row_layout.addWidget(self.location_jump_btn)

        form.addRow("Sensor Feed", self.source_combo)
        form.addRow("Product Layer", self.collection_combo)
        form.addRow("Access Profile", self.contract_id)
        form.addRow("Start Date (UTC)", self.start_date)
        form.addRow("End Date (UTC)", self.end_date)
        form.addRow("Max Cloud (%)", self.max_cloud)
        form.addRow("Min Resolution (m/px)", self.min_gsd)
        form.addRow("Max Resolution (m/px)", self.max_gsd)
        form.addRow("Max Results", self.limit)
        form.addRow("Platform", self.satellite_name)
        form.addRow("Coverage Filter", self.require_full_aoi_overlap)
        jump_box = QGroupBox("Go To AOI")
        jump_box_layout = QVBoxLayout(jump_box)
        jump_box_layout.setContentsMargins(8, 8, 8, 8)
        jump_box_layout.setSpacing(4)
        jump_box_layout.addWidget(jump_row_widget)

        btn_row = QHBoxLayout()
        self.search_btn = QPushButton("Search Current AOI")
        self.search_btn.clicked.connect(self._emit_search_request)
        btn_row.addWidget(self.search_btn)
        self.download_selected_btn = QPushButton("Download Selected")
        self.download_selected_btn.setToolTip(
            "Download selected search result(s) as GeoTIFF in background. "
            "Multi-tile captures are merged into one VRT per outcome."
        )
        self.download_selected_btn.setEnabled(False)
        self.download_selected_btn.clicked.connect(self._emit_download_selected_request)
        btn_row.addWidget(self.download_selected_btn)
        btn_row.addStretch(1)

        # Create sub-tabs for search log and results
        output_tabs = QTabWidget()
        
        # Results tab
        results_tab = QWidget()
        results_layout = QVBoxLayout(results_tab)
        results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_list = QListWidget()
        self.results_list.setMinimumWidth(0)
        self.results_list.setSelectionMode(self.results_list.SingleSelection)
        self.results_list.currentItemChanged.connect(lambda _cur, _prev: self._emit_result_selected())
        self.results_list.itemChanged.connect(self._on_results_item_changed)
        self.results_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self._show_results_context_menu)
        self.results_list.setToolTip(
            "Select a capture to load imagery. Check multiple captures to build a time stack."
        )
        results_layout.addWidget(self.results_list)
        output_tabs.addTab(results_tab, "Candidate Captures")
        
        # Search log tab
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(0, 0, 0, 0)
        self.download_progress_label = QLabel("Download monitor: idle")
        self.download_progress_label.setWordWrap(True)
        self.download_progress_bar = QProgressBar()
        self.download_progress_bar.setRange(0, 100)
        self.download_progress_bar.setValue(0)
        self.download_progress_bar.setFormat("%p%")
        log_layout.addWidget(self.download_progress_label)
        log_layout.addWidget(self.download_progress_bar)

        self.download_tasks_table = QTableWidget()
        self.download_tasks_table.setColumnCount(9)
        self.download_tasks_table.setHorizontalHeaderLabels(
            [
                "Task ID",
                "Status",
                "Progress",
                "Groups",
                "Items",
                "Downloaded",
                "Started (UTC)",
                "Updated (UTC)",
                "Note",
            ]
        )
        self.download_tasks_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.download_tasks_table.setSelectionMode(QTableWidget.NoSelection)
        self.download_tasks_table.setAlternatingRowColors(True)
        self.download_tasks_table.verticalHeader().setVisible(False)
        self.download_tasks_table.horizontalHeader().setStretchLastSection(True)
        self.download_tasks_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.download_tasks_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.download_tasks_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.download_tasks_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.download_tasks_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.download_tasks_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.download_tasks_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.download_tasks_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.download_tasks_table.setMinimumHeight(130)
        log_layout.addWidget(self.download_tasks_table)

        self.search_log = QTextEdit()
        self.search_log.setReadOnly(True)
        self.search_log.setPlaceholderText("Search activity appears here.")
        self.search_log.setMinimumWidth(0)
        log_layout.addWidget(self.search_log, 1)
        output_tabs.addTab(log_tab, "Activity Log")

        # Debug log tab
        debug_tab = QWidget()
        debug_layout = QVBoxLayout(debug_tab)
        debug_layout.setContentsMargins(0, 0, 0, 0)
        self.debug_log = QTextEdit()
        self.debug_log.setReadOnly(True)
        self.debug_log.setPlaceholderText("System diagnostics appear here.")
        self.debug_log.setMinimumWidth(0)
        debug_layout.addWidget(self.debug_log)
        output_tabs.addTab(debug_tab, "System Log")

        layout.addWidget(jump_box)
        layout.addLayout(form)
        layout.addLayout(btn_row)
        layout.addWidget(output_tabs, 1)
        return tab

    def _build_asset_intel_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        intro = QLabel(
            "Browse and filter the local military asset intelligence database."
        )
        intro.setWordWrap(True)

        query_group = QGroupBox("Asset Query")
        query_layout = QVBoxLayout(query_group)
        query_layout.setContentsMargins(8, 8, 8, 8)
        query_layout.setSpacing(6)

        query_row = QWidget()
        query_row_layout = QHBoxLayout(query_row)
        query_row_layout.setContentsMargins(0, 0, 0, 0)
        query_row_layout.setSpacing(6)

        self.asset_intel_query_input = QLineEdit()
        self.asset_intel_query_input.setPlaceholderText("Search by title, id, or technical text...")
        self.asset_intel_query_input.returnPressed.connect(self._emit_asset_intel_search_request)
        self.asset_intel_search_btn = QPushButton("Search")
        self.asset_intel_search_btn.clicked.connect(self._emit_asset_intel_search_request)
        self.asset_intel_reset_btn = QPushButton("Reset")
        self.asset_intel_reset_btn.clicked.connect(self._reset_asset_intel_filters)

        query_row_layout.addWidget(self.asset_intel_query_input, 1)
        query_row_layout.addWidget(self.asset_intel_search_btn)
        query_row_layout.addWidget(self.asset_intel_reset_btn)

        filters_form = QFormLayout()
        self.asset_intel_main_domain_combo = QComboBox()
        self.asset_intel_sub_domain_1_combo = QComboBox()
        self.asset_intel_sub_domain_2_combo = QComboBox()
        self.asset_intel_type_combo = QComboBox()
        self.asset_intel_origin_combo = QComboBox()
        self.asset_intel_proliferation_combo = QComboBox()
        self.asset_intel_builder_combo = QComboBox()
        self.asset_intel_limit_spin = QSpinBox()
        self.asset_intel_limit_spin.setRange(1, 1000)
        self.asset_intel_limit_spin.setValue(250)
        self.asset_intel_sub_domain_2_combo.currentIndexChanged.connect(
            self._on_asset_intel_sub_domain_2_changed
        )

        def _dimension_filter_input():
            value_input = QLineEdit()
            value_input.setMaximumWidth(90)
            value_input.setPlaceholderText("-1")
            value_input.setText("-1")
            value_input.setToolTip("-1 disables this filter; enter meters for filtering.")
            return value_input

        self.asset_intel_length_min_input = _dimension_filter_input()
        self.asset_intel_length_max_input = _dimension_filter_input()
        self.asset_intel_width_min_input = _dimension_filter_input()
        self.asset_intel_width_max_input = _dimension_filter_input()

        vessel_size_row = QWidget()
        vessel_size_row_layout = QHBoxLayout(vessel_size_row)
        vessel_size_row_layout.setContentsMargins(0, 0, 0, 0)
        vessel_size_row_layout.setSpacing(6)
        vessel_size_row_layout.addWidget(QLabel("Length"))
        vessel_size_row_layout.addWidget(QLabel("Min"))
        vessel_size_row_layout.addWidget(self.asset_intel_length_min_input)
        vessel_size_row_layout.addWidget(QLabel("Max"))
        vessel_size_row_layout.addWidget(self.asset_intel_length_max_input)
        vessel_size_row_layout.addSpacing(8)
        vessel_size_row_layout.addWidget(QLabel("Width"))
        vessel_size_row_layout.addWidget(QLabel("Min"))
        vessel_size_row_layout.addWidget(self.asset_intel_width_min_input)
        vessel_size_row_layout.addWidget(QLabel("Max"))
        vessel_size_row_layout.addWidget(self.asset_intel_width_max_input)
        vessel_size_row_layout.addStretch(1)

        for combo in (
            self.asset_intel_main_domain_combo,
            self.asset_intel_sub_domain_1_combo,
            self.asset_intel_sub_domain_2_combo,
            self.asset_intel_type_combo,
            self.asset_intel_origin_combo,
            self.asset_intel_proliferation_combo,
            self.asset_intel_builder_combo,
        ):
            combo.addItem("Any", "")

        filters_form.addRow("Main Domain", self.asset_intel_main_domain_combo)
        filters_form.addRow("Sub Domain 1", self.asset_intel_sub_domain_1_combo)
        filters_form.addRow("Sub Domain 2", self.asset_intel_sub_domain_2_combo)
        filters_form.addRow("Type", self.asset_intel_type_combo)
        filters_form.addRow("Origin", self.asset_intel_origin_combo)
        filters_form.addRow("Proliferation", self.asset_intel_proliferation_combo)
        filters_form.addRow("Builder", self.asset_intel_builder_combo)
        filters_form.addRow("Vessel Size (m)", vessel_size_row)
        filters_form.addRow("Result Limit", self.asset_intel_limit_spin)

        query_layout.addWidget(query_row)
        query_layout.addLayout(filters_form)

        query_actions_row = QHBoxLayout()
        self.asset_intel_create_btn = QPushButton("Add Asset")
        self.asset_intel_create_btn.clicked.connect(self._open_asset_intel_create_dialog)
        self.asset_intel_extract_size_btn = QPushButton("Select Target from Map")
        self.asset_intel_extract_size_btn.setToolTip(
            "Enter Select Mode, click a polygon in the map, and apply +/-5m length/width filters."
        )
        self.asset_intel_extract_size_btn.setCheckable(True)
        self.asset_intel_extract_size_btn.setChecked(False)
        self.asset_intel_extract_size_btn.clicked.connect(
            self._emit_asset_intel_polygon_size_from_selection_request
        )
        self.asset_intel_update_btn = QPushButton("Modify Asset")
        self.asset_intel_update_btn.clicked.connect(self._open_asset_intel_update_dialog)
        self.asset_intel_delete_btn = QPushButton("Delete Asset")
        self.asset_intel_delete_btn.clicked.connect(self._emit_asset_intel_delete_request)
        query_actions_row.addWidget(self.asset_intel_create_btn)
        query_actions_row.addWidget(self.asset_intel_extract_size_btn)
        query_actions_row.addStretch(1)

        result_actions_row = QHBoxLayout()
        result_actions_row.addWidget(self.asset_intel_update_btn)
        result_actions_row.addWidget(self.asset_intel_delete_btn)
        result_actions_row.addStretch(1)

        self.asset_intel_status_label = QLabel("Asset Intel: waiting for database configuration.")
        self.asset_intel_status_label.setWordWrap(True)
        self.asset_intel_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.asset_intel_results_list = QListWidget()
        self.asset_intel_results_list.setSelectionMode(self.asset_intel_results_list.SingleSelection)
        self.asset_intel_results_list.currentItemChanged.connect(
            lambda _cur, _prev: self._emit_asset_intel_asset_selected()
        )
        self.asset_intel_results_list.itemDoubleClicked.connect(self._on_asset_intel_result_double_clicked)
        self.asset_intel_results_list.setToolTip("Select an asset to load detailed technical intelligence.")

        detail_tabs = QTabWidget()
        self.asset_intel_detail_tabs = detail_tabs
        overview_tab = QWidget()
        overview_layout = QVBoxLayout(overview_tab)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        self.asset_intel_overview_text = QTextEdit()
        self.asset_intel_overview_text.setReadOnly(True)
        self.asset_intel_overview_text.setPlaceholderText("Asset summary appears here.")
        overview_layout.addWidget(self.asset_intel_overview_text)
        detail_tabs.addTab(overview_tab, "Overview")

        systems_tab = QWidget()
        systems_layout = QVBoxLayout(systems_tab)
        systems_layout.setContentsMargins(0, 0, 0, 0)
        self.asset_intel_system_scope_tabs = QTabWidget()

        units_scope_tab = QWidget()
        units_scope_layout = QVBoxLayout(units_scope_tab)
        units_scope_layout.setContentsMargins(0, 0, 0, 0)
        units_scope_layout.setSpacing(6)

        unit_filter_row = QHBoxLayout()
        unit_filter_row.addWidget(QLabel("Pennant / Identifier"))
        self.asset_intel_unit_filter_input = QLineEdit()
        self.asset_intel_unit_filter_input.setPlaceholderText("Filter fielded units by pennant or identifier...")
        self.asset_intel_unit_filter_input.textChanged.connect(lambda _text: self._apply_asset_intel_unit_filter())
        unit_filter_row.addWidget(self.asset_intel_unit_filter_input, 1)

        self.asset_intel_units_table = QTableWidget(0, 7)
        self.asset_intel_units_table.setHorizontalHeaderLabels(
            ["Primary ID", "Unit", "Type", "Status", "Linked Systems", "Notes", "Source"]
        )
        self.asset_intel_units_table.setSelectionBehavior(self.asset_intel_units_table.SelectRows)
        self.asset_intel_units_table.setSelectionMode(self.asset_intel_units_table.SingleSelection)
        self.asset_intel_units_table.setEditTriggers(self.asset_intel_units_table.NoEditTriggers)
        self.asset_intel_units_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.asset_intel_units_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.asset_intel_units_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.asset_intel_units_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.asset_intel_units_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.asset_intel_units_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.asset_intel_units_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.asset_intel_units_table.currentCellChanged.connect(
            lambda _r, _c, _pr, _pc: self._on_asset_intel_unit_selection_changed()
        )
        self.asset_intel_units_table.cellDoubleClicked.connect(
            lambda row, _col: self._open_asset_intel_edit_unit_dialog(int(row))
        )

        self.asset_intel_unit_identifier_table = QTableWidget(0, 3)
        self.asset_intel_unit_identifier_table.setHorizontalHeaderLabels(
            ["Identifier Type", "Identifier", "Primary"]
        )
        self.asset_intel_unit_identifier_table.setSelectionBehavior(
            self.asset_intel_unit_identifier_table.SelectRows
        )
        self.asset_intel_unit_identifier_table.setSelectionMode(
            self.asset_intel_unit_identifier_table.SingleSelection
        )
        self.asset_intel_unit_identifier_table.setEditTriggers(
            self.asset_intel_unit_identifier_table.NoEditTriggers
        )
        self.asset_intel_unit_identifier_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents
        )
        self.asset_intel_unit_identifier_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.asset_intel_unit_identifier_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.asset_intel_unit_identifier_table.cellDoubleClicked.connect(
            lambda row, _col: self._open_asset_intel_edit_identifier_dialog(int(row))
        )
        self.asset_intel_unit_identifier_table.viewport().installEventFilter(self)

        self.asset_intel_unit_system_fit_table = QTableWidget(0, 4)
        self.asset_intel_unit_system_fit_table.setHorizontalHeaderLabels(
            ["Onboard System", "Category", "Fit Status", "Qty"]
        )
        self.asset_intel_unit_system_fit_table.setSelectionBehavior(
            self.asset_intel_unit_system_fit_table.SelectRows
        )
        self.asset_intel_unit_system_fit_table.setSelectionMode(
            self.asset_intel_unit_system_fit_table.SingleSelection
        )
        self.asset_intel_unit_system_fit_table.setEditTriggers(
            self.asset_intel_unit_system_fit_table.NoEditTriggers
        )
        self.asset_intel_unit_system_fit_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.asset_intel_unit_system_fit_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents
        )
        self.asset_intel_unit_system_fit_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents
        )
        self.asset_intel_unit_system_fit_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents
        )
        self.asset_intel_unit_system_fit_table.cellDoubleClicked.connect(
            lambda row, _col: self._open_asset_intel_edit_system_fit_dialog(int(row))
        )
        self.asset_intel_unit_system_fit_table.viewport().installEventFilter(self)

        units_splitter = QSplitter(Qt.Vertical)
        units_splitter.addWidget(self.asset_intel_units_table)
        unit_detail_splitter = QSplitter(Qt.Vertical)
        unit_detail_splitter.addWidget(self.asset_intel_unit_identifier_table)
        unit_detail_splitter.addWidget(self.asset_intel_unit_system_fit_table)
        unit_detail_splitter.setSizes([140, 180])
        units_splitter.addWidget(unit_detail_splitter)
        units_splitter.setSizes([230, 220])

        units_scope_layout.addLayout(unit_filter_row)
        units_scope_layout.addWidget(units_splitter)
        self.asset_intel_system_scope_tabs.addTab(units_scope_tab, "Fielded Units (Pennants)")

        onboard_scope_tab = QWidget()
        onboard_scope_layout = QVBoxLayout(onboard_scope_tab)
        onboard_scope_layout.setContentsMargins(0, 0, 0, 0)
        systems_splitter = QSplitter(Qt.Vertical)
        self.asset_intel_systems_table = QTableWidget(0, 5)
        self.asset_intel_systems_table.setHorizontalHeaderLabels(
            ["System", "Category", "Summary", "Pages", "Notes"]
        )
        self.asset_intel_systems_table.setSelectionBehavior(self.asset_intel_systems_table.SelectRows)
        self.asset_intel_systems_table.setSelectionMode(self.asset_intel_systems_table.SingleSelection)
        self.asset_intel_systems_table.setEditTriggers(self.asset_intel_systems_table.NoEditTriggers)
        self.asset_intel_systems_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.asset_intel_systems_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.asset_intel_systems_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.asset_intel_systems_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.asset_intel_systems_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.asset_intel_systems_table.currentCellChanged.connect(
            lambda _r, _c, _pr, _pc: self._on_asset_intel_system_selection_changed()
        )
        self.asset_intel_systems_table.cellDoubleClicked.connect(
            lambda row, _col: self._open_asset_intel_edit_system_dialog(int(row))
        )
        self.asset_intel_system_attr_table = QTableWidget(0, 3)
        self.asset_intel_system_attr_table.setHorizontalHeaderLabels(
            ["Attribute", "Value", "Unit"]
        )
        self.asset_intel_system_attr_table.setSelectionBehavior(self.asset_intel_system_attr_table.SelectRows)
        self.asset_intel_system_attr_table.setSelectionMode(self.asset_intel_system_attr_table.SingleSelection)
        self.asset_intel_system_attr_table.setEditTriggers(self.asset_intel_system_attr_table.NoEditTriggers)
        self.asset_intel_system_attr_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.asset_intel_system_attr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.asset_intel_system_attr_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        systems_splitter.addWidget(self.asset_intel_systems_table)
        systems_splitter.addWidget(self.asset_intel_system_attr_table)
        systems_splitter.setSizes([260, 220])
        onboard_scope_layout.addWidget(systems_splitter)
        self.asset_intel_system_scope_tabs.addTab(onboard_scope_tab, "Onboard Systems")
        self.asset_intel_system_scope_action_btn = QPushButton("New Units")
        self.asset_intel_system_scope_action_btn.clicked.connect(self._on_asset_intel_system_scope_action_clicked)
        self.asset_intel_system_scope_tabs.setCornerWidget(
            self.asset_intel_system_scope_action_btn,
            Qt.TopRightCorner,
        )
        self.asset_intel_system_scope_tabs.currentChanged.connect(
            lambda _index: self._refresh_asset_intel_system_scope_action_button()
        )
        self._refresh_asset_intel_system_scope_action_button()

        systems_layout.addWidget(self.asset_intel_system_scope_tabs)
        detail_tabs.addTab(systems_tab, "Systems")

        notes_tab = QWidget()
        notes_layout = QVBoxLayout(notes_tab)
        notes_layout.setContentsMargins(0, 0, 0, 0)
        notes_layout.setSpacing(6)
        note_scope_row = QHBoxLayout()
        self.asset_intel_note_id_label = QLabel("Note ID: (new)")
        self.asset_intel_note_target_combo = QComboBox()
        self.asset_intel_note_target_combo.addItem("Asset (General)", "asset")
        note_scope_row.addWidget(self.asset_intel_note_id_label)
        note_scope_row.addStretch(1)
        note_scope_row.addWidget(QLabel("Target"))
        note_scope_row.addWidget(self.asset_intel_note_target_combo)

        self.asset_intel_notes_table = QTableWidget(0, 6)
        self.asset_intel_notes_table.setHorizontalHeaderLabels(
            ["Event UTC", "Analyst", "Scope", "Type", "Priority", "Title"]
        )
        self.asset_intel_notes_table.setSelectionBehavior(self.asset_intel_notes_table.SelectRows)
        self.asset_intel_notes_table.setSelectionMode(self.asset_intel_notes_table.SingleSelection)
        self.asset_intel_notes_table.setEditTriggers(self.asset_intel_notes_table.NoEditTriggers)
        self.asset_intel_notes_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.asset_intel_notes_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.asset_intel_notes_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.asset_intel_notes_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.asset_intel_notes_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.asset_intel_notes_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.asset_intel_notes_table.currentCellChanged.connect(
            lambda _r, _c, _pr, _pc: self._on_asset_intel_note_selection_changed()
        )

        note_form = QFormLayout()
        self.asset_intel_note_analyst_input = QLineEdit()
        self.asset_intel_note_analyst_input.setPlaceholderText("required")
        self.asset_intel_note_title_input = QLineEdit()
        self.asset_intel_note_type_combo = QComboBox()
        self.asset_intel_note_type_combo.addItem("Observation", "observation")
        self.asset_intel_note_type_combo.addItem("Assessment", "assessment")
        self.asset_intel_note_type_combo.addItem("Alert", "alert")
        self.asset_intel_note_type_combo.addItem("Change", "change")
        self.asset_intel_note_type_combo.addItem("Maintenance", "maintenance")
        self.asset_intel_note_type_combo.addItem("AI", "ai")
        self.asset_intel_note_priority_combo = QComboBox()
        self.asset_intel_note_priority_combo.addItem("Low", "low")
        self.asset_intel_note_priority_combo.addItem("Medium", "medium")
        self.asset_intel_note_priority_combo.addItem("High", "high")
        self.asset_intel_note_priority_combo.addItem("Critical", "critical")
        self.asset_intel_note_priority_combo.setCurrentIndex(1)
        self.asset_intel_note_confidence_combo = QComboBox()
        self.asset_intel_note_confidence_combo.addItem("Unknown", "")
        self.asset_intel_note_confidence_combo.addItem("Low", "low")
        self.asset_intel_note_confidence_combo.addItem("Medium", "medium")
        self.asset_intel_note_confidence_combo.addItem("High", "high")
        self.asset_intel_note_confidence_combo.addItem("Confirmed", "confirmed")
        self.asset_intel_note_source_reliability_combo = QComboBox()
        self.asset_intel_note_source_reliability_combo.addItem("Unknown", "")
        for value in ["A", "B", "C", "D", "E", "F"]:
            self.asset_intel_note_source_reliability_combo.addItem(value, value)
        self.asset_intel_note_info_credibility_combo = QComboBox()
        self.asset_intel_note_info_credibility_combo.addItem("Unknown", "")
        for value in ["1", "2", "3", "4", "5", "6"]:
            self.asset_intel_note_info_credibility_combo.addItem(value, value)
        self.asset_intel_note_event_datetime = QDateTimeEdit()
        self.asset_intel_note_event_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.asset_intel_note_event_datetime.setCalendarPopup(True)
        self.asset_intel_note_event_datetime.setDateTime(QDateTime.currentDateTimeUtc())
        self.asset_intel_note_tags_input = QLineEdit()
        self.asset_intel_note_tags_input.setPlaceholderText("comma,separated,tags")
        self.asset_intel_note_location_input = QLineEdit()
        self.asset_intel_note_source_ref_input = QLineEdit()
        self.asset_intel_note_ai_checkbox = QCheckBox("AI-generated note")
        self.asset_intel_note_text_input = QTextEdit()
        self.asset_intel_note_text_input.setPlaceholderText("event description, implications, recommended action...")

        note_form.addRow("Analyst", self.asset_intel_note_analyst_input)
        note_form.addRow("Title", self.asset_intel_note_title_input)
        note_form.addRow("Type", self.asset_intel_note_type_combo)
        note_form.addRow("Priority", self.asset_intel_note_priority_combo)
        note_form.addRow("Confidence", self.asset_intel_note_confidence_combo)
        note_form.addRow("Source Reliability", self.asset_intel_note_source_reliability_combo)
        note_form.addRow("Info Credibility", self.asset_intel_note_info_credibility_combo)
        note_form.addRow("Event Time (UTC)", self.asset_intel_note_event_datetime)
        note_form.addRow("Tags", self.asset_intel_note_tags_input)
        note_form.addRow("Location", self.asset_intel_note_location_input)
        note_form.addRow("Source Ref", self.asset_intel_note_source_ref_input)
        note_form.addRow(self.asset_intel_note_ai_checkbox)
        note_form.addRow("Note", self.asset_intel_note_text_input)

        note_buttons = QHBoxLayout()
        self.asset_intel_note_add_btn = QPushButton("Add Note")
        self.asset_intel_note_add_btn.clicked.connect(self._emit_asset_intel_note_create_request)
        self.asset_intel_note_update_btn = QPushButton("Update Note")
        self.asset_intel_note_update_btn.clicked.connect(self._emit_asset_intel_note_update_request)
        self.asset_intel_note_delete_btn = QPushButton("Delete Note")
        self.asset_intel_note_delete_btn.clicked.connect(self._emit_asset_intel_note_delete_request)
        self.asset_intel_note_clear_btn = QPushButton("Clear")
        self.asset_intel_note_clear_btn.clicked.connect(self._clear_asset_intel_note_form)
        note_buttons.addWidget(self.asset_intel_note_add_btn)
        note_buttons.addWidget(self.asset_intel_note_update_btn)
        note_buttons.addWidget(self.asset_intel_note_delete_btn)
        note_buttons.addWidget(self.asset_intel_note_clear_btn)
        note_buttons.addStretch(1)

        notes_layout.addLayout(note_scope_row)
        notes_layout.addWidget(self.asset_intel_notes_table, 1)
        notes_layout.addLayout(note_form)
        notes_layout.addLayout(note_buttons)
        detail_tabs.addTab(notes_tab, "Analyst Notes")

        raw_tab = QWidget()
        raw_layout = QVBoxLayout(raw_tab)
        raw_layout.setContentsMargins(0, 0, 0, 0)
        self.asset_intel_raw_text = QTextEdit()
        self.asset_intel_raw_text.setReadOnly(True)
        self.asset_intel_raw_text.setPlaceholderText("Raw extracted notes/text blocks appear here.")
        raw_layout.addWidget(self.asset_intel_raw_text)
        detail_tabs.addTab(raw_tab, "Raw")

        sources_tab = QWidget()
        sources_layout = QVBoxLayout(sources_tab)
        sources_layout.setContentsMargins(0, 0, 0, 0)
        self.asset_intel_sources_list = QListWidget()
        self.asset_intel_sources_list.itemDoubleClicked.connect(
            lambda _item: self._open_selected_asset_intel_source_link()
        )
        self.asset_intel_sources_list.setToolTip("Double-click a source link to open it in your browser.")
        sources_layout.addWidget(self.asset_intel_sources_list)
        detail_tabs.addTab(sources_tab, "Sources")

        self.asset_intel_query_results_tabs = QTabWidget()

        query_tab = QWidget()
        self.asset_intel_query_tab = query_tab
        query_layout_outer = QVBoxLayout(query_tab)
        query_layout_outer.setContentsMargins(0, 0, 0, 0)
        query_layout_outer.setSpacing(8)
        query_layout_outer.addWidget(intro)
        query_layout_outer.addWidget(query_group)
        query_layout_outer.addLayout(query_actions_row)
        query_layout_outer.addStretch(1)
        self.asset_intel_query_results_tabs.addTab(query_tab, "Asset Query")

        results_tab = QWidget()
        self.asset_intel_results_tab = results_tab
        results_layout = QVBoxLayout(results_tab)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(6)
        results_layout.addWidget(self.asset_intel_results_list, 1)
        self.asset_intel_query_results_tabs.addTab(results_tab, "Query Results")

        asset_details_tab = QWidget()
        self.asset_intel_details_tab = asset_details_tab
        asset_details_layout = QVBoxLayout(asset_details_tab)
        asset_details_layout.setContentsMargins(0, 0, 0, 0)
        asset_details_layout.setSpacing(6)
        asset_details_layout.addWidget(self.asset_intel_status_label)
        asset_details_layout.addLayout(result_actions_row)
        asset_details_layout.addWidget(detail_tabs, 1)
        self.asset_intel_query_results_tabs.addTab(asset_details_tab, "Asset Details")

        layout.addWidget(self.asset_intel_query_results_tabs, 1)
        return tab

    def _build_tasking_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        tasking_tabs = QTabWidget()
        tasking_tabs.addTab(self._build_tasking_adhoc_tab(), "Ad-hocs")
        tasking_tabs.addTab(self._build_mosaic_tab(), "Mosaic")
        layout.addWidget(tasking_tabs, 1)
        return tab

    def _build_tasking_adhoc_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.tasking_status_label = QLabel("Request status: idle")
        self.tasking_status_label.setWordWrap(True)
        self.tasking_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        create_group = QGroupBox("Create Collection Request")
        create_form = QFormLayout(create_group)

        self.tasking_target_type_combo = QComboBox()
        self.tasking_target_type_combo.addItem("Point Target", "point")
        self.tasking_target_type_combo.addItem("Area Target", "area")
        self.tasking_target_type_combo.currentIndexChanged.connect(self._on_tasking_target_type_changed)

        self.tasking_geometry_mode_combo = QComboBox()
        self.tasking_order_name_input = QLineEdit()
        self.tasking_order_name_input.setPlaceholderText("required")
        self.tasking_project_combo = QComboBox()
        self.tasking_project_combo.setEditable(True)
        self.tasking_product_combo = QComboBox()
        self.tasking_start_datetime = QDateTimeEdit()
        self.tasking_start_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.tasking_start_datetime.setCalendarPopup(True)
        self.tasking_end_datetime = QDateTimeEdit()
        self.tasking_end_datetime.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.tasking_end_datetime.setCalendarPopup(True)
        now_utc = QDateTime.currentDateTimeUtc()
        self.tasking_start_datetime.setDateTime(now_utc)
        self.tasking_end_datetime.setDateTime(now_utc.addDays(1))
        self.tasking_cadence_input = QLineEdit()
        self.tasking_cadence_label = QLabel("Revisit Cadence")

        create_form.addRow("Target Type", self.tasking_target_type_combo)
        create_form.addRow("Geometry Source", self.tasking_geometry_mode_combo)
        create_form.addRow("Request Name", self.tasking_order_name_input)
        create_form.addRow("Mission / Operation", self.tasking_project_combo)
        create_form.addRow("Collection Package", self.tasking_product_combo)
        create_form.addRow("Start (UTC)", self.tasking_start_datetime)
        create_form.addRow("End (UTC)", self.tasking_end_datetime)
        create_form.addRow(self.tasking_cadence_label, self.tasking_cadence_input)

        create_help = QLabel(
            "Collection requests use the search access profile. For area targets, select current map extent or selected result footprint."
        )
        create_help.setWordWrap(True)

        create_buttons = QHBoxLayout()
        self.tasking_refresh_btn = QPushButton("Refresh Requests")
        self.tasking_refresh_btn.clicked.connect(self.tasking_refresh_requested.emit)
        self.tasking_submit_btn = QPushButton("Submit Collection Request")
        self.tasking_submit_btn.clicked.connect(self._emit_tasking_submit_request)
        create_buttons.addWidget(self.tasking_refresh_btn)
        create_buttons.addWidget(self.tasking_submit_btn)
        create_buttons.addStretch(1)

        self.tasking_orders_meta_label = QLabel("No tasking orders loaded.")
        self.tasking_orders_meta_label.setWordWrap(True)

        tasking_filter_row = QHBoxLayout()
        tasking_filter_row.addWidget(QLabel("Filter"))
        self.tasking_orders_filter_input = QLineEdit()
        self.tasking_orders_filter_input.setPlaceholderText(
            "Search by time, status, package, mission, request name, type, or ID..."
        )
        self.tasking_orders_filter_input.textChanged.connect(lambda _text: self._apply_tasking_order_filters())
        tasking_filter_row.addWidget(self.tasking_orders_filter_input, 1)
        tasking_filter_row.addWidget(QLabel("Status"))
        self.tasking_orders_status_filter_combo = QComboBox()
        self.tasking_orders_status_filter_combo.addItem("All Statuses", "")
        self.tasking_orders_status_filter_combo.currentIndexChanged.connect(
            lambda _idx: self._apply_tasking_order_filters()
        )
        tasking_filter_row.addWidget(self.tasking_orders_status_filter_combo)
        tasking_filter_row.addWidget(QLabel("Mission"))
        self.tasking_orders_project_filter_combo = QComboBox()
        self.tasking_orders_project_filter_combo.addItem("All Missions", "")
        self.tasking_orders_project_filter_combo.currentIndexChanged.connect(
            lambda _idx: self._apply_tasking_order_filters()
        )
        tasking_filter_row.addWidget(self.tasking_orders_project_filter_combo)

        self.tasking_orders_table = QTableWidget(0, 7)
        self.tasking_orders_table.setHorizontalHeaderLabels(
            ["Created / Updated (UTC)", "Status", "Package", "Mission", "Request Name", "Target", "Order ID"]
        )
        self.tasking_orders_table.setSelectionBehavior(self.tasking_orders_table.SelectRows)
        self.tasking_orders_table.setSelectionMode(self.tasking_orders_table.SingleSelection)
        self.tasking_orders_table.setEditTriggers(self.tasking_orders_table.NoEditTriggers)
        self.tasking_orders_table.setSortingEnabled(True)
        self.tasking_orders_table.sortByColumn(0, Qt.DescendingOrder)
        self.tasking_orders_table.verticalHeader().setVisible(False)
        self.tasking_orders_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tasking_orders_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tasking_orders_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tasking_orders_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tasking_orders_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.tasking_orders_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.tasking_orders_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.tasking_orders_table.itemSelectionChanged.connect(self._on_tasking_order_selection_changed)
        self.tasking_orders_table.setToolTip("Select an order to view detail and refresh order status.")

        self.tasking_order_detail = QTextEdit()
        self.tasking_order_detail.setReadOnly(True)
        self.tasking_order_detail.setPlaceholderText("Select a tasking order to view details.")

        layout.addWidget(self.tasking_status_label)
        layout.addWidget(create_group)
        layout.addWidget(create_help)
        layout.addLayout(create_buttons)
        layout.addWidget(self.tasking_orders_meta_label)
        layout.addLayout(tasking_filter_row)
        layout.addWidget(self.tasking_orders_table, 1)
        layout.addWidget(self.tasking_order_detail, 1)

        self._on_tasking_target_type_changed()
        return tab

    def _build_mosaic_tab(self):
        tab = QWidget()
        root_layout = QVBoxLayout(tab)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(8)

        self.mosaic_tabs = QTabWidget()
        root_layout.addWidget(self.mosaic_tabs, 1)

        create_tab = QWidget()
        create_layout = QVBoxLayout(create_tab)
        create_layout.setContentsMargins(8, 8, 8, 8)
        create_layout.setSpacing(8)

        self.mosaic_create_status_label = QLabel("Mosaic create: idle.")
        self.mosaic_create_status_label.setWordWrap(True)
        self.mosaic_create_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        create_form_group = QGroupBox("Mosaic Create")
        create_form = QFormLayout(create_form_group)

        self.mosaic_aoi_source_combo = QComboBox()
        self.mosaic_aoi_source_combo.addItem("Current Map Extent", "map_extent")
        self.mosaic_aoi_source_combo.addItem("Selected Polygon Layer", "polygon_layer")
        self.mosaic_aoi_source_combo.currentIndexChanged.connect(self._on_mosaic_aoi_source_changed)

        layer_pick = QWidget()
        layer_pick_layout = QHBoxLayout(layer_pick)
        layer_pick_layout.setContentsMargins(0, 0, 0, 0)
        layer_pick_layout.setSpacing(6)
        self.mosaic_aoi_layer_combo = QComboBox()
        self.mosaic_aoi_layer_refresh_btn = QPushButton("Refresh")
        self.mosaic_aoi_layer_refresh_btn.clicked.connect(self._refresh_mosaic_polygon_layer_options)
        layer_pick_layout.addWidget(self.mosaic_aoi_layer_combo, 1)
        layer_pick_layout.addWidget(self.mosaic_aoi_layer_refresh_btn)

        self.mosaic_project_id_input = QLineEdit()
        self.mosaic_project_id_input.setPlaceholderText("required, unique per campaign")
        project_row = QWidget()
        project_row_layout = QHBoxLayout(project_row)
        project_row_layout.setContentsMargins(0, 0, 0, 0)
        project_row_layout.setSpacing(6)
        project_row_layout.addWidget(self.mosaic_project_id_input, 1)
        self.mosaic_add_tasking_checkbox = QCheckBox("Add Tasking")
        self.mosaic_add_tasking_checkbox.setChecked(True)
        self.mosaic_add_tasking_checkbox.setToolTip(
            "When checked, all tiles are submitted immediately. "
            "When unchecked, tiles are stored only and can be tasked one-by-one in Tracking."
        )
        project_row_layout.addWidget(self.mosaic_add_tasking_checkbox)

        self.mosaic_estimated_price_label = QLabel("Estimated price: $0.00")
        self.mosaic_estimated_price_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.mosaic_estimated_area_label = QLabel("Total clipped area: 0.00 km2")
        self.mosaic_estimated_area_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        create_form.addRow("AOI Source", self.mosaic_aoi_source_combo)
        create_form.addRow("AOI Polygon Layer", layer_pick)
        create_form.addRow("Project ID", project_row)

        create_action_row = QHBoxLayout()
        self.mosaic_breakdown_btn = QPushButton("Breakdown AOI")
        self.mosaic_breakdown_btn.clicked.connect(self._emit_mosaic_breakdown_request)
        self.mosaic_accept_btn = QPushButton("Accept")
        self.mosaic_accept_btn.clicked.connect(self._emit_mosaic_accept_request)
        create_action_row.addWidget(self.mosaic_breakdown_btn)
        create_action_row.addWidget(self.mosaic_accept_btn)
        create_action_row.addStretch(1)

        self.mosaic_breakdown_table = QTableWidget(0, 4)
        self.mosaic_breakdown_table.setHorizontalHeaderLabels(
            ["Tile ID", "Clipped Area (km2)", "Grid X", "Grid Y"]
        )
        self.mosaic_breakdown_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.mosaic_breakdown_table.setSelectionMode(QTableWidget.SingleSelection)
        self.mosaic_breakdown_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.mosaic_breakdown_table.verticalHeader().setVisible(False)
        self.mosaic_breakdown_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.mosaic_breakdown_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.mosaic_breakdown_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.mosaic_breakdown_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        create_layout.addWidget(self.mosaic_create_status_label)
        create_layout.addWidget(create_form_group)
        create_layout.addLayout(create_action_row)
        create_layout.addWidget(self.mosaic_estimated_area_label)
        create_layout.addWidget(self.mosaic_estimated_price_label)
        create_layout.addWidget(self.mosaic_breakdown_table, 1)

        tracking_tab = QWidget()
        tracking_layout = QVBoxLayout(tracking_tab)
        tracking_layout.setContentsMargins(8, 8, 8, 8)
        tracking_layout.setSpacing(8)

        self.mosaic_tracking_status_label = QLabel("Mosaic tracking: idle.")
        self.mosaic_tracking_status_label.setWordWrap(True)
        self.mosaic_tracking_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        tracking_controls = QHBoxLayout()
        tracking_controls.addWidget(QLabel("Project"))
        self.mosaic_tracking_project_combo = QComboBox()
        self.mosaic_tracking_project_combo.currentIndexChanged.connect(self._on_mosaic_tracking_project_changed)
        tracking_controls.addWidget(self.mosaic_tracking_project_combo, 1)
        self.mosaic_projects_refresh_btn = QPushButton("Refresh Projects")
        self.mosaic_projects_refresh_btn.clicked.connect(self.mosaic_refresh_projects_requested.emit)
        tracking_controls.addWidget(self.mosaic_projects_refresh_btn)
        self.mosaic_refresh_status_btn = QPushButton("Refresh Status")
        self.mosaic_refresh_status_btn.clicked.connect(self._emit_mosaic_refresh_status_request)
        tracking_controls.addWidget(self.mosaic_refresh_status_btn)
        self.mosaic_delete_project_btn = QPushButton("Delete Mosaic")
        self.mosaic_delete_project_btn.clicked.connect(self._emit_mosaic_delete_request)
        tracking_controls.addWidget(self.mosaic_delete_project_btn)
        self.mosaic_show_tiling_checkbox = QCheckBox("Show Tiling")
        self.mosaic_show_tiling_checkbox.toggled.connect(self._emit_mosaic_show_tiling_request)
        tracking_controls.addWidget(self.mosaic_show_tiling_checkbox)

        self.mosaic_tracking_table = QTableWidget(0, 10)
        self.mosaic_tracking_table.setHorizontalHeaderLabels(
            [
                "Tile ID",
                "Area (km2)",
                "API Status",
                "QA Status",
                "Latest Collection ID",
                "Attempts",
                "Preview",
                "Accept",
                "Re-Task",
                "Cancel",
            ]
        )
        self.mosaic_tracking_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.mosaic_tracking_table.setSelectionMode(QTableWidget.SingleSelection)
        self.mosaic_tracking_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.mosaic_tracking_table.itemSelectionChanged.connect(self._on_mosaic_tracking_selection_changed)
        self.mosaic_tracking_table.verticalHeader().setVisible(False)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeToContents)
        self.mosaic_tracking_table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeToContents)

        tracking_layout.addWidget(self.mosaic_tracking_status_label)
        tracking_layout.addLayout(tracking_controls)
        tracking_layout.addWidget(self.mosaic_tracking_table, 1)

        self.mosaic_tabs.addTab(create_tab, "Create")
        self.mosaic_tabs.addTab(tracking_tab, "Tracking")

        self._refresh_mosaic_polygon_layer_options()
        self._on_mosaic_aoi_source_changed()
        return tab

    def _build_monitoring_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.monitoring_status_label = QLabel("Watch status: idle")
        self.monitoring_status_label.setWordWrap(True)
        self.monitoring_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        subscription_group = QGroupBox("Create Watch Subscription")
        subscription_form = QFormLayout(subscription_group)
        self.monitoring_source_combo = QComboBox()
        self.monitoring_name_input = QLineEdit()
        self.monitoring_name_input.setPlaceholderText("optional subscription name")
        self.monitoring_collection_ids_input = QLineEdit()
        self.monitoring_collection_ids_input.setPlaceholderText("optional csv, e.g. l1d-sr")
        self.monitoring_geometry_mode_combo = QComboBox()
        self.monitoring_geometry_mode_combo.addItem("Current Map Extent", "map_extent")
        self.monitoring_geometry_mode_combo.addItem("Selected Result Footprint", "selected_result_footprint")
        self.monitoring_filters_input = QLineEdit()
        self.monitoring_filters_input.setPlaceholderText("{}")
        self.monitoring_enabled_checkbox = QCheckBox("Enabled")
        self.monitoring_enabled_checkbox.setChecked(True)
        subscription_form.addRow("Sensor Feed", self.monitoring_source_combo)
        subscription_form.addRow("Name", self.monitoring_name_input)
        subscription_form.addRow("Collection IDs", self.monitoring_collection_ids_input)
        subscription_form.addRow("AOI Source", self.monitoring_geometry_mode_combo)
        subscription_form.addRow("Filters JSON", self.monitoring_filters_input)
        subscription_form.addRow(self.monitoring_enabled_checkbox)

        subscription_buttons = QHBoxLayout()
        self.monitoring_create_subscription_btn = QPushButton("Create Watch")
        self.monitoring_create_subscription_btn.clicked.connect(self._emit_monitoring_create_subscription_request)
        self.monitoring_refresh_btn = QPushButton("Refresh Watch Feed")
        self.monitoring_refresh_btn.clicked.connect(self._emit_monitoring_refresh_request)
        self.monitoring_status_filter_combo = QComboBox()
        self.monitoring_status_filter_combo.addItem("All Statuses", "")
        self.monitoring_status_filter_combo.addItem("Open", "open")
        self.monitoring_status_filter_combo.addItem("Acked", "acked")
        self.monitoring_status_filter_combo.addItem("Queued Review", "queued_review")
        subscription_buttons.addWidget(QLabel("Event Status"))
        subscription_buttons.addWidget(self.monitoring_status_filter_combo)
        subscription_buttons.addWidget(self.monitoring_refresh_btn)
        subscription_buttons.addWidget(self.monitoring_create_subscription_btn)
        subscription_buttons.addStretch(1)

        cue_controls = QHBoxLayout()
        self.monitoring_ack_event_btn = QPushButton("Ack Selected Event")
        self.monitoring_ack_event_btn.clicked.connect(self._emit_monitoring_ack_event_request)
        self.monitoring_cue_priority_combo = QComboBox()
        self.monitoring_cue_priority_combo.addItem("Low", "low")
        self.monitoring_cue_priority_combo.addItem("Medium", "medium")
        self.monitoring_cue_priority_combo.addItem("High", "high")
        self.monitoring_cue_priority_combo.addItem("Urgent", "urgent")
        self.monitoring_cue_geometry_mode_combo = QComboBox()
        self.monitoring_cue_geometry_mode_combo.addItem("Event Geometry", "event_geometry")
        self.monitoring_cue_geometry_mode_combo.addItem("Current Map Extent", "map_extent")
        self.monitoring_cue_geometry_mode_combo.addItem("Selected Result Footprint", "selected_result_footprint")
        self.monitoring_create_cue_btn = QPushButton("Create Cue from Event")
        self.monitoring_create_cue_btn.clicked.connect(self._emit_monitoring_create_cue_request)
        cue_controls.addWidget(self.monitoring_ack_event_btn)
        cue_controls.addWidget(QLabel("Cue Priority"))
        cue_controls.addWidget(self.monitoring_cue_priority_combo)
        cue_controls.addWidget(QLabel("Cue Geometry"))
        cue_controls.addWidget(self.monitoring_cue_geometry_mode_combo)
        cue_controls.addWidget(self.monitoring_create_cue_btn)
        cue_controls.addStretch(1)

        lists_tabs = QTabWidget()
        subscriptions_tab = QWidget()
        subscriptions_layout = QVBoxLayout(subscriptions_tab)
        subscriptions_layout.setContentsMargins(0, 0, 0, 0)
        self.monitoring_subscriptions_list = QListWidget()
        self.monitoring_subscriptions_list.currentItemChanged.connect(
            lambda _current, _previous: self._on_monitoring_item_selected()
        )
        subscriptions_layout.addWidget(self.monitoring_subscriptions_list)
        lists_tabs.addTab(subscriptions_tab, "Subscriptions")

        events_tab = QWidget()
        events_layout = QVBoxLayout(events_tab)
        events_layout.setContentsMargins(0, 0, 0, 0)
        self.monitoring_events_list = QListWidget()
        self.monitoring_events_list.currentItemChanged.connect(
            lambda _current, _previous: self._on_monitoring_item_selected()
        )
        events_layout.addWidget(self.monitoring_events_list)
        lists_tabs.addTab(events_tab, "Events")

        cues_tab = QWidget()
        cues_layout = QVBoxLayout(cues_tab)
        cues_layout.setContentsMargins(0, 0, 0, 0)
        self.monitoring_cues_list = QListWidget()
        self.monitoring_cues_list.currentItemChanged.connect(
            lambda _current, _previous: self._on_monitoring_item_selected()
        )
        cues_layout.addWidget(self.monitoring_cues_list)
        lists_tabs.addTab(cues_tab, "Queued Cues")

        self.monitoring_detail_text = QTextEdit()
        self.monitoring_detail_text.setReadOnly(True)
        self.monitoring_detail_text.setPlaceholderText("Select a monitoring row to inspect details.")

        layout.addWidget(self.monitoring_status_label)
        layout.addWidget(subscription_group)
        layout.addLayout(subscription_buttons)
        layout.addLayout(cue_controls)
        layout.addWidget(lists_tabs, 1)
        layout.addWidget(self.monitoring_detail_text, 1)
        return tab

    def _build_simulation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.simulation_status_label = QLabel("Simulation status: idle")
        self.simulation_status_label.setWordWrap(True)
        self.simulation_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.simulation_status_label)

        constellation_group = QGroupBox("Constellation Configuration")
        constellation_layout = QVBoxLayout(constellation_group)
        constellation_layout.setContentsMargins(8, 8, 8, 8)
        constellation_layout.setSpacing(6)

        self.simulation_sat_count_label = QLabel("Satellites configured: 0")
        self.simulation_sat_count_label.setWordWrap(True)
        constellation_layout.addWidget(self.simulation_sat_count_label)

        self.simulation_sat_table = QTableWidget(0, 6)
        self.simulation_sat_table.setHorizontalHeaderLabels(
            ["Include", "Enabled", "Satellite ID", "Name", "Swath (km)", "Priority"]
        )
        self.simulation_sat_table.verticalHeader().setVisible(False)
        self.simulation_sat_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.simulation_sat_table.setSelectionMode(QTableWidget.SingleSelection)
        self.simulation_sat_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.simulation_sat_table.horizontalHeader().setStretchLastSection(True)
        self.simulation_sat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.simulation_sat_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.simulation_sat_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.simulation_sat_table.itemChanged.connect(self._on_simulation_sat_table_item_changed)
        constellation_layout.addWidget(self.simulation_sat_table, 1)

        sat_btn_row = QHBoxLayout()
        self.simulation_add_sat_btn = QPushButton("Add")
        self.simulation_add_sat_btn.clicked.connect(self._on_simulation_add_satellite)
        self.simulation_edit_sat_btn = QPushButton("Edit")
        self.simulation_edit_sat_btn.clicked.connect(self._on_simulation_edit_satellite)
        self.simulation_remove_sat_btn = QPushButton("Remove")
        self.simulation_remove_sat_btn.clicked.connect(self._on_simulation_remove_satellite)
        self.simulation_import_sat_btn = QPushButton("Import TLE")
        self.simulation_import_sat_btn.clicked.connect(self._on_simulation_import_satellites)
        self.simulation_export_sat_btn = QPushButton("Export Config")
        self.simulation_export_sat_btn.clicked.connect(self._on_simulation_export_config)
        sat_btn_row.addWidget(self.simulation_add_sat_btn)
        sat_btn_row.addWidget(self.simulation_edit_sat_btn)
        sat_btn_row.addWidget(self.simulation_remove_sat_btn)
        sat_btn_row.addWidget(self.simulation_import_sat_btn)
        sat_btn_row.addWidget(self.simulation_export_sat_btn)
        sat_btn_row.addStretch(1)
        constellation_layout.addLayout(sat_btn_row)

        params_group = QGroupBox("Simulation Parameters")
        params_form = QFormLayout(params_group)

        self.simulation_selection_mode_combo = QComboBox()
        self.simulation_selection_mode_combo.addItem("Top N by Priority", "top_n")
        self.simulation_selection_mode_combo.addItem("Manual Selection", "manual")
        self.simulation_selection_mode_combo.currentIndexChanged.connect(
            self._on_simulation_selection_mode_changed
        )

        self.simulation_satellite_count_spin = QSpinBox()
        self.simulation_satellite_count_spin.setRange(1, 999)
        self.simulation_satellite_count_spin.setValue(1)
        self.simulation_satellite_count_label = QLabel("Satellites to include")

        self.simulation_sat_selection_hint = QLabel("Top N mode: enabled satellites are sorted by priority.")
        self.simulation_sat_selection_hint.setWordWrap(True)

        self.simulation_scenario_combo = QComboBox()
        self.simulation_scenario_combo.addItem("Coverage Analysis", "coverage_analysis")
        self.simulation_scenario_combo.addItem("Point Target Revisit", "point_revisit_analysis")
        self.simulation_scenario_combo.currentIndexChanged.connect(self._on_simulation_scenario_changed)

        self.simulation_aoi_source_combo = QComboBox()
        self.simulation_aoi_source_combo.addItem("Current Map Extent", "map_extent")
        self.simulation_aoi_source_combo.addItem("Selected Polygon Layer", "polygon_layer")
        self.simulation_aoi_source_label = QLabel("AOI Source")

        layer_pick = QWidget()
        layer_pick_layout = QHBoxLayout(layer_pick)
        layer_pick_layout.setContentsMargins(0, 0, 0, 0)
        layer_pick_layout.setSpacing(6)
        self.simulation_aoi_layer_pick = layer_pick
        self.simulation_aoi_layer_label = QLabel("AOI Polygon Layer")
        self.simulation_aoi_layer_combo = QComboBox()
        self.simulation_aoi_layer_refresh_btn = QPushButton("Refresh")
        self.simulation_aoi_layer_refresh_btn.clicked.connect(self._refresh_simulation_polygon_layer_options)
        layer_pick_layout.addWidget(self.simulation_aoi_layer_combo, 1)
        layer_pick_layout.addWidget(self.simulation_aoi_layer_refresh_btn)

        self.simulation_off_nadir_spin = QDoubleSpinBox()
        self.simulation_off_nadir_spin.setDecimals(1)
        self.simulation_off_nadir_spin.setRange(0.1, 60.0)
        self.simulation_off_nadir_spin.setSingleStep(0.5)
        self.simulation_off_nadir_spin.setValue(30.0)

        now_utc = QDateTime.currentDateTimeUtc()
        self.simulation_start_dt = QDateTimeEdit()
        self.simulation_start_dt.setCalendarPopup(True)
        self.simulation_start_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.simulation_start_dt.setDateTime(now_utc)

        self.simulation_end_dt = QDateTimeEdit()
        self.simulation_end_dt.setCalendarPopup(True)
        self.simulation_end_dt.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.simulation_end_dt.setDateTime(now_utc.addDays(1))

        self.simulation_time_step_spin = QSpinBox()
        self.simulation_time_step_spin.setRange(10, 3600)
        self.simulation_time_step_spin.setSingleStep(10)
        self.simulation_time_step_spin.setValue(60)

        params_form.addRow("Scenario", self.simulation_scenario_combo)
        params_form.addRow("Selection Mode", self.simulation_selection_mode_combo)
        params_form.addRow(self.simulation_satellite_count_label, self.simulation_satellite_count_spin)
        params_form.addRow(self.simulation_aoi_source_label, self.simulation_aoi_source_combo)
        params_form.addRow(self.simulation_aoi_layer_label, layer_pick)
        params_form.addRow("Max Off-Nadir (deg)", self.simulation_off_nadir_spin)
        params_form.addRow("Start UTC", self.simulation_start_dt)
        params_form.addRow("End UTC", self.simulation_end_dt)
        params_form.addRow("Time Step (sec)", self.simulation_time_step_spin)

        self.simulation_target_group = QGroupBox("Point Target Input")
        target_form = QFormLayout(self.simulation_target_group)
        self.simulation_target_lat_spin = QDoubleSpinBox()
        self.simulation_target_lat_spin.setDecimals(6)
        self.simulation_target_lat_spin.setRange(-90.0, 90.0)
        self.simulation_target_lat_spin.setSingleStep(0.01)
        self.simulation_target_lat_spin.setValue(0.0)
        self.simulation_target_lat_spin.valueChanged.connect(self._on_simulation_target_coordinate_changed)
        self.simulation_target_lon_spin = QDoubleSpinBox()
        self.simulation_target_lon_spin.setDecimals(6)
        self.simulation_target_lon_spin.setRange(-180.0, 180.0)
        self.simulation_target_lon_spin.setSingleStep(0.01)
        self.simulation_target_lon_spin.setValue(0.0)
        self.simulation_target_lon_spin.valueChanged.connect(self._on_simulation_target_coordinate_changed)
        self.simulation_target_label_input = QLineEdit()
        self.simulation_target_label_input.setPlaceholderText("Optional label")
        self.simulation_target_label_input.textEdited.connect(self._on_simulation_target_label_changed)
        self.simulation_target_source_label = QLabel("Target source: manual")
        self.simulation_pick_target_btn = QPushButton("Pick from Map")
        self.simulation_pick_target_btn.clicked.connect(self._on_simulation_pick_target_clicked)
        target_form.addRow("Latitude (deg)", self.simulation_target_lat_spin)
        target_form.addRow("Longitude (deg)", self.simulation_target_lon_spin)
        target_form.addRow("Target Label", self.simulation_target_label_input)
        target_form.addRow("Source", self.simulation_target_source_label)
        target_form.addRow("", self.simulation_pick_target_btn)

        self.simulation_progress_label = QLabel("Ready.")
        self.simulation_progress_label.setWordWrap(True)
        self.simulation_progress_bar = QProgressBar()
        self.simulation_progress_bar.setRange(0, 1)
        self.simulation_progress_bar.setValue(0)

        action_row = QHBoxLayout()
        self.simulation_start_btn = QPushButton("Start Simulation")
        self.simulation_start_btn.clicked.connect(self._emit_simulation_start_request)
        self.simulation_cancel_btn = QPushButton("Cancel")
        self.simulation_cancel_btn.clicked.connect(self.simulation_cancel_requested.emit)
        self.simulation_cancel_btn.setEnabled(False)
        action_row.addWidget(self.simulation_start_btn)
        action_row.addWidget(self.simulation_cancel_btn)
        action_row.addStretch(1)

        self.simulation_day_group = QGroupBox("Day Navigation")
        day_layout = QVBoxLayout(self.simulation_day_group)
        day_layout.setContentsMargins(8, 8, 8, 8)
        day_layout.setSpacing(6)

        day_nav_row = QHBoxLayout()
        self.simulation_first_day_btn = QPushButton("<<")
        self.simulation_first_day_btn.clicked.connect(self.simulation_first_day_requested.emit)
        self.simulation_first_day_btn.setEnabled(False)
        self.simulation_prev_30_days_btn = QPushButton("30d<")
        self.simulation_prev_30_days_btn.clicked.connect(self.simulation_prev_30_days_requested.emit)
        self.simulation_prev_30_days_btn.setEnabled(False)
        self.simulation_prev_day_btn = QPushButton("1d<")
        self.simulation_prev_day_btn.clicked.connect(self.simulation_prev_day_requested.emit)
        self.simulation_prev_day_btn.setEnabled(False)
        self.simulation_next_day_btn = QPushButton(">1d")
        self.simulation_next_day_btn.clicked.connect(self.simulation_next_day_requested.emit)
        self.simulation_next_day_btn.setEnabled(False)
        self.simulation_next_30_days_btn = QPushButton(">30d")
        self.simulation_next_30_days_btn.clicked.connect(self.simulation_next_30_days_requested.emit)
        self.simulation_next_30_days_btn.setEnabled(False)
        self.simulation_last_day_btn = QPushButton(">>")
        self.simulation_last_day_btn.clicked.connect(self.simulation_last_day_requested.emit)
        self.simulation_last_day_btn.setEnabled(False)
        self.simulation_day_label = QLabel("--")
        self.simulation_day_label.setAlignment(Qt.AlignCenter)
        day_nav_row.addWidget(self.simulation_first_day_btn)
        day_nav_row.addWidget(self.simulation_prev_30_days_btn)
        day_nav_row.addWidget(self.simulation_prev_day_btn)
        day_nav_row.addWidget(self.simulation_next_day_btn)
        day_nav_row.addWidget(self.simulation_next_30_days_btn)
        day_nav_row.addWidget(self.simulation_last_day_btn)

        self.simulation_day_imaged_label = QLabel("Imaged today: 0.00 km2")
        self.simulation_day_total_label = QLabel("Total imaged up to day: 0.00 km2")
        self.simulation_day_unique_label = QLabel("Unique covered up to day: 0.00 km2")
        self.simulation_day_passes_label = QLabel("Collection passes today: 0")

        day_layout.addLayout(day_nav_row)
        day_layout.addWidget(self.simulation_day_label)
        day_layout.addWidget(self.simulation_day_imaged_label)
        day_layout.addWidget(self.simulation_day_total_label)
        day_layout.addWidget(self.simulation_day_unique_label)
        day_layout.addWidget(self.simulation_day_passes_label)

        self.simulation_summary_group = QGroupBox("Simulation Summary")
        summary_layout = QVBoxLayout(self.simulation_summary_group)
        summary_layout.setContentsMargins(8, 8, 8, 8)
        summary_layout.setSpacing(6)
        self.simulation_summary_aoi_label = QLabel("AOI area: 0.00 km2")
        self.simulation_summary_unique_label = QLabel("Total unique area covered: 0.00 km2")
        self.simulation_summary_coverage_label = QLabel("AOI covered: 0.00%")
        self.simulation_summary_total_label = QLabel("Total area imaged: 0.00 km2")
        self.simulation_summary_passes_label = QLabel("Total collection passes: 0")
        summary_layout.addWidget(self.simulation_summary_aoi_label)
        summary_layout.addWidget(self.simulation_summary_unique_label)
        summary_layout.addWidget(self.simulation_summary_coverage_label)
        summary_layout.addWidget(self.simulation_summary_total_label)
        summary_layout.addWidget(self.simulation_summary_passes_label)

        self.simulation_revisit_group = QGroupBox("Point Revisit Summary (--, --):")
        revisit_layout = QVBoxLayout(self.simulation_revisit_group)
        revisit_layout.setContentsMargins(8, 8, 8, 8)
        revisit_layout.setSpacing(6)
        self.simulation_revisit_summary_table = QTableWidget(0, 3)
        self.simulation_revisit_summary_table.setHorizontalHeaderLabels(
            ["Metric", "Minutes", "Days"]
        )
        self.simulation_revisit_summary_table.verticalHeader().setVisible(False)
        self.simulation_revisit_summary_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.simulation_revisit_summary_table.setSelectionMode(QTableWidget.SingleSelection)
        self.simulation_revisit_summary_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.simulation_revisit_summary_table.setAlternatingRowColors(True)
        summary_header = self.simulation_revisit_summary_table.horizontalHeader()
        summary_header.setSectionResizeMode(QHeaderView.Stretch)
        revisit_layout.addWidget(self.simulation_revisit_summary_table)

        self.simulation_revisit_events_group = QGroupBox("Point Revisit Events : 0 Collections")
        revisit_events_layout = QVBoxLayout(self.simulation_revisit_events_group)
        revisit_events_layout.setContentsMargins(8, 8, 8, 8)
        revisit_events_layout.setSpacing(6)
        self.simulation_revisit_events_table = QTableWidget(0, 6)
        self.simulation_revisit_events_table.setHorizontalHeaderLabels(
            [
                "Event UTC",
                "Satellite ID",
                "Pass Start UTC",
                "Pass End UTC",
                "Closest Distance (km)",
                "Closest Off-Nadir (deg)",
            ]
        )
        self.simulation_revisit_events_table.verticalHeader().setVisible(False)
        self.simulation_revisit_events_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.simulation_revisit_events_table.setSelectionMode(QTableWidget.SingleSelection)
        self.simulation_revisit_events_table.setEditTriggers(QTableWidget.NoEditTriggers)
        events_header = self.simulation_revisit_events_table.horizontalHeader()
        events_header.setSectionResizeMode(QHeaderView.Interactive)
        events_header.setStretchLastSection(False)
        self.simulation_revisit_events_table.setColumnWidth(0, 170)
        self.simulation_revisit_events_table.setColumnWidth(1, 130)
        self.simulation_revisit_events_table.setColumnWidth(2, 170)
        self.simulation_revisit_events_table.setColumnWidth(3, 170)
        self.simulation_revisit_events_table.setColumnWidth(4, 170)
        self.simulation_revisit_events_table.setColumnWidth(5, 190)
        revisit_events_layout.addWidget(self.simulation_revisit_events_table)

        self.simulation_config_tab = QWidget()
        config_layout = QVBoxLayout(self.simulation_config_tab)
        config_layout.setContentsMargins(8, 8, 8, 8)
        config_layout.setSpacing(8)
        config_layout.addWidget(constellation_group, 3)
        config_layout.addWidget(params_group)
        config_layout.addWidget(self.simulation_target_group)
        config_layout.addWidget(self.simulation_sat_selection_hint)
        config_layout.addWidget(self.simulation_progress_label)
        config_layout.addWidget(self.simulation_progress_bar)
        config_layout.addLayout(action_row)
        config_layout.addStretch(1)

        self.simulation_results_tab = QWidget()
        results_layout = QVBoxLayout(self.simulation_results_tab)
        results_layout.setContentsMargins(8, 8, 8, 8)
        results_layout.setSpacing(8)
        results_layout.addWidget(self.simulation_day_group)
        results_layout.addWidget(self.simulation_summary_group)
        results_layout.addWidget(self.simulation_revisit_group)
        results_layout.addWidget(self.simulation_revisit_events_group, 1)
        results_layout.addStretch(1)

        self.simulation_tabs = QTabWidget()
        self.simulation_tabs.addTab(self.simulation_config_tab, "Simulation Config")
        self.simulation_tabs.addTab(self.simulation_results_tab, "Simulation Results")
        layout.addWidget(self.simulation_tabs, 1)
        layout.addStretch(1)

        self._refresh_simulation_polygon_layer_options()
        self._on_simulation_selection_mode_changed()
        self._on_simulation_target_coordinate_changed()
        self._on_simulation_scenario_changed()
        return tab

    def _project_raster_layer_options(self):
        options = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsRasterLayer):
                continue
            layer_id = str(layer.id() or "").strip()
            layer_name = str(layer.name() or "").strip() or layer_id
            if not layer_id:
                continue
            provider = str(layer.providerType() or "").strip() or "unknown"
            options.append(
                {
                    "id": layer_id,
                    "name": layer_name,
                    "provider": provider,
                }
            )
        options.sort(key=lambda row: (str(row.get("name") or "").lower(), str(row.get("id") or "")))
        return options

    @staticmethod
    def _layer_has_fields(layer, names):
        if layer is None or not isinstance(names, (list, tuple)):
            return False
        try:
            fields = layer.fields()
        except Exception:
            return False
        for name in names:
            if fields.indexFromName(str(name or "").strip()) < 0:
                return False
        return True

    def _project_vector_layer_options(self):
        options = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            layer_id = str(layer.id() or "").strip()
            layer_name = str(layer.name() or "").strip() or layer_id
            if not layer_id:
                continue
            provider = str(layer.providerType() or "").strip() or "unknown"
            options.append(
                {
                    "id": layer_id,
                    "name": layer_name,
                    "provider": provider,
                    "layer": layer,
                }
            )
        options.sort(key=lambda row: (str(row.get("name") or "").lower(), str(row.get("id") or "")))
        return options

    def _project_vessel_detection_layer_options(self):
        required = ["detection_id", "length_m", "width_m", "confidence", "model_version"]
        options = []
        for row in self._project_vector_layer_options():
            layer = row.get("layer")
            if self._layer_has_fields(layer, required) and not self._layer_has_fields(layer, ["qa_status"]):
                options.append(row)
        return options

    def _project_vessel_qa_layer_options(self):
        required = ["qa_status", "label_source", "detection_id", "length_m", "width_m", "model_version"]
        options = []
        for row in self._project_vector_layer_options():
            layer = row.get("layer")
            if self._layer_has_fields(layer, required):
                options.append(row)
        return options

    def _build_utilities_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        info = QLabel(
            "Run lightweight raster utilities on layers currently loaded in this project."
        )
        info.setWordWrap(True)

        create_vrt_group = QGroupBox("Virtual Raster")
        create_vrt_layout = QVBoxLayout(create_vrt_group)
        create_vrt_layout.setContentsMargins(8, 8, 8, 8)
        create_vrt_layout.setSpacing(6)
        create_vrt_desc = QLabel(
            "Create a VRT from one or more project raster layers."
        )
        create_vrt_desc.setWordWrap(True)
        self.create_vrt_btn = QPushButton("Create VRT")
        self.create_vrt_btn.clicked.connect(self._open_create_vrt_dialog)
        create_vrt_layout.addWidget(create_vrt_desc)
        create_vrt_layout.addWidget(self.create_vrt_btn)

        sharpen_group = QGroupBox("Image Processing")
        sharpen_layout = QVBoxLayout(sharpen_group)
        sharpen_layout.setContentsMargins(8, 8, 8, 8)
        sharpen_layout.setSpacing(6)
        sharpen_desc = QLabel(
            "Sharpen or resample a project raster layer."
        )
        sharpen_desc.setWordWrap(True)
        self.sharpen_image_btn = QPushButton("Sharpen Image")
        self.sharpen_image_btn.clicked.connect(self._open_sharpen_image_dialog)
        self.resample_10m_btn = QPushButton("Resample to 10m")
        self.resample_10m_btn.setToolTip(
            "Resample a local raster layer to 10-meter pixel resolution and add it to the project."
        )
        self.resample_10m_btn.clicked.connect(self._open_resample_10m_dialog)
        self.resample_10p8_to_3m_btn = QPushButton(RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M.action_label)
        self.resample_10p8_to_3m_btn.setToolTip(
            "Resample a local raster layer in two steps: 10.8 m, then 3 m."
        )
        self.resample_10p8_to_3m_btn.clicked.connect(self._open_resample_10p8_to_3m_dialog)
        self.resample_2m_to_1m_btn = QPushButton(RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M.action_label)
        self.resample_2m_to_1m_btn.setToolTip(
            "Resample a local raster layer in two steps: 2 m, then 1 m."
        )
        self.resample_2m_to_1m_btn.clicked.connect(self._open_resample_2m_to_1m_dialog)
        self.resample_3p76m_to_1m_btn = QPushButton(RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M.action_label)
        self.resample_3p76m_to_1m_btn.setToolTip(
            "Resample a local raster layer in two steps: 3.76 m, then 1 m."
        )
        self.resample_3p76m_to_1m_btn.clicked.connect(self._open_resample_3p76m_to_1m_dialog)
        sharpen_layout.addWidget(sharpen_desc)
        sharpen_layout.addWidget(self.sharpen_image_btn)
        sharpen_layout.addWidget(self.resample_10m_btn)
        sharpen_layout.addWidget(self.resample_10p8_to_3m_btn)
        sharpen_layout.addWidget(self.resample_2m_to_1m_btn)
        sharpen_layout.addWidget(self.resample_3p76m_to_1m_btn)

        vessel_group = QGroupBox("Vessel Detection")
        vessel_layout = QVBoxLayout(vessel_group)
        vessel_layout.setContentsMargins(8, 8, 8, 8)
        vessel_layout.setSpacing(6)
        vessel_desc = QLabel(
            "Run vessel detection on the current map extent using either axis-aligned boxes (BB) or oriented boxes (OBB)."
        )
        vessel_desc.setWordWrap(True)
        self.vessel_detect_extent_btn = QPushButton("Vessel Detection (BB)")
        self.vessel_detect_extent_btn.setToolTip(
            "Detect vessel(s) using the default BB ONNX model on the current map extent."
        )
        self.vessel_detect_extent_btn.clicked.connect(self._emit_vessel_detect_current_extent_request)
        self.vessel_detect_extent_obb_btn = QPushButton("Vessel Detection (OBB)")
        self.vessel_detect_extent_obb_btn.setToolTip(
            "Detect vessel(s) using the default OBB ONNX model on the current map extent."
        )
        self.vessel_detect_extent_obb_btn.clicked.connect(self._emit_vessel_detect_current_extent_obb_request)
        vessel_layout.addWidget(vessel_desc)
        vessel_layout.addWidget(self.vessel_detect_extent_btn)
        vessel_layout.addWidget(self.vessel_detect_extent_obb_btn)

        vessel_qa_group = QGroupBox("Vessel QA")
        vessel_qa_layout = QVBoxLayout(vessel_qa_group)
        vessel_qa_layout.setContentsMargins(8, 8, 8, 8)
        vessel_qa_layout.setSpacing(6)
        vessel_qa_desc = QLabel(
            "Create QA layers from detections, mark selected labels as approved/rejected, and finalize batch exports."
        )
        vessel_qa_desc.setWordWrap(True)
        self.vessel_qa_create_btn = QPushButton("Create QA Layer")
        self.vessel_qa_create_btn.clicked.connect(self._open_vessel_qa_create_dialog)
        status_row = QHBoxLayout()
        self.vessel_qa_mark_approved_btn = QPushButton("Mark Selected Approved")
        self.vessel_qa_mark_approved_btn.clicked.connect(
            lambda: self._emit_vessel_qa_status("approved")
        )
        self.vessel_qa_mark_rejected_btn = QPushButton("Mark Selected Rejected")
        self.vessel_qa_mark_rejected_btn.clicked.connect(
            lambda: self._emit_vessel_qa_status("rejected")
        )
        self.vessel_qa_mark_pending_btn = QPushButton("Mark Selected Pending")
        self.vessel_qa_mark_pending_btn.clicked.connect(
            lambda: self._emit_vessel_qa_status("pending")
        )
        status_row.addWidget(self.vessel_qa_mark_approved_btn)
        status_row.addWidget(self.vessel_qa_mark_rejected_btn)
        status_row.addWidget(self.vessel_qa_mark_pending_btn)
        self.vessel_qa_finalize_btn = QPushButton("Finalize QA Batch")
        self.vessel_qa_finalize_btn.clicked.connect(self._open_vessel_qa_finalize_dialog)
        vessel_qa_layout.addWidget(vessel_qa_desc)
        vessel_qa_layout.addWidget(self.vessel_qa_create_btn)
        vessel_qa_layout.addLayout(status_row)
        vessel_qa_layout.addWidget(self.vessel_qa_finalize_btn)

        layout.addWidget(info)
        layout.addWidget(create_vrt_group)
        layout.addWidget(sharpen_group)
        layout.addWidget(vessel_group)
        layout.addWidget(vessel_qa_group)
        layout.addStretch(1)
        return tab

    def _open_create_vrt_dialog(self):
        options = self._project_raster_layer_options()
        if not options:
            QMessageBox.warning(
                self,
                "No Raster Layers",
                "Add one or more raster layers to the project before creating a VRT.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Create VRT")
        dialog.resize(760, 420)
        layout = QVBoxLayout(dialog)

        desc = QLabel(
            "Select raster layers to include in the VRT. "
            "Output path is managed automatically in the active campaign."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        list_widget = QListWidget(dialog)
        list_widget.setMinimumHeight(280)
        for row in options:
            label = f"{row['name']} [{row['provider']}]"
            item = QListWidgetItem(label, list_widget)
            item.setData(Qt.UserRole, row["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
        layout.addWidget(list_widget, 1)

        quick_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        clear_btn = QPushButton("Clear All")
        quick_row.addWidget(select_all_btn)
        quick_row.addWidget(clear_btn)
        quick_row.addStretch(1)
        layout.addLayout(quick_row)

        def _set_all(check_state):
            for idx in range(list_widget.count()):
                row_item = list_widget.item(idx)
                if row_item is not None:
                    row_item.setCheckState(check_state)

        select_all_btn.clicked.connect(lambda: _set_all(Qt.Checked))
        clear_btn.clicked.connect(lambda: _set_all(Qt.Unchecked))

        output_name_hint = QLineEdit(dialog)
        output_name_hint.setPlaceholderText("Optional output label (auto if blank)")
        layout.addWidget(output_name_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        selected_layer_ids = []
        for idx in range(list_widget.count()):
            row_item = list_widget.item(idx)
            if row_item is None or row_item.checkState() != Qt.Checked:
                continue
            layer_id = str(row_item.data(Qt.UserRole) or "").strip()
            if layer_id:
                selected_layer_ids.append(layer_id)
        if not selected_layer_ids:
            QMessageBox.warning(self, "Create VRT", "Select at least one raster layer.")
            return

        self.create_vrt_requested.emit(
            {
                "layer_ids": selected_layer_ids,
                "output_name_hint": output_name_hint.text().strip(),
            }
        )

    def _open_sharpen_image_dialog(self):
        options = self._project_raster_layer_options()
        if not options:
            QMessageBox.warning(
                self,
                "No Raster Layers",
                "Add a raster layer to the project before sharpening.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Sharpen Image")
        dialog.resize(620, 210)
        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        layer_combo = QComboBox(dialog)
        for row in options:
            layer_combo.addItem(f"{row['name']} [{row['provider']}]", row["id"])

        sharpen_factor = QDoubleSpinBox(dialog)
        sharpen_factor.setDecimals(2)
        sharpen_factor.setRange(0.1, 8.0)
        sharpen_factor.setSingleStep(0.1)
        sharpen_factor.setValue(1.0)
        sharpen_factor.setToolTip("Unsharp mask intensity multiplier.")

        output_name_hint = QLineEdit(dialog)
        output_name_hint.setPlaceholderText("Optional output label (auto if blank)")

        form.addRow("Input Layer", layer_combo)
        form.addRow("Sharpening Factor", sharpen_factor)
        form.addRow("Output Label", output_name_hint)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        layer_id = str(layer_combo.currentData() or "").strip()
        if not layer_id:
            QMessageBox.warning(self, "Sharpen Image", "Choose an input raster layer.")
            return

        self.sharpen_image_requested.emit(
            {
                "layer_id": layer_id,
                "factor": float(sharpen_factor.value()),
                "output_name_hint": output_name_hint.text().strip(),
            }
        )

    def _open_resample_10m_dialog(self):
        payload = self._collect_resample_request_payload(
            dialog_title="Resample to 10m",
            resolution_label="10 m",
        )
        if payload is None:
            return

        payload["target_resolution_m"] = 10.0
        self.resample_image_10m_requested.emit(payload)

    def _open_resample_10p8_to_3m_dialog(self):
        payload = self._collect_resample_request_payload(
            dialog_title=RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M.dialog_title,
            resolution_label=RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M.resolution_chain_label(),
        )
        if payload is None:
            return
        self.resample_image_10p8_to_3m_requested.emit(payload)

    def _open_resample_2m_to_1m_dialog(self):
        payload = self._collect_resample_request_payload(
            dialog_title=RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M.dialog_title,
            resolution_label=RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M.resolution_chain_label(),
        )
        if payload is None:
            return
        self.resample_image_2m_to_1m_requested.emit(payload)

    def _open_resample_3p76m_to_1m_dialog(self):
        payload = self._collect_resample_request_payload(
            dialog_title=RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M.dialog_title,
            resolution_label=RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M.resolution_chain_label(),
        )
        if payload is None:
            return
        self.resample_image_3p76m_to_1m_requested.emit(payload)

    def _collect_resample_request_payload(self, *, dialog_title, resolution_label):
        options = self._project_raster_layer_options()
        if not options:
            QMessageBox.warning(
                self,
                "No Raster Layers",
                "Add a local georeferenced raster layer to the project before resampling.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(dialog_title)
        dialog.resize(620, 180)
        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        layer_combo = QComboBox(dialog)
        for row in options:
            layer_combo.addItem(f"{row['name']} [{row['provider']}]", row["id"])

        output_name_hint = QLineEdit(dialog)
        output_name_hint.setPlaceholderText("Optional output label (auto if blank)")

        form.addRow("Input Layer", layer_combo)
        form.addRow("Target Resolution", QLabel(str(resolution_label or "").strip() or "N/A"))
        form.addRow("Output Label", output_name_hint)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        layer_id = str(layer_combo.currentData() or "").strip()
        if not layer_id:
            QMessageBox.warning(self, dialog_title, "Choose an input raster layer.")
            return None

        return {
            "layer_id": layer_id,
            "output_name_hint": output_name_hint.text().strip(),
        }

    def _open_vessel_detect_dialog(self):
        options = self._project_raster_layer_options()
        if not options:
            QMessageBox.warning(
                self,
                "No Raster Layers",
                "Add a local georeferenced raster layer to the project before vessel detection.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Detect Vessels")
        dialog.resize(680, 310)
        layout = QVBoxLayout(dialog)

        intro = QLabel(
            "Run vessel detection on a selected raster layer. "
            "For reliable dimensions, use a local georeferenced raster."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        layer_combo = QComboBox(dialog)
        for row in options:
            layer_combo.addItem(f"{row['name']} [{row['provider']}]", row["id"])

        model_row_widget = QWidget(dialog)
        model_row_layout = QHBoxLayout(model_row_widget)
        model_row_layout.setContentsMargins(0, 0, 0, 0)
        model_row_layout.setSpacing(6)
        model_path_edit = QLineEdit(dialog)
        model_path_edit.setPlaceholderText("Path to vessel ONNX model")
        if hasattr(self, "vessel_model_default_path"):
            model_path_edit.setText(str(self.vessel_model_default_path.text() or "").strip())
        browse_model_btn = QPushButton("Browse...", dialog)

        def _browse_model():
            current = str(model_path_edit.text() or "").strip()
            selected, _unused = QFileDialog.getOpenFileName(
                dialog,
                "Select Vessel ONNX Model",
                current,
                "ONNX Model (*.onnx);;All Files (*)",
            )
            selected = str(selected or "").strip()
            if selected:
                model_path_edit.setText(selected)

        browse_model_btn.clicked.connect(_browse_model)
        model_row_layout.addWidget(model_path_edit, 1)
        model_row_layout.addWidget(browse_model_btn)

        conf_spin = QDoubleSpinBox(dialog)
        conf_spin.setDecimals(2)
        conf_spin.setRange(0.01, 1.0)
        conf_spin.setSingleStep(0.05)
        conf_spin.setValue(
            float(self.vessel_conf_default.value()) if hasattr(self, "vessel_conf_default") else 0.25
        )

        iou_spin = QDoubleSpinBox(dialog)
        iou_spin.setDecimals(2)
        iou_spin.setRange(0.01, 1.0)
        iou_spin.setSingleStep(0.05)
        iou_spin.setValue(
            float(self.vessel_iou_default.value()) if hasattr(self, "vessel_iou_default") else 0.45
        )

        max_det_spin = QSpinBox(dialog)
        max_det_spin.setRange(1, 500)
        max_det_spin.setValue(
            int(self.vessel_max_det_default.value()) if hasattr(self, "vessel_max_det_default") else 20
        )

        auto_filter_checkbox = QCheckBox("Auto-apply Asset Intel size filters")
        auto_filter_checkbox.setChecked(True)

        create_qa_checkbox = QCheckBox("Create QA layer from detections")
        create_qa_checkbox.setChecked(True)

        output_name_hint = QLineEdit(dialog)
        output_name_hint.setPlaceholderText("Optional output layer suffix")

        form.addRow("Input Layer", layer_combo)
        form.addRow("ONNX Model", model_row_widget)
        form.addRow("Confidence Threshold", conf_spin)
        form.addRow("IoU Threshold", iou_spin)
        form.addRow("Max Detections", max_det_spin)
        form.addRow(auto_filter_checkbox)
        form.addRow(create_qa_checkbox)
        form.addRow("Output Label", output_name_hint)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        layer_id = str(layer_combo.currentData() or "").strip()
        if not layer_id:
            QMessageBox.warning(self, "Detect Vessels", "Choose an input raster layer.")
            return

        model_path = str(model_path_edit.text() or "").strip()
        if not model_path:
            QMessageBox.warning(self, "Detect Vessels", "Select an ONNX model path.")
            return

        self.vessel_detect_requested.emit(
            {
                "layer_id": layer_id,
                "model_path": model_path,
                "conf_threshold": float(conf_spin.value()),
                "iou_threshold": float(iou_spin.value()),
                "max_detections": int(max_det_spin.value()),
                "autofill_asset_intel_filters": bool(auto_filter_checkbox.isChecked()),
                "create_qa_layer": bool(create_qa_checkbox.isChecked()),
                "output_name_hint": output_name_hint.text().strip(),
            }
        )

    def _emit_vessel_detect_current_extent_request(self):
        model_path = ""
        if hasattr(self, "vessel_model_default_path"):
            model_path = str(self.vessel_model_default_path.text() or "").strip()
        conf_threshold = 0.25
        if hasattr(self, "vessel_conf_default"):
            conf_threshold = float(self.vessel_conf_default.value())
        iou_threshold = 0.45
        if hasattr(self, "vessel_iou_default"):
            iou_threshold = float(self.vessel_iou_default.value())
        max_detections = 20
        if hasattr(self, "vessel_max_det_default"):
            max_detections = int(self.vessel_max_det_default.value())

        self.vessel_detect_extent_requested.emit(
            {
                "model_path": model_path,
                "detection_variant": "bb",
                "conf_threshold": float(conf_threshold),
                "iou_threshold": float(iou_threshold),
                "max_detections": int(max_detections),
                "single_best_only": True,
                "autofill_asset_intel_filters": True,
                "create_qa_layer": False,
                "output_name_hint": "current_extent_bb",
            }
        )

    def _emit_vessel_detect_current_extent_obb_request(self):
        conf_threshold = 0.25
        if hasattr(self, "vessel_conf_default"):
            conf_threshold = float(self.vessel_conf_default.value())
        iou_threshold = 0.45
        if hasattr(self, "vessel_iou_default"):
            iou_threshold = float(self.vessel_iou_default.value())
        max_detections = 20
        if hasattr(self, "vessel_max_det_default"):
            max_detections = int(self.vessel_max_det_default.value())

        self.vessel_detect_extent_requested.emit(
            {
                "detection_variant": "obb",
                "conf_threshold": float(conf_threshold),
                "iou_threshold": float(iou_threshold),
                "max_detections": int(max_detections),
                "single_best_only": True,
                "autofill_asset_intel_filters": True,
                "create_qa_layer": False,
                "output_name_hint": "current_extent_obb",
            }
        )

    def _open_vessel_qa_create_dialog(self):
        options = self._project_vessel_detection_layer_options()
        if not options:
            QMessageBox.warning(
                self,
                "No Detection Layers",
                "Run vessel detection first, or choose a vector layer with vessel detection fields.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Create Vessel QA Layer")
        dialog.resize(560, 180)
        layout = QVBoxLayout(dialog)

        intro = QLabel(
            "Create a QA layer from a vessel detection layer. "
            "New labels can be added manually in the QA layer using QGIS editing tools."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        layer_combo = QComboBox(dialog)
        for row in options:
            layer_combo.addItem(f"{row['name']} [{row['provider']}]", row["id"])
        output_name_hint = QLineEdit(dialog)
        output_name_hint.setPlaceholderText("Optional QA layer suffix")
        form.addRow("Detection Layer", layer_combo)
        form.addRow("Output Label", output_name_hint)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        detection_layer_id = str(layer_combo.currentData() or "").strip()
        if not detection_layer_id:
            QMessageBox.warning(self, "Create QA Layer", "Choose a vessel detection layer.")
            return

        self.vessel_qa_layer_create_requested.emit(
            {
                "detection_layer_id": detection_layer_id,
                "output_name_hint": output_name_hint.text().strip(),
            }
        )

    def _emit_vessel_qa_status(self, qa_status):
        status_key = str(qa_status or "").strip().lower()
        if status_key not in {"approved", "rejected", "pending"}:
            QMessageBox.warning(self, "Vessel QA", "Invalid QA status.")
            return
        self.vessel_qa_status_set_requested.emit({"qa_status": status_key})

    def _open_vessel_qa_finalize_dialog(self):
        options = self._project_vessel_qa_layer_options()
        if not options:
            QMessageBox.warning(
                self,
                "No QA Layers",
                "Create a vessel QA layer first before finalizing a QA batch.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Finalize Vessel QA Batch")
        dialog.resize(620, 280)
        layout = QVBoxLayout(dialog)

        intro = QLabel(
            "Finalize the selected QA layer into a batch export. "
            "Only features with qa_status='approved' are included for training-ready records."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        qa_layer_combo = QComboBox(dialog)
        for row in options:
            qa_layer_combo.addItem(f"{row['name']} [{row['provider']}]", row["id"])

        batch_id = QLineEdit(dialog)
        batch_id.setPlaceholderText("Optional batch id (auto if blank)")

        dataset_id = QLineEdit(dialog)
        dataset_id.setPlaceholderText("Optional dataset id for traceability")

        chip_size_spin = QSpinBox(dialog)
        chip_size_spin.setRange(256, 4096)
        chip_size_spin.setSingleStep(64)
        chip_size_spin.setValue(1024)

        padding_spin = QSpinBox(dialog)
        padding_spin.setRange(0, 1024)
        padding_spin.setSingleStep(16)
        padding_spin.setValue(128)

        form.addRow("QA Layer", qa_layer_combo)
        form.addRow("Batch ID", batch_id)
        form.addRow("Dataset ID", dataset_id)
        form.addRow("Chip Size (px)", chip_size_spin)
        form.addRow("Padding (px)", padding_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QDialog.Accepted:
            return

        qa_layer_id = str(qa_layer_combo.currentData() or "").strip()
        if not qa_layer_id:
            QMessageBox.warning(self, "Finalize QA Batch", "Choose a QA layer.")
            return

        self.vessel_qa_finalize_requested.emit(
            {
                "qa_layer_id": qa_layer_id,
                "batch_id": batch_id.text().strip(),
                "dataset_id": dataset_id.text().strip(),
                "chip_size": int(chip_size_spin.value()),
                "padding": int(padding_spin.value()),
                "split": {"train": 70, "val": 15, "test": 15},
            }
        )

    def _build_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        backend_group = QGroupBox("Backend Streaming")
        backend_form = QFormLayout(backend_group)
        self.backend_api_base_url = QLineEdit()
        self.backend_api_base_url.setPlaceholderText("http://localhost:8000")
        backend_form.addRow("Backend API base URL", self.backend_api_base_url)

        sat_group = QGroupBox("NewSat Constellation")
        sat_form = QFormLayout(sat_group)
        self.sat_auth_mode = QComboBox()
        self.sat_auth_mode.addItems([
            "oauth_client_credentials",
            "auto",
            "bearer",
            "key_secret",
        ])

        self.sat_contract = QLineEdit()
        self.sat_stac_url = QLineEdit()
        self.sat_authcfg_id = QLineEdit()
        self.sat_authcfg_id.setPlaceholderText("QGIS auth config id")

        sat_form.addRow("Auth mode", self.sat_auth_mode)
        sat_form.addRow("Access Profile", self.sat_contract)
        sat_form.addRow("STAC URL", self.sat_stac_url)
        sat_form.addRow("Auth config ID", self.sat_authcfg_id)

        cdse_group = QGroupBox("Merlin / CDSE")
        cdse_form = QFormLayout(cdse_group)
        self.cdse_enabled = QCheckBox("Enable Merlin (Sentinel-2)")
        self.cdse_stac_url = QLineEdit()
        self.cdse_client_id = QLineEdit()
        self.cdse_client_id.setPlaceholderText("CDSE OAuth client id")
        self.cdse_client_secret = QLineEdit()
        self.cdse_client_secret.setPlaceholderText("CDSE OAuth client secret")
        self.cdse_client_secret.setEchoMode(QLineEdit.Password)
        self.cdse_wmts_base_url = QLineEdit()
        self.cdse_wmts_instance_id = QLineEdit()
        self.cdse_wmts_layer_id = QLineEdit()
        self.cdse_wmts_use_backend_proxy = QCheckBox("Prefer backend WMTS proxy endpoint")
        self.cdse_wmts_use_backend_proxy.setChecked(True)
        self.cdse_authcfg_id = QLineEdit()
        self.cdse_authcfg_id.setPlaceholderText("QGIS auth config id")

        cdse_form.addRow(self.cdse_enabled)
        cdse_form.addRow("STAC URL", self.cdse_stac_url)
        cdse_form.addRow("Client ID", self.cdse_client_id)
        cdse_form.addRow("Client Secret", self.cdse_client_secret)
        cdse_form.addRow("WMTS base URL", self.cdse_wmts_base_url)
        cdse_form.addRow("WMTS instance ID", self.cdse_wmts_instance_id)
        cdse_form.addRow("WMTS layer ID", self.cdse_wmts_layer_id)
        cdse_form.addRow(self.cdse_wmts_use_backend_proxy)
        cdse_form.addRow("Auth config ID", self.cdse_authcfg_id)

        asset_intel_group = QGroupBox("Asset Intel")
        asset_intel_form = QFormLayout(asset_intel_group)
        asset_intel_path_widget = QWidget()
        asset_intel_path_layout = QHBoxLayout(asset_intel_path_widget)
        asset_intel_path_layout.setContentsMargins(0, 0, 0, 0)
        asset_intel_path_layout.setSpacing(6)
        self.asset_intel_db_path = QLineEdit()
        self.asset_intel_db_path.setPlaceholderText("Path to asset_intel_prototype.sqlite")
        self.asset_intel_db_browse_btn = QPushButton("Browse...")
        self.asset_intel_db_browse_btn.clicked.connect(self._browse_asset_intel_db_file)
        asset_intel_path_layout.addWidget(self.asset_intel_db_path, 1)
        asset_intel_path_layout.addWidget(self.asset_intel_db_browse_btn)
        asset_intel_form.addRow("SQLite DB Path", asset_intel_path_widget)

        vessel_group = QGroupBox("Vessel Detection")
        vessel_form = QFormLayout(vessel_group)
        vessel_model_widget = QWidget()
        vessel_model_layout = QHBoxLayout(vessel_model_widget)
        vessel_model_layout.setContentsMargins(0, 0, 0, 0)
        vessel_model_layout.setSpacing(6)
        self.vessel_model_default_path = QLineEdit()
        self.vessel_model_default_path.setPlaceholderText("Path to production vessel ONNX model")
        self.vessel_model_browse_btn = QPushButton("Browse...")
        self.vessel_model_browse_btn.clicked.connect(self._browse_vessel_model_file)
        vessel_model_layout.addWidget(self.vessel_model_default_path, 1)
        vessel_model_layout.addWidget(self.vessel_model_browse_btn)

        self.vessel_conf_default = QDoubleSpinBox()
        self.vessel_conf_default.setDecimals(2)
        self.vessel_conf_default.setRange(0.01, 1.0)
        self.vessel_conf_default.setSingleStep(0.05)
        self.vessel_conf_default.setValue(0.25)

        self.vessel_iou_default = QDoubleSpinBox()
        self.vessel_iou_default.setDecimals(2)
        self.vessel_iou_default.setRange(0.01, 1.0)
        self.vessel_iou_default.setSingleStep(0.05)
        self.vessel_iou_default.setValue(0.45)

        self.vessel_max_det_default = QSpinBox()
        self.vessel_max_det_default.setRange(1, 500)
        self.vessel_max_det_default.setValue(20)

        vessel_form.addRow("Default ONNX Model", vessel_model_widget)
        vessel_form.addRow("Default Confidence", self.vessel_conf_default)
        vessel_form.addRow("Default IoU", self.vessel_iou_default)
        vessel_form.addRow("Default Max Detections", self.vessel_max_det_default)

        self.remove_existing_layers = QCheckBox("Remove Existing Layers")
        self.remove_existing_layers.setChecked(True)
        self.remove_existing_layers.setToolTip("Remove existing layers with names starting with 'Image Mate'.")
        self.create_new_layer_on_selection = QCheckBox("Create New Layer Per Selection")
        self.create_new_layer_on_selection.setChecked(False)
        self.create_new_layer_on_selection.setToolTip(
            "When enabled, selecting a result adds a new imagery layer instead of replacing the previous one."
        )

        self.settings_save_btn = QPushButton("Save Integration Settings")
        self.settings_save_btn.clicked.connect(self.settings_saved.emit)
        self.settings_validate_btn = QPushButton("Validate Setup")
        self.settings_validate_btn.clicked.connect(self.validate_requested.emit)
        self.settings_validate_btn.setToolTip("Validate plugin setup and auth wiring.")

        layout.addWidget(backend_group)
        layout.addWidget(sat_group)
        layout.addWidget(cdse_group)
        layout.addWidget(asset_intel_group)
        layout.addWidget(vessel_group)
        layout.addWidget(self.remove_existing_layers)
        layout.addWidget(self.create_new_layer_on_selection)
        layout.addStretch(1)
        layout.addWidget(self.settings_validate_btn)
        layout.addWidget(self.settings_save_btn)
        return tab

    @staticmethod
    def _placeholder_tab(text):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(8, 8, 8, 8)
        label = QLabel(text)
        label.setWordWrap(True)
        tab_layout.addWidget(label)
        tab_layout.addStretch(1)
        return tab

    def _build_status_tab(self):
        """Build the Status/Log tab with runtime information."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Stream status
        stream_label = QLabel("Streaming Health:")
        stream_label.setStyleSheet("font-weight: 600;")
        self.stream_status = QLabel("Stream status: idle")
        self.stream_status.setWordWrap(True)
        self.stream_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # Runtime summary
        runtime_label = QLabel("Runtime Health:")
        runtime_label.setStyleSheet("font-weight: 600; margin-top: 12px;")
        self.runtime_summary = QLabel("Runtime summary unavailable.")
        self.runtime_summary.setWordWrap(True)
        self.runtime_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        layout.addWidget(stream_label)
        layout.addWidget(self.stream_status)
        layout.addWidget(runtime_label)
        layout.addWidget(self.runtime_summary)
        layout.addStretch(1)
        
        return tab
