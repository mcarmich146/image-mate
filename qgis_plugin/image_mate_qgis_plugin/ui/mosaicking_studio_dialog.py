# -*- coding: utf-8 -*-
"""Guided MVP dialog for selecting project rasters and a mosaic output."""

from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)


class _InputLayersPage(QWizardPage):
    def __init__(self, layer_options, parent=None):
        super().__init__(parent)
        self.setTitle("Choose project layers")
        self.setSubTitle("Select at least two local raster layers to mosaic.")
        layout = QVBoxLayout(self)

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
        self.layer_list.itemChanged.connect(lambda _item: self.completeChanged.emit())
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

    def isComplete(self):
        return len(self.selected_layer_ids()) >= 2

    def validatePage(self):
        if self.isComplete():
            return True
        QMessageBox.warning(self, "Mosaicking Studio", "Select at least two raster layers.")
        return False


class _OutputPage(QWizardPage):
    def __init__(self, default_output_path="", parent=None):
        super().__init__(parent)
        self.setTitle("Choose mosaic output")
        self.setSubTitle("Save the generated mosaic as a local GeoTIFF.")
        layout = QVBoxLayout(self)

        path_row = QHBoxLayout()
        self.output_path = QLineEdit(self)
        self.output_path.setText(str(default_output_path or "").strip())
        self.output_path.setPlaceholderText("Choose a .tif or .tiff output file")
        self.output_path.textChanged.connect(lambda _text: self.completeChanged.emit())
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.output_path, 1)
        path_row.addWidget(browse)
        layout.addLayout(path_row)

        self.overwrite = QCheckBox("Replace the output if it already exists", self)
        self.overwrite.stateChanged.connect(lambda _state: self.completeChanged.emit())
        layout.addWidget(self.overwrite)

        note = QLabel(
            "This first integration uses the current Mosaicker_v2 defaults for "
            "radiometric balancing, automatic cloud scoring, seam planning, and feathering."
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

    def isComplete(self):
        text = self.output_path.text().strip()
        if not text or Path(text).suffix.lower() not in {".tif", ".tiff"}:
            return False
        return not Path(text).exists() or self.overwrite.isChecked()

    def validatePage(self):
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


class _ReviewPage(QWizardPage):
    def __init__(self, studio, parent=None):
        super().__init__(parent)
        self._studio = studio
        self.setTitle("Review and create")
        self.setSubTitle("Finish to start mosaic generation in the QGIS task manager.")
        layout = QVBoxLayout(self)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.summary)
        layout.addStretch(1)

    def initializePage(self):
        payload = self._studio.request_payload()
        layer_count = len(payload.get("layer_ids") or [])
        output_path = str(payload.get("output_path") or "")
        overwrite = "yes" if payload.get("overwrite") else "no"
        self.summary.setText(
            f"Input layers: {layer_count}\n"
            f"Output: {output_path}\n"
            f"Replace existing output: {overwrite}\n\n"
            "Advanced cutline, feather, and cloud controls will be added in a later iteration."
        )


class MosaickingStudioDialog(QWizard):
    """Collect the minimal input/output request for the lifted Mosaicker_v2 engine."""

    def __init__(self, *, layer_options, default_output_path="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mosaicking Studio")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.resize(780, 520)

        self.input_page = _InputLayersPage(layer_options, self)
        self.output_page = _OutputPage(default_output_path, self)
        self.review_page = _ReviewPage(self, self)
        self.addPage(self.input_page)
        self.addPage(self.output_page)
        self.addPage(self.review_page)

    def request_payload(self):
        return {
            "layer_ids": self.input_page.selected_layer_ids(),
            "output_path": self.output_page.output_path.text().strip(),
            "overwrite": self.output_page.overwrite.isChecked(),
        }
