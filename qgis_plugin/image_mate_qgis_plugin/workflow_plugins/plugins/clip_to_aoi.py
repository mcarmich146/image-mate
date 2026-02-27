"""Clip-to-AOI workflow function plugin.

Double-click behavior:
1. Open one modal dialog for full plugin configuration.
2. Let user pick AOI from either:
 - existing project layer, or
 - AOI file path from filesystem.
 - current map canvas extent.
3. Let user set an optional output label (path is campaign-managed).
4. Save only when user presses OK; keep unchanged on Cancel.
"""

from pathlib import Path

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from qgis.core import QgsProject

from ..types import WorkflowFunctionSpec


class ClipToAoiConfigDialog(QDialog):
    def __init__(self, *, parent=None, initial_payload=None, dock=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Clip to AOI")
        self._initial_payload = dict(initial_payload or {})
        self._dock = dock
        self._grouping_type = (
            str(
                self._initial_payload.get("__workflow_grouping_type")
                or self._initial_payload.get("grouping_type")
                or "single"
            )
            .strip()
            .lower()
            or "single"
        )
        self._allow_project_layers_input = bool(self._initial_payload.get("allow_project_layers_input", True))

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.aoi_source_combo = QComboBox()
        if self._allow_project_layers_input:
            self.aoi_source_combo.addItem("Project Layer", "project_layer")
        self.aoi_source_combo.addItem("AOI File", "file")
        self.aoi_source_combo.addItem("Clip To Canvas", "canvas")
        self.aoi_source_combo.currentIndexChanged.connect(self._on_source_mode_changed)

        self.aoi_project_layer_combo = QComboBox()
        self.aoi_project_layer_combo.setMinimumWidth(0)
        self._refresh_project_layers()

        aoi_file_row = QHBoxLayout()
        self.aoi_file_edit = QLineEdit()
        self.aoi_file_edit.setPlaceholderText("Select AOI file...")
        self.aoi_file_edit.setMinimumWidth(0)
        self.aoi_file_browse_btn = QPushButton("Browse...")
        self.aoi_file_browse_btn.clicked.connect(self._browse_aoi_file)
        aoi_file_row.addWidget(self.aoi_file_edit, 1)
        aoi_file_row.addWidget(self.aoi_file_browse_btn)

        self.output_name_hint_edit = QLineEdit()
        self.output_name_hint_edit.setPlaceholderText("Optional output label (auto if blank)")
        self.output_name_hint_edit.setMinimumWidth(0)

        form.addRow("AOI Source Type", self.aoi_source_combo)
        form.addRow("Project Layer", self.aoi_project_layer_combo)
        form.addRow("AOI File", aoi_file_row)
        form.addRow("Output Label", self.output_name_hint_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_initial_values()
        self._on_source_mode_changed()

    def _refresh_project_layers(self):
        prior = str(self.aoi_project_layer_combo.currentData() or "").strip()
        self.aoi_project_layer_combo.blockSignals(True)
        self.aoi_project_layer_combo.clear()
        self.aoi_project_layer_combo.addItem("Select a project layer", "")
        for layer in QgsProject.instance().mapLayers().values():
            layer_id = str(layer.id() or "").strip()
            if not layer_id:
                continue
            layer_name = str(layer.name() or layer_id).strip()
            self.aoi_project_layer_combo.addItem(f"{layer_name} ({layer_id})", layer_id)
        if prior:
            idx = self.aoi_project_layer_combo.findData(prior)
            if idx >= 0:
                self.aoi_project_layer_combo.setCurrentIndex(idx)
        self.aoi_project_layer_combo.blockSignals(False)

    def _load_initial_values(self):
        source_type = str(self._initial_payload.get("aoi_source_type") or "").strip().lower()
        if source_type not in {"project_layer", "file", "canvas"}:
            if self._initial_payload.get("aoi_project_layer_id"):
                source_type = "project_layer"
            elif self._initial_payload.get("aoi_path"):
                source_type = "file"
            else:
                source_type = "project_layer" if self._allow_project_layers_input else "file"

        source_idx = self.aoi_source_combo.findData(source_type)
        if source_idx >= 0:
            self.aoi_source_combo.setCurrentIndex(source_idx)

        aoi_file = str(self._initial_payload.get("aoi_path") or "").strip()
        if aoi_file:
            self.aoi_file_edit.setText(aoi_file)

        output_hint = str(
            self._initial_payload.get("output_name_hint")
            or self._initial_payload.get("output_file_name")
            or ""
        ).strip()
        if output_hint:
            self.output_name_hint_edit.setText(output_hint)

        layer_id = str(self._initial_payload.get("aoi_project_layer_id") or "").strip()
        if layer_id:
            idx = self.aoi_project_layer_combo.findData(layer_id)
            if idx >= 0:
                self.aoi_project_layer_combo.setCurrentIndex(idx)

    def _on_source_mode_changed(self):
        source_type = str(self.aoi_source_combo.currentData() or "file").strip().lower()
        use_project_layer = source_type == "project_layer"
        use_file = source_type == "file"
        self.aoi_project_layer_combo.setEnabled(use_project_layer)
        self.aoi_file_edit.setEnabled(use_file)
        self.aoi_file_browse_btn.setEnabled(use_file)

    def _browse_aoi_file(self):
        current = str(self.aoi_file_edit.text() or "").strip()
        start_dir = str(Path(current).parent) if current else ""
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select AOI File",
            start_dir,
            "AOI files (*.geojson *.json *.gpkg *.shp *.kml);;All files (*.*)",
        )
        selected_path = str(selected_path or "").strip()
        if selected_path:
            self.aoi_file_edit.setText(selected_path)

    def _on_accept(self):
        source_type = str(self.aoi_source_combo.currentData() or "file").strip().lower()
        if source_type == "project_layer":
            layer_id = str(self.aoi_project_layer_combo.currentData() or "").strip()
            if not layer_id:
                QMessageBox.warning(self, "Clip to AOI", "Select a project layer for AOI input.")
                return
        elif source_type == "file":
            aoi_file = str(self.aoi_file_edit.text() or "").strip()
            if not aoi_file:
                QMessageBox.warning(self, "Clip to AOI", "Select an AOI file.")
                return
        self.accept()

    def config_payload(self):
        updated = dict(self._initial_payload or {})
        updated.pop("__workflow_grouping_type", None)
        source_type = str(self.aoi_source_combo.currentData() or "file").strip().lower()
        output_hint = str(self.output_name_hint_edit.text() or "").strip()

        updated["aoi_source_type"] = source_type
        updated["allow_project_layers_input"] = self._allow_project_layers_input
        updated["output_path"] = ""
        updated["output_file_name"] = ""
        updated["output_name_hint"] = output_hint

        if source_type == "project_layer":
            layer_id = str(self.aoi_project_layer_combo.currentData() or "").strip()
            layer_label = str(self.aoi_project_layer_combo.currentText() or "").strip()
            layer_name = layer_label.split(" (")[0] if layer_label else layer_id
            updated["aoi_project_layer_id"] = layer_id
            updated["aoi_project_layer_name"] = layer_name
            updated["aoi_path"] = ""
            updated["aoi_file_name"] = ""
        elif source_type == "file":
            aoi_file = str(self.aoi_file_edit.text() or "").strip()
            updated["aoi_path"] = aoi_file
            updated["aoi_file_name"] = Path(aoi_file).name if aoi_file else ""
            updated["aoi_project_layer_id"] = ""
            updated["aoi_project_layer_name"] = ""
        else:
            # Clip-to-canvas mode derives AOI from current map canvas extent at execution time.
            updated["aoi_path"] = ""
            updated["aoi_file_name"] = ""
            updated["aoi_project_layer_id"] = ""
            updated["aoi_project_layer_name"] = ""
        return updated


def _on_node_double_click(*, dock, node_payload, function_spec):
    dialog = ClipToAoiConfigDialog(
        parent=dock,
        initial_payload=node_payload,
        dock=dock,
    )
    if dialog.exec_() != QDialog.Accepted:
        return None
    return dialog.config_payload()


def get_function_spec():
    return WorkflowFunctionSpec(
        function_id="clip_to_aoi",
        display_name="Clip to AOI",
        description=(
            "Clip source imagery to AOI. "
            "Double-click node to configure AOI source (project layer, file, or canvas extent). "
            "Output path is managed automatically."
        ),
        default_payload={
            "aoi_source_type": "project_layer",
            "aoi_project_layer_id": "",
            "aoi_project_layer_name": "",
            "aoi_path": "",
            "aoi_file_name": "",
            "output_path": "",
            "output_file_name": "",
            "output_name_hint": "",
            "allow_project_layers_input": True,
        },
        on_node_double_click=_on_node_double_click,
    )
