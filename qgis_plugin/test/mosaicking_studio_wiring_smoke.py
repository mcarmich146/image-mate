#!/usr/bin/env python3
"""Static contract checks for Mosaicking Studio QGIS wiring."""

from __future__ import annotations

from pathlib import Path


def _require(text: str, token: str, label: str) -> None:
    if token not in text:
        raise AssertionError(f"{label}: missing {token!r}")


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    package_root = plugin_root / "image_mate_qgis_plugin"
    dock_text = (package_root / "ui" / "main_dock.py").read_text(encoding="utf-8")
    dialog_text = (package_root / "ui" / "mosaicking_studio_dialog.py").read_text(encoding="utf-8")
    plugin_text = (package_root / "plugin.py").read_text(encoding="utf-8")

    _require(dock_text, 'mosaicking_studio_requested = pyqtSignal(dict)', "dock signal")
    _require(dock_text, 'QPushButton("Mosaicking Studio")', "geoprocessing action")
    _require(dock_text, 'self.mosaicking_studio_requested.emit(', "request emission")
    _require(dialog_text, 'class MosaickingStudioDialog(QWizard):', "guided studio")
    _require(dialog_text, '"layer_ids": self.input_page.selected_layer_ids()', "layer selection")
    _require(dialog_text, '"output_path": self.output_page.output_path.text().strip()', "output selection")

    for deferred_token in ("cloud_threshold", "cloud_mask", "cutline_editor", "feather_spin"):
        if deferred_token in dialog_text:
            raise AssertionError(f"deferred control leaked into MVP dialog: {deferred_token}")

    _require(
        plugin_text,
        "self.dock.mosaicking_studio_requested.connect(self.handle_mosaicking_studio_request)",
        "handler connection",
    )
    _require(plugin_text, "QgsTask.fromFunction(", "background task")
    _require(plugin_text, "QgsApplication.taskManager().addTask(task)", "task submission")
    _require(plugin_text, "self._resolve_local_raster_source_path(layer)", "local path resolution")
    _require(plugin_text, "self._add_layer_to_image_mate_group(mosaic_layer)", "project layer load")

    print("mosaicking_studio_wiring_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
