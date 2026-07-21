# -*- coding: utf-8 -*-
"""Persistent tabbed studio for configuring and monitoring a raster mosaic."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import QDateTime, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class _InputLayersTab(QWidget):
    def __init__(self, layer_options, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        heading = QLabel("Choose project layers")
        heading.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(heading)
        description = QLabel("Select at least two local raster layers to mosaic.")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.layer_list = QListWidget(self)
        self.layer_list.setMinimumSize(680, 300)
        for row in layer_options or []:
            layer_id = str(row.get("id") or "").strip()
            if not layer_id:
                continue
            name = str(row.get("name") or layer_id).strip()
            provider = str(row.get("provider") or "unknown").strip()
            item = QListWidgetItem(f"{name} [{provider}]", self.layer_list)
            item.setData(Qt.UserRole, layer_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
        layout.addWidget(self.layer_list, 1)

        button_row = QHBoxLayout()
        select_all = QPushButton("Select All", self)
        clear_all = QPushButton("Clear All", self)
        select_all.clicked.connect(lambda: self._set_all(Qt.Checked))
        clear_all.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        button_row.addWidget(select_all)
        button_row.addWidget(clear_all)
        button_row.addStretch(1)
        layout.addLayout(button_row)

    def _set_all(self, state):
        for index in range(self.layer_list.count()):
            self.layer_list.item(index).setCheckState(state)

    def selected_layer_ids(self):
        selected = []
        for index in range(self.layer_list.count()):
            item = self.layer_list.item(index)
            if item.checkState() != Qt.Checked:
                continue
            layer_id = str(item.data(Qt.UserRole) or "").strip()
            if layer_id:
                selected.append(layer_id)
        return selected

    def validate(self):
        if len(self.selected_layer_ids()) >= 2:
            return True
        QMessageBox.warning(self, "Mosaicking Studio", "Select at least two raster layers.")
        return False


class _OutputTab(QWidget):
    def __init__(self, default_output_path="", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        heading = QLabel("Choose mosaic output")
        heading.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(heading)
        description = QLabel("Save the generated mosaic as a local GeoTIFF.")
        description.setWordWrap(True)
        layout.addWidget(description)

        path_row = QHBoxLayout()
        self.output_path = QLineEdit(self)
        self.output_path.setText(str(default_output_path or "").strip())
        self.output_path.setPlaceholderText("Choose a .tif or .tiff output file")
        browse = QPushButton("Browse...", self)
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.output_path, 1)
        path_row.addWidget(browse)
        layout.addLayout(path_row)

        self.overwrite = QCheckBox("Replace the output if it already exists", self)
        layout.addWidget(self.overwrite)

        self.include_debug_information = QCheckBox("Include debug information", self)
        self.include_debug_information.setToolTip(
            "Show detailed task, dependency-loading, engine, and output-verification messages."
        )
        layout.addWidget(self.include_debug_information)

        note = QLabel(
            "This integration uses the current Mosaicker_v2 defaults for radiometric "
            "balancing, automatic cloud scoring, seam planning, and feathering."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    def _browse(self):
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Save Mosaic",
            self.output_path.text().strip(),
            "GeoTIFF (*.tif *.tiff)",
        )
        if selected:
            path = Path(selected)
            if path.suffix.lower() not in {".tif", ".tiff"}:
                path = path.with_suffix(".tif")
            self.output_path.setText(str(path))

    def validate(self):
        text = self.output_path.text().strip()
        if not text:
            QMessageBox.warning(self, "Mosaicking Studio", "Choose an output GeoTIFF path.")
            return False
        if Path(text).suffix.lower() not in {".tif", ".tiff"}:
            QMessageBox.warning(self, "Mosaicking Studio", "Output must end in .tif or .tiff.")
            return False
        if Path(text).exists() and not self.overwrite.isChecked():
            QMessageBox.warning(
                self,
                "Mosaicking Studio",
                "The output already exists. Choose another path or enable replacement.",
            )
            return False
        return True


class _ReviewTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        heading = QLabel("Review and create")
        heading.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(heading)
        description = QLabel("Click Finish to start mosaic generation.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.summary)
        layout.addStretch(1)

    def update_summary(self, payload):
        layer_count = len(payload.get("layer_ids") or [])
        output_path = str(payload.get("output_path") or "")
        overwrite = "yes" if payload.get("overwrite") else "no"
        self.summary.setText(
            f"Input layers: {layer_count}\n"
            f"Output: {output_path}\n"
            f"Replace existing output: {overwrite}\n\n"
            "Advanced cutline, feather, and cloud controls will be added later."
        )


class _ProcessingResultsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        heading = QLabel("Processing Results")
        heading.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(heading)
        self.status_label = QLabel("Waiting to start.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)
        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Mosaicker progress and status messages will appear here.")
        layout.addWidget(self.log, 1)


class MosaickingStudioDialog(QDialog):
    """One-window, tabbed workflow that remains visible through processing."""

    run_requested = pyqtSignal(dict)
    processing_log_received = pyqtSignal(str)
    processing_progress_received = pyqtSignal(float)

    INPUTS_TAB = 0
    OUTPUT_TAB = 1
    REVIEW_TAB = 2
    RESULTS_TAB = 3

    def __init__(self, *, layer_options, default_output_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mosaicking Studio")
        self.resize(820, 600)
        self._processing = False
        self._terminal = False

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        self.input_tab = _InputLayersTab(layer_options, self)
        self.output_tab = _OutputTab(default_output_path, self)
        self.review_tab = _ReviewTab(self)
        self.results_tab = _ProcessingResultsTab(self)
        self.tabs.addTab(self.input_tab, "1. Inputs")
        self.tabs.addTab(self.output_tab, "2. Output")
        self.tabs.addTab(self.review_tab, "3. Review")
        self.tabs.addTab(self.results_tab, "4. Processing Results")
        self.tabs.setTabEnabled(self.OUTPUT_TAB, False)
        self.tabs.setTabEnabled(self.REVIEW_TAB, False)
        self.tabs.setTabEnabled(self.RESULTS_TAB, False)
        self.tabs.currentChanged.connect(self._sync_navigation)
        layout.addWidget(self.tabs, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.back_button = QPushButton("Back", self)
        self.next_button = QPushButton("Next", self)
        self.finish_button = QPushButton("Finish", self)
        self.close_button = QPushButton("Close", self)
        self.back_button.clicked.connect(self._go_back)
        self.next_button.clicked.connect(self._go_next)
        self.finish_button.clicked.connect(self._start_processing)
        self.close_button.clicked.connect(self.reject)
        button_row.addWidget(self.back_button)
        button_row.addWidget(self.next_button)
        button_row.addWidget(self.finish_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.processing_log_received.connect(self.append_processing_log)
        self.processing_progress_received.connect(self.set_processing_progress)
        self._sync_navigation()

    def request_payload(self):
        return {
            "layer_ids": self.input_tab.selected_layer_ids(),
            "output_path": self.output_tab.output_path.text().strip(),
            "overwrite": self.output_tab.overwrite.isChecked(),
            "include_debug_information": self.output_tab.include_debug_information.isChecked(),
        }

    def _go_next(self):
        current = self.tabs.currentIndex()
        if current == self.INPUTS_TAB:
            if not self.input_tab.validate():
                return
            self.tabs.setTabEnabled(self.OUTPUT_TAB, True)
            self.tabs.setCurrentIndex(self.OUTPUT_TAB)
        elif current == self.OUTPUT_TAB:
            if not self.output_tab.validate():
                return
            self.review_tab.update_summary(self.request_payload())
            self.tabs.setTabEnabled(self.REVIEW_TAB, True)
            self.tabs.setCurrentIndex(self.REVIEW_TAB)

    def _go_back(self):
        current = self.tabs.currentIndex()
        if current == self.OUTPUT_TAB:
            self.tabs.setCurrentIndex(self.INPUTS_TAB)
        elif current == self.REVIEW_TAB:
            self.tabs.setCurrentIndex(self.OUTPUT_TAB)

    def _start_processing(self):
        if self._processing:
            return
        if not self.input_tab.validate() or not self.output_tab.validate():
            return
        payload = self.request_payload()
        self.review_tab.update_summary(payload)
        self._processing = True
        self._terminal = False
        self.tabs.setTabEnabled(self.INPUTS_TAB, False)
        self.tabs.setTabEnabled(self.OUTPUT_TAB, False)
        self.tabs.setTabEnabled(self.REVIEW_TAB, False)
        self.tabs.setTabEnabled(self.RESULTS_TAB, True)
        self.tabs.setCurrentIndex(self.RESULTS_TAB)
        self.results_tab.log.clear()
        self.results_tab.status_label.setText("Starting mosaic generation...")
        self.results_tab.progress_bar.setValue(0)
        self.append_processing_log("Request prepared for QGIS task submission.")
        if payload["include_debug_information"]:
            self.append_processing_log("DEBUG: Detailed lifecycle logging is enabled.")
        self._sync_navigation()
        payload["_studio"] = self
        self.run_requested.emit(payload)

    def _sync_navigation(self, _index=None):
        current = self.tabs.currentIndex()
        editable = not self._processing and not self._terminal
        self.back_button.setEnabled(editable and current in {self.OUTPUT_TAB, self.REVIEW_TAB})
        self.next_button.setEnabled(editable and current in {self.INPUTS_TAB, self.OUTPUT_TAB})
        self.finish_button.setEnabled(editable and current == self.REVIEW_TAB)
        self.close_button.setEnabled(not self._processing)

    def set_processing_progress(self, value):
        progress = min(100, max(0, int(round(float(value)))))
        if progress < self.results_tab.progress_bar.value():
            return
        self.results_tab.progress_bar.setValue(progress)
        if self._processing:
            self.results_tab.status_label.setText(f"Mosaic generation in progress: {progress}%")

    def append_processing_log(self, message):
        text = str(message or "").strip()
        if not text:
            return
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self.results_tab.log.appendPlainText(f"[{timestamp}] {text}")
        scrollbar = self.results_tab.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def finish_processing(self, *, success, message):
        self._processing = False
        self._terminal = True
        if success:
            self.results_tab.progress_bar.setValue(100)
            self.results_tab.status_label.setText("Mosaic completed successfully.")
        else:
            self.results_tab.status_label.setText("Mosaic generation failed.")
        self.append_processing_log(message)
        self.tabs.setTabEnabled(self.RESULTS_TAB, True)
        self.tabs.setCurrentIndex(self.RESULTS_TAB)
        self._sync_navigation()

    def reject(self):
        if self._processing:
            self.results_tab.status_label.setText(
                "Mosaic generation is still running. Keep this window open until it finishes."
            )
            self.append_processing_log("Close request ignored while processing is active.")
            return
        super().reject()

    def closeEvent(self, event):
        if self._processing:
            event.ignore()
            self.reject()
            return
        super().closeEvent(event)
