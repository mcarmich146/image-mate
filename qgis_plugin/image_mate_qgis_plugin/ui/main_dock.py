# -*- coding: utf-8 -*-
"""Main dock widget for Image Mate."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QDate
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QGroupBox,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ImageMateMainDock(QDockWidget):
    validate_requested = pyqtSignal()
    settings_saved = pyqtSignal()
    search_requested = pyqtSignal(dict)
    result_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Image Mate", parent)
        self.setObjectName("imageMateMainDock")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.setMinimumWidth(0)
        self.setMinimumSize(0, 0)

        root = QWidget(self)
        root.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        root.setMinimumWidth(0)
        root.setMinimumSize(0, 0)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QLabel("Image Mate")
        header.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header.setStyleSheet("font-weight: 600; font-size: 14px;")
        header.setWordWrap(True)
        subtitle = QLabel("Phase 1 implementation baseline")
        subtitle.setTextInteractionFlags(Qt.TextSelectableByMouse)
        subtitle.setWordWrap(True)

        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.tabs.addTab(self._build_explore_tab(), "Explore")
        self._settings_tab_index = self.tabs.addTab(self._build_settings_tab(), "Settings")
        self.tabs.addTab(self._placeholder_tab("Tasking UI pending."), "Tasking")
        self.tabs.addTab(self._placeholder_tab("Monitoring UI pending."), "Monitoring")
        self.tabs.addTab(self._placeholder_tab("Workflows/Runs UI pending."), "Workflows")
        self.tabs.addTab(self._build_status_tab(), "Status")

        health_btn = QPushButton("Validate Setup")
        health_btn.clicked.connect(self.validate_requested.emit)
        health_btn.setToolTip("Validate plugin setup and auth wiring.")

        layout.addWidget(header)
        layout.addWidget(subtitle)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(health_btn)

        self.setWidget(root)

    def minimumSizeHint(self):
        return QSize(120, 200)

    def sizeHint(self):
        return QSize(420, 640)

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
        for row in rows:
            label = row.get("title") or row.get("source_id") or "unknown"
            source_id = row.get("source_id") or ""
            enabled = bool(row.get("enabled"))
            if not enabled:
                label = f"{label} (disabled)"
            self.source_combo.addItem(label, source_id)
            model_item = self.source_combo.model().item(self.source_combo.count() - 1)
            if model_item is not None:
                model_item.setEnabled(enabled)
        if prior:
            idx = self.source_combo.findData(prior)
            if idx >= 0:
                self.source_combo.setCurrentIndex(idx)
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

    def load_settings(self, cfg):
        self.backend_api_base_url.setText(cfg.backend_api_base_url)
        self.sat_auth_mode.setCurrentText(cfg.satellogic_auth_mode)
        self.sat_contract.setText(cfg.satellogic_contract_id)
        self.sat_stac_url.setText(cfg.satellogic_stac_url)
        self.sat_authcfg_id.setText(cfg.satellogic_authcfg_id)

        self.cdse_enabled.setChecked(bool(cfg.cdse_enabled))
        self.cdse_stac_url.setText(cfg.cdse_stac_url)
        self.cdse_wmts_base_url.setText(cfg.cdse_wmts_base_url)
        self.cdse_wmts_instance_id.setText(cfg.cdse_wmts_instance_id)
        self.cdse_wmts_layer_id.setText(cfg.cdse_wmts_layer_id)
        self.cdse_authcfg_id.setText(cfg.cdse_authcfg_id)

    def apply_settings_to(self, cfg):
        cfg.backend_api_base_url = self.backend_api_base_url.text().strip() or "http://localhost:8000"
        cfg.satellogic_auth_mode = self.sat_auth_mode.currentText().strip()
        cfg.satellogic_contract_id = self.sat_contract.text().strip()
        cfg.satellogic_stac_url = self.sat_stac_url.text().strip()
        cfg.satellogic_authcfg_id = self.sat_authcfg_id.text().strip()

        cfg.cdse_enabled = bool(self.cdse_enabled.isChecked())
        cfg.cdse_stac_url = self.cdse_stac_url.text().strip()
        cfg.cdse_wmts_base_url = self.cdse_wmts_base_url.text().strip()
        cfg.cdse_wmts_instance_id = self.cdse_wmts_instance_id.text().strip()
        cfg.cdse_wmts_layer_id = self.cdse_wmts_layer_id.text().strip() or "TRUE-COLOR"
        cfg.cdse_authcfg_id = self.cdse_authcfg_id.text().strip()
        return cfg

    def set_contract_id(self, contract_id):
        self.contract_id.setText(str(contract_id or "").strip())

    def set_contract_enabled(self, enabled):
        self.contract_id.setEnabled(bool(enabled))

    def set_results(self, items):
        self.results_list.blockSignals(True)
        self.results_list.clear()
        
        # Group items by outcome_id for multi-tile collections
        groups = {}
        groupable_collections = {"l1d-sr", "l1d", "quickview-visual", "quickview-toa", "l1c"}
        for row in items or []:
            outcome_id = str(row.get("outcome_id") or "").strip()
            collection = str(row.get("collection") or "").strip().lower().replace("_", "-")
            
            # Group multi-tile collections by outcome_id, others individually
            if collection in groupable_collections and outcome_id:
                group_key = f"outcome:{outcome_id}"
            else:
                group_key = str(row.get("id") or "").strip()
            
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(row)
        
        # Display one entry per group
        for group_key, group_items in groups.items():
            # Use first item as representative
            row = group_items[0]
            item_id = str(row.get("id") or "").strip()
            outcome_id = str(row.get("outcome_id") or "").strip()
            source_id = str(row.get("source_id") or "").strip()
            dt = str(row.get("datetime") or "").strip()
            cloud = row.get("cloud_cover")
            gsd = row.get("gsd")
            
            # Show tile count if grouped
            tile_suffix = f" ({len(group_items)} tiles)" if len(group_items) > 1 else ""
            label = (
                f"{dt or 'unknown time'} | {source_id or 'unknown source'} | "
                f"cloud={cloud if cloud is not None else '--'} | gsd={gsd if gsd is not None else '--'}{tile_suffix} | {item_id}"
            )
            q_item = QListWidgetItem(label)
            q_item.setData(Qt.UserRole, item_id)
            q_item.setData(Qt.UserRole + 1, outcome_id)
            self.results_list.addItem(q_item)
        
        self.results_list.blockSignals(False)
        # Auto-select and load the first result
        if self.results_list.count() > 0:
            self.results_list.setCurrentRow(0)

    def current_source_id(self):
        return str(self.source_combo.currentData() or "").strip()

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
        
        self.search_requested.emit(self.current_search_payload())

    def _emit_result_selected(self):
        item = self.results_list.currentItem()
        if item is None:
            return
        item_id = str(item.data(Qt.UserRole) or "").strip()
        if item_id:
            self.result_selected.emit(item_id)

    def _show_results_context_menu(self, pos):
        item = self.results_list.itemAt(pos)
        if item is None:
            return

        item_id = str(item.data(Qt.UserRole) or "").strip()
        outcome_id = str(item.data(Qt.UserRole + 1) or "").strip()

        menu = QMenu(self.results_list)
        act_copy_outcome = menu.addAction("Copy Outcome ID")
        act_copy_item = menu.addAction("Copy Item ID")
        if not outcome_id:
            act_copy_outcome.setEnabled(False)

        selected = menu.exec_(self.results_list.mapToGlobal(pos))
        if selected == act_copy_outcome and outcome_id:
            QApplication.clipboard().setText(outcome_id)
        elif selected == act_copy_item and item_id:
            QApplication.clipboard().setText(item_id)

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

        form.addRow("Source", self.source_combo)
        form.addRow("Collection", self.collection_combo)
        form.addRow("Contract ID", self.contract_id)
        form.addRow("Start date", self.start_date)
        form.addRow("End date", self.end_date)
        form.addRow("Cloud cover <=", self.max_cloud)
        form.addRow("Min GSD (m)", self.min_gsd)
        form.addRow("Max GSD (m)", self.max_gsd)
        form.addRow("Limit", self.limit)
        form.addRow("Satellite name", self.satellite_name)

        btn_row = QHBoxLayout()
        self.search_btn = QPushButton("Search Map Extent")
        self.search_btn.clicked.connect(self._emit_search_request)
        btn_row.addWidget(self.search_btn)
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
        self.results_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_list.customContextMenuRequested.connect(self._show_results_context_menu)
        self.results_list.setToolTip("Selecting a result loads imagery. Right-click to copy Outcome ID or Item ID.")
        results_layout.addWidget(self.results_list)
        output_tabs.addTab(results_tab, "Results")
        
        # Search log tab
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(0, 0, 0, 0)
        self.search_log = QTextEdit()
        self.search_log.setReadOnly(True)
        self.search_log.setPlaceholderText("Search output will appear here.")
        self.search_log.setMinimumWidth(0)
        log_layout.addWidget(self.search_log)
        output_tabs.addTab(log_tab, "Search Log")

        # Debug log tab
        debug_tab = QWidget()
        debug_layout = QVBoxLayout(debug_tab)
        debug_layout.setContentsMargins(0, 0, 0, 0)
        self.debug_log = QTextEdit()
        self.debug_log.setReadOnly(True)
        self.debug_log.setPlaceholderText("Debug output will appear here.")
        self.debug_log.setMinimumWidth(0)
        debug_layout.addWidget(self.debug_log)
        output_tabs.addTab(debug_tab, "Debug Log")

        layout.addLayout(form)
        layout.addLayout(btn_row)
        layout.addWidget(output_tabs, 1)
        return tab

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

        sat_group = QGroupBox("Satellogic")
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
        sat_form.addRow("Contract ID", self.sat_contract)
        sat_form.addRow("STAC URL", self.sat_stac_url)
        sat_form.addRow("Auth config ID", self.sat_authcfg_id)

        cdse_group = QGroupBox("Merlin / CDSE")
        cdse_form = QFormLayout(cdse_group)
        self.cdse_enabled = QCheckBox("Enable Merlin (Sentinel-2)")
        self.cdse_stac_url = QLineEdit()
        self.cdse_wmts_base_url = QLineEdit()
        self.cdse_wmts_instance_id = QLineEdit()
        self.cdse_wmts_layer_id = QLineEdit()
        self.cdse_authcfg_id = QLineEdit()
        self.cdse_authcfg_id.setPlaceholderText("QGIS auth config id")

        cdse_form.addRow(self.cdse_enabled)
        cdse_form.addRow("STAC URL", self.cdse_stac_url)
        cdse_form.addRow("WMTS base URL", self.cdse_wmts_base_url)
        cdse_form.addRow("WMTS instance ID", self.cdse_wmts_instance_id)
        cdse_form.addRow("WMTS layer ID", self.cdse_wmts_layer_id)
        cdse_form.addRow("Auth config ID", self.cdse_authcfg_id)

        self.remove_existing_layers = QCheckBox("Remote Existing Layers")
        self.remove_existing_layers.setChecked(True)
        self.remove_existing_layers.setToolTip("Remove existing layers with names starting with 'Image Mate'.")
        self.create_new_layer_on_selection = QCheckBox("Create New Layer Per Selection")
        self.create_new_layer_on_selection.setChecked(False)
        self.create_new_layer_on_selection.setToolTip(
            "When enabled, selecting a result adds a new imagery layer instead of replacing the previous one."
        )

        self.settings_save_btn = QPushButton("Save Settings")
        self.settings_save_btn.clicked.connect(self.settings_saved.emit)

        layout.addWidget(backend_group)
        layout.addWidget(sat_group)
        layout.addWidget(cdse_group)
        layout.addWidget(self.remove_existing_layers)
        layout.addWidget(self.create_new_layer_on_selection)
        layout.addStretch(1)
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
        stream_label = QLabel("Stream Status:")
        stream_label.setStyleSheet("font-weight: 600;")
        self.stream_status = QLabel("Stream status: idle")
        self.stream_status.setWordWrap(True)
        self.stream_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # Runtime summary
        runtime_label = QLabel("Runtime Summary:")
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
