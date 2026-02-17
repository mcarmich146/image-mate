# -*- coding: utf-8 -*-
"""Main dock widget for Image Mate."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtCore import QDate
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
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
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ImageMateMainDock(QDockWidget):
    validate_requested = pyqtSignal()
    settings_requested = pyqtSignal()
    search_requested = pyqtSignal(dict)
    result_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Image Mate", parent)
        self.setObjectName("imageMateMainDock")

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QLabel("Image Mate")
        header.setTextInteractionFlags(Qt.TextSelectableByMouse)
        header.setStyleSheet("font-weight: 600; font-size: 14px;")
        subtitle = QLabel("Phase 1 implementation baseline")
        subtitle.setTextInteractionFlags(Qt.TextSelectableByMouse)

        tabs = QTabWidget()
        tabs.addTab(self._build_explore_tab(), "Explore")
        tabs.addTab(self._placeholder_tab("Tasking UI pending."), "Tasking")
        tabs.addTab(self._placeholder_tab("Monitoring UI pending."), "Monitoring")
        tabs.addTab(self._placeholder_tab("Workflows/Runs UI pending."), "Workflows")

        self.runtime_summary = QLabel("Runtime summary unavailable.")
        self.runtime_summary.setWordWrap(True)
        self.runtime_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stream_status = QLabel("Stream status: idle")
        self.stream_status.setWordWrap(True)
        self.stream_status.setTextInteractionFlags(Qt.TextSelectableByMouse)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.settings_requested.emit)
        settings_btn.setToolTip("Configure provider settings and auth config IDs.")

        health_btn = QPushButton("Validate Setup")
        health_btn.clicked.connect(self.validate_requested.emit)
        health_btn.setToolTip("Validate plugin setup and auth wiring.")

        layout.addWidget(header)
        layout.addWidget(subtitle)
        layout.addWidget(tabs, 1)
        layout.addWidget(self.stream_status)
        layout.addWidget(self.runtime_summary)
        layout.addWidget(settings_btn)
        layout.addWidget(health_btn)

        self.setWidget(root)

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

    def set_search_enabled(self, enabled):
        self.search_btn.setEnabled(bool(enabled))

    def set_contract_id(self, contract_id):
        self.contract_id.setText(str(contract_id or "").strip())

    def set_contract_enabled(self, enabled):
        self.contract_id.setEnabled(bool(enabled))

    def set_results(self, items):
        self.results_list.blockSignals(True)
        self.results_list.clear()
        for row in items or []:
            item_id = str(row.get("id") or "").strip()
            source_id = str(row.get("source_id") or "").strip()
            dt = str(row.get("datetime") or "").strip()
            cloud = row.get("cloud_cover")
            gsd = row.get("gsd")
            label = (
                f"{dt or 'unknown time'} | {source_id or 'unknown source'} | "
                f"cloud={cloud if cloud is not None else '--'} | gsd={gsd if gsd is not None else '--'} | {item_id}"
            )
            q_item = QListWidgetItem(label)
            q_item.setData(Qt.UserRole, item_id)
            self.results_list.addItem(q_item)
        self.results_list.blockSignals(False)

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
        self.search_requested.emit(self.current_search_payload())

    def _emit_result_selected(self):
        item = self.results_list.currentItem()
        if item is None:
            return
        item_id = str(item.data(Qt.UserRole) or "").strip()
        if item_id:
            self.result_selected.emit(item_id)

    def _build_explore_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        form = QFormLayout()
        self.source_combo = QComboBox()
        self.collection_combo = QComboBox()
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.max_cloud = QSpinBox()
        self.max_cloud.setRange(0, 100)
        self.max_cloud.setValue(40)
        self.min_gsd = QDoubleSpinBox()
        self.min_gsd.setRange(0.0, 1000.0)
        self.min_gsd.setDecimals(2)
        self.min_gsd.setSingleStep(0.1)
        self.min_gsd.setSpecialValueText("none")
        self.min_gsd.setValue(0.0)
        self.max_gsd = QDoubleSpinBox()
        self.max_gsd.setRange(0.0, 1000.0)
        self.max_gsd.setDecimals(2)
        self.max_gsd.setSingleStep(0.1)
        self.max_gsd.setSpecialValueText("none")
        self.max_gsd.setValue(0.0)
        self.limit = QSpinBox()
        self.limit.setRange(1, 1000)
        self.limit.setValue(250)
        self.contract_id = QLineEdit()
        self.contract_id.setPlaceholderText("optional (defaults to .env / client setting)")
        self.satellite_name = QLineEdit()
        self.satellite_name.setPlaceholderText("optional")

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
        self.remove_existing_layers = QCheckBox("Remote Existing Layers")
        self.remove_existing_layers.setChecked(True)
        self.remove_existing_layers.setToolTip("Remove existing layers with names starting with 'Image Mate'.")
        btn_row.addWidget(self.remove_existing_layers)
        self.create_new_layer_on_selection = QCheckBox("Create New Layer Per Selection")
        self.create_new_layer_on_selection.setChecked(False)
        self.create_new_layer_on_selection.setToolTip(
            "When enabled, selecting a result adds a new imagery layer instead of replacing the previous one."
        )
        btn_row.addWidget(self.create_new_layer_on_selection)
        btn_row.addStretch(1)

        self.search_log = QTextEdit()
        self.search_log.setReadOnly(True)
        self.search_log.setPlaceholderText("Search output will appear here.")
        self.results_list = QListWidget()
        self.results_list.setSelectionMode(self.results_list.SingleSelection)
        self.results_list.currentItemChanged.connect(lambda _cur, _prev: self._emit_result_selected())
        self.results_list.setToolTip("Selecting a result triggers imagery loading.")

        layout.addLayout(form)
        layout.addLayout(btn_row)
        layout.addWidget(QLabel("Search log"))
        layout.addWidget(self.search_log, 1)
        layout.addWidget(QLabel("Results (selection loads imagery)"))
        layout.addWidget(self.results_list, 2)
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
