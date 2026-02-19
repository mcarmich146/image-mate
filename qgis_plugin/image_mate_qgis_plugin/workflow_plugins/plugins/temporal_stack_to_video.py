"""Temporal Stack to Video workflow plugin.

Double-click behavior:
1. Open one modal dialog for full plugin configuration.
2. Configure output video location/name.
3. Configure text overlay template and placement.
4. Configure temporal pause between frames when collection date changes.
5. Choose clipping mode: canvas extent or AOI.
6. If AOI clipping is selected, choose AOI source (project layer or file).
7. Select optional project vector layers to overlay on every frame.

Plugin callback API notes:
- Function id: `temporal_stack_to_video`
- Expected payload keys:
  - `output_path`: output video path
  - `text_template`: overlay text, supports `{collection_date, 'yyyy-mm-dd'}`
  - `text_vertical_align`: `top` or `bottom`
  - `text_horizontal_align`: `left`, `center`, or `right`
  - `pause_between_dates_seconds`: float >= 0
  - `frames_per_second`: int > 0
  - `clip_mode`: `canvas` or `aoi`
  - `aoi_source_type`: `project_layer` or `file` (used when `clip_mode=aoi`)
  - `aoi_project_layer_id`: optional AOI project layer id
  - `aoi_path`: optional AOI file path
  - `overlay_vector_layer_id`: optional project vector layer id
  - `overlay_shapefile_layer_id`: optional project shapefile layer id
"""

from pathlib import Path

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from qgis.core import QgsProject
from qgis.core import QgsVectorLayer

from ..types import WorkflowFunctionSpec


class TemporalStackToVideoConfigDialog(QDialog):
    def __init__(self, *, parent=None, initial_payload=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Temporal Stack to Video")
        self._initial_payload = dict(initial_payload or {})
        self._allow_project_layers_input = bool(self._initial_payload.get("allow_project_layers_input", True))

        layout = QVBoxLayout(self)
        form = QFormLayout()

        output_row = QHBoxLayout()
        self.output_file_edit = QLineEdit()
        self.output_file_edit.setPlaceholderText("Select output video file...")
        self.output_file_edit.setMinimumWidth(0)
        self.output_file_browse_btn = QPushButton("Browse...")
        self.output_file_browse_btn.clicked.connect(self._browse_output_file)
        output_row.addWidget(self.output_file_edit, 1)
        output_row.addWidget(self.output_file_browse_btn)

        self.text_template_edit = QLineEdit()
        self.text_template_edit.setMinimumWidth(0)
        self.text_template_edit.setPlaceholderText(
            "Example: Collected {collection_date, 'yyyy-mm-dd'}"
        )

        self.text_vertical_combo = QComboBox()
        self.text_vertical_combo.addItem("Top", "top")
        self.text_vertical_combo.addItem("Bottom", "bottom")

        self.text_horizontal_combo = QComboBox()
        self.text_horizontal_combo.addItem("Left", "left")
        self.text_horizontal_combo.addItem("Center", "center")
        self.text_horizontal_combo.addItem("Right", "right")

        self.pause_seconds_spin = QDoubleSpinBox()
        self.pause_seconds_spin.setRange(0.0, 120.0)
        self.pause_seconds_spin.setDecimals(2)
        self.pause_seconds_spin.setSingleStep(0.25)

        self.frames_per_second_spin = QSpinBox()
        self.frames_per_second_spin.setRange(1, 60)

        self.clip_mode_combo = QComboBox()
        self.clip_mode_combo.addItem("Clip to Canvas", "canvas")
        self.clip_mode_combo.addItem("Clip to AOI", "aoi")
        self.clip_mode_combo.currentIndexChanged.connect(self._on_clip_mode_changed)

        self.aoi_source_combo = QComboBox()
        if self._allow_project_layers_input:
            self.aoi_source_combo.addItem("Project Layer", "project_layer")
        self.aoi_source_combo.addItem("AOI File", "file")
        self.aoi_source_combo.currentIndexChanged.connect(self._on_aoi_source_mode_changed)

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

        self.overlay_vector_combo = QComboBox()
        self.overlay_vector_combo.setMinimumWidth(0)
        self._populate_overlay_combo(self.overlay_vector_combo, shapefile_only=False)

        self.overlay_shapefile_combo = QComboBox()
        self.overlay_shapefile_combo.setMinimumWidth(0)
        self._populate_overlay_combo(self.overlay_shapefile_combo, shapefile_only=True)

        form.addRow("Output Video", output_row)
        form.addRow("Text Overlay", self.text_template_edit)
        form.addRow("Text Vertical", self.text_vertical_combo)
        form.addRow("Text Horizontal", self.text_horizontal_combo)
        form.addRow("Pause Between Dates (s)", self.pause_seconds_spin)
        form.addRow("Frames Per Second", self.frames_per_second_spin)
        form.addRow("Clip Mode", self.clip_mode_combo)
        form.addRow("AOI Source Type", self.aoi_source_combo)
        form.addRow("AOI Project Layer", self.aoi_project_layer_combo)
        form.addRow("AOI File", aoi_file_row)
        form.addRow("Overlay Vector (project)", self.overlay_vector_combo)
        form.addRow("Overlay Shapefile (project)", self.overlay_shapefile_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_initial_values()
        self._on_clip_mode_changed()

    def _vector_layers(self, *, shapefile_only=False):
        layers = []
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            if not layer.isValid():
                continue
            if shapefile_only:
                layer_source = str(layer.source() or "").strip()
                source_path = layer_source.split("|", 1)[0]
                if Path(source_path).suffix.lower() != ".shp":
                    continue
            layers.append(layer)
        return layers

    def _refresh_project_layers(self):
        prior = str(self.aoi_project_layer_combo.currentData() or "").strip()
        self.aoi_project_layer_combo.blockSignals(True)
        self.aoi_project_layer_combo.clear()
        self.aoi_project_layer_combo.addItem("Select a project layer", "")
        for layer in self._vector_layers(shapefile_only=False):
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

    def _populate_overlay_combo(self, combo, *, shapefile_only):
        prior_value = str(combo.currentData() or "").strip()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("None", "")
        for layer in self._vector_layers(shapefile_only=shapefile_only):
            layer_id = str(layer.id() or "").strip()
            if not layer_id:
                continue
            layer_name = str(layer.name() or layer_id).strip()
            combo.addItem(f"{layer_name} ({layer_id})", layer_id)
        if prior_value:
            idx = combo.findData(prior_value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _load_initial_values(self):
        output_path = str(self._initial_payload.get("output_path") or "").strip()
        if output_path:
            self.output_file_edit.setText(output_path)

        text_template = str(self._initial_payload.get("text_template") or "").strip()
        if text_template:
            self.text_template_edit.setText(text_template)

        vertical_align = str(self._initial_payload.get("text_vertical_align") or "top").strip().lower()
        vertical_idx = self.text_vertical_combo.findData(vertical_align)
        if vertical_idx >= 0:
            self.text_vertical_combo.setCurrentIndex(vertical_idx)

        horizontal_align = str(self._initial_payload.get("text_horizontal_align") or "left").strip().lower()
        horizontal_idx = self.text_horizontal_combo.findData(horizontal_align)
        if horizontal_idx >= 0:
            self.text_horizontal_combo.setCurrentIndex(horizontal_idx)

        pause_seconds = self._initial_payload.get("pause_between_dates_seconds")
        if pause_seconds is not None:
            try:
                self.pause_seconds_spin.setValue(max(0.0, float(pause_seconds)))
            except Exception:
                pass

        fps = self._initial_payload.get("frames_per_second")
        if fps is not None:
            try:
                self.frames_per_second_spin.setValue(max(1, int(fps)))
            except Exception:
                pass

        clip_mode = str(self._initial_payload.get("clip_mode") or "").strip().lower()
        if clip_mode not in {"canvas", "aoi"}:
            if self._initial_payload.get("aoi_project_layer_id") or self._initial_payload.get("aoi_path"):
                clip_mode = "aoi"
            else:
                clip_mode = "canvas"
        clip_mode_idx = self.clip_mode_combo.findData(clip_mode)
        if clip_mode_idx >= 0:
            self.clip_mode_combo.setCurrentIndex(clip_mode_idx)

        aoi_source_type = str(self._initial_payload.get("aoi_source_type") or "").strip().lower()
        if aoi_source_type not in {"project_layer", "file"}:
            if self._initial_payload.get("aoi_project_layer_id"):
                aoi_source_type = "project_layer"
            elif self._initial_payload.get("aoi_path"):
                aoi_source_type = "file"
            else:
                aoi_source_type = "project_layer" if self._allow_project_layers_input else "file"
        source_idx = self.aoi_source_combo.findData(aoi_source_type)
        if source_idx >= 0:
            self.aoi_source_combo.setCurrentIndex(source_idx)

        aoi_project_layer_id = str(self._initial_payload.get("aoi_project_layer_id") or "").strip()
        if aoi_project_layer_id:
            idx = self.aoi_project_layer_combo.findData(aoi_project_layer_id)
            if idx >= 0:
                self.aoi_project_layer_combo.setCurrentIndex(idx)

        aoi_file = str(self._initial_payload.get("aoi_path") or "").strip()
        if aoi_file:
            self.aoi_file_edit.setText(aoi_file)

        vector_layer_id = str(self._initial_payload.get("overlay_vector_layer_id") or "").strip()
        if vector_layer_id:
            idx = self.overlay_vector_combo.findData(vector_layer_id)
            if idx >= 0:
                self.overlay_vector_combo.setCurrentIndex(idx)

        shapefile_layer_id = str(self._initial_payload.get("overlay_shapefile_layer_id") or "").strip()
        if shapefile_layer_id:
            idx = self.overlay_shapefile_combo.findData(shapefile_layer_id)
            if idx >= 0:
                self.overlay_shapefile_combo.setCurrentIndex(idx)

    def _on_clip_mode_changed(self):
        self._update_clip_controls_state()

    def _on_aoi_source_mode_changed(self):
        self._update_clip_controls_state()

    def _update_clip_controls_state(self):
        clip_mode = str(self.clip_mode_combo.currentData() or "canvas").strip().lower()
        use_aoi = clip_mode == "aoi"

        self.aoi_source_combo.setEnabled(use_aoi)

        source_type = str(self.aoi_source_combo.currentData() or "file").strip().lower()
        use_project_layer = use_aoi and source_type == "project_layer"
        use_file = use_aoi and source_type != "project_layer"
        self.aoi_project_layer_combo.setEnabled(use_project_layer)
        self.aoi_file_edit.setEnabled(use_file)
        self.aoi_file_browse_btn.setEnabled(use_file)

    def _browse_output_file(self):
        current = str(self.output_file_edit.text() or "").strip()
        start_file = current or "temporal_stack_video.mp4"
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Video Output File",
            start_file,
            "MP4 video (*.mp4);;All files (*.*)",
        )
        selected_path = str(selected_path or "").strip()
        if selected_path:
            if not Path(selected_path).suffix:
                selected_path = f"{selected_path}.mp4"
            self.output_file_edit.setText(selected_path)

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
        output_file = str(self.output_file_edit.text() or "").strip()
        if not output_file:
            QMessageBox.warning(self, "Temporal Stack to Video", "Select output video file location and name.")
            return

        clip_mode = str(self.clip_mode_combo.currentData() or "canvas").strip().lower()
        if clip_mode == "aoi":
            source_type = str(self.aoi_source_combo.currentData() or "file").strip().lower()
            if source_type == "project_layer":
                layer_id = str(self.aoi_project_layer_combo.currentData() or "").strip()
                if not layer_id:
                    QMessageBox.warning(
                        self,
                        "Temporal Stack to Video",
                        "Select an AOI project layer or switch AOI source type to file.",
                    )
                    return
            else:
                aoi_file = str(self.aoi_file_edit.text() or "").strip()
                if not aoi_file:
                    QMessageBox.warning(
                        self,
                        "Temporal Stack to Video",
                        "Select an AOI file or switch AOI source type to project layer.",
                    )
                    return

        self.accept()

    def config_payload(self):
        updated = dict(self._initial_payload or {})

        output_file = str(self.output_file_edit.text() or "").strip()
        if output_file and not Path(output_file).suffix:
            output_file = f"{output_file}.mp4"
        updated["output_path"] = output_file
        updated["output_file_name"] = Path(output_file).name if output_file else ""

        updated["text_template"] = str(self.text_template_edit.text() or "").strip()
        updated["text_vertical_align"] = str(self.text_vertical_combo.currentData() or "top").strip().lower()
        updated["text_horizontal_align"] = str(
            self.text_horizontal_combo.currentData() or "left"
        ).strip().lower()
        updated["pause_between_dates_seconds"] = float(self.pause_seconds_spin.value())
        updated["frames_per_second"] = int(self.frames_per_second_spin.value())

        clip_mode = str(self.clip_mode_combo.currentData() or "canvas").strip().lower()
        updated["clip_mode"] = clip_mode
        updated["allow_project_layers_input"] = self._allow_project_layers_input

        source_type = str(self.aoi_source_combo.currentData() or "file").strip().lower()
        updated["aoi_source_type"] = source_type
        if source_type == "project_layer":
            layer_id = str(self.aoi_project_layer_combo.currentData() or "").strip()
            layer_label = str(self.aoi_project_layer_combo.currentText() or "").strip()
            layer_name = layer_label.split(" (")[0] if layer_label else layer_id
            updated["aoi_project_layer_id"] = layer_id
            updated["aoi_project_layer_name"] = layer_name
            updated["aoi_path"] = ""
            updated["aoi_file_name"] = ""
        else:
            aoi_file = str(self.aoi_file_edit.text() or "").strip()
            updated["aoi_path"] = aoi_file
            updated["aoi_file_name"] = Path(aoi_file).name if aoi_file else ""
            updated["aoi_project_layer_id"] = ""
            updated["aoi_project_layer_name"] = ""

        vector_layer_id = str(self.overlay_vector_combo.currentData() or "").strip()
        vector_layer_name = ""
        if vector_layer_id:
            layer = QgsProject.instance().mapLayer(vector_layer_id)
            if layer is not None:
                vector_layer_name = str(layer.name() or "").strip()
        updated["overlay_vector_layer_id"] = vector_layer_id
        updated["overlay_vector_layer_name"] = vector_layer_name

        shapefile_layer_id = str(self.overlay_shapefile_combo.currentData() or "").strip()
        shapefile_layer_name = ""
        if shapefile_layer_id:
            layer = QgsProject.instance().mapLayer(shapefile_layer_id)
            if layer is not None:
                shapefile_layer_name = str(layer.name() or "").strip()
        updated["overlay_shapefile_layer_id"] = shapefile_layer_id
        updated["overlay_shapefile_layer_name"] = shapefile_layer_name
        return updated


def _on_node_double_click(*, dock, node_payload, function_spec):
    dialog = TemporalStackToVideoConfigDialog(
        parent=dock,
        initial_payload=node_payload,
    )
    if dialog.exec_() != QDialog.Accepted:
        return None
    return dialog.config_payload()


def get_function_spec():
    return WorkflowFunctionSpec(
        function_id="temporal_stack_to_video",
        display_name="Temporal Stack to Video",
        description=(
            "Render temporal stack inputs into a video. "
            "Supports clipping (canvas or AOI), text/date overlay, temporal pause, and project vector overlays."
        ),
        default_payload={
            "output_path": "",
            "output_file_name": "",
            "text_template": "Collected {collection_date, 'yyyy-mm-dd'}",
            "text_vertical_align": "top",
            "text_horizontal_align": "left",
            "pause_between_dates_seconds": 0.0,
            "frames_per_second": 2,
            "clip_mode": "canvas",
            "aoi_source_type": "project_layer",
            "aoi_project_layer_id": "",
            "aoi_project_layer_name": "",
            "aoi_path": "",
            "aoi_file_name": "",
            "allow_project_layers_input": True,
            "clip_effective_mask_path": "",
            "clip_effective_mask_desc": "",
            "overlay_vector_layer_id": "",
            "overlay_vector_layer_name": "",
            "overlay_shapefile_layer_id": "",
            "overlay_shapefile_layer_name": "",
        },
        on_node_double_click=_on_node_double_click,
    )
