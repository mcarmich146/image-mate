#!/usr/bin/env python3
"""Static contract checks for Mosaicking Studio QGIS wiring."""

from __future__ import annotations

import ast
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
    _require(
        dock_text,
        'dialog.run_requested.connect(self.mosaicking_studio_requested.emit)',
        "persistent request emission",
    )
    _require(dock_text, "dialog.show()", "modeless studio opening")
    _require(dock_text, "dialog.destroyed.connect(", "modeless studio cleanup")
    dock_tree = ast.parse(dock_text)
    studio_open = next(
        node
        for node in ast.walk(dock_tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_open_mosaicking_studio"
    )
    studio_open_calls = {
        node.func.attr
        for node in ast.walk(studio_open)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    if "exec_" in studio_open_calls:
        raise AssertionError("Mosaicking Studio must not disable the main dock with a modal event loop")
    _require(dialog_text, 'class MosaickingStudioDialog(QDialog):', "persistent studio")
    _require(dialog_text, 'self.tabs = QTabWidget(self)', "tab container")
    for tab_label in (
        '"1. Inputs"',
        '"2. Output"',
        '"3. Review"',
        '"4. Processing Results"',
    ):
        _require(dialog_text, tab_label, "studio step tab")
    _require(dialog_text, '"layer_ids": self.input_tab.selected_layer_ids()', "layer selection")
    _require(dialog_text, '"output_path": self.output_tab.output_path.text().strip()', "output selection")
    _require(dialog_text, 'run_requested = pyqtSignal(dict)', "non-closing finish signal")
    _require(dialog_text, 'self.tabs.setCurrentIndex(self.RESULTS_TAB)', "results transition")
    _require(dialog_text, 'self.progress_bar = QProgressBar(self)', "progress bar")
    _require(dialog_text, 'self.log = QPlainTextEdit(self)', "processing log")
    _require(dialog_text, 'processing_log_received = pyqtSignal(str)', "queued log bridge")
    _require(dialog_text, 'processing_progress_received = pyqtSignal(float)', "queued progress bridge")
    _require(dialog_text, 'QCheckBox("Include debug information"', "debug information option")
    _require(dialog_text, '"include_debug_information":', "debug request payload")
    _require(dialog_text, 'if self._processing:', "close guard")

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
    _require(plugin_text, "progress_callback=task.setProgress", "engine progress bridge")
    _require(plugin_text, "debug_callback=_emit_studio_debug", "debug lifecycle bridge")
    _require(plugin_text, "studio_log_buffer = MosaickingLogBuffer()", "thread-safe log bridge")
    _require(plugin_text, "studio_log_buffer.drain(studio_log_signal.emit)", "GUI-thread log drain")
    _require(plugin_text, "timer.stop()", "terminal log timer stop")
    _require(plugin_text, "timer.deleteLater()", "terminal log timer disposal")
    _require(plugin_text, "task.progressChanged.connect(studio.processing_progress_received.emit)", "UI progress bridge")
    _require(plugin_text, "task.statusChanged.connect(", "task status diagnostics")
    _require(plugin_text, "task.taskTerminated.connect(", "termination fallback")
    _require(plugin_text, "_report_unhandled_termination", "termination exception report")
    _require(plugin_text, "Could not submit the mosaic task", "submission failure handling")
    _require(plugin_text, "studio.finish_processing(", "terminal status")
    _require(plugin_text, "self._resolve_local_raster_source_path(layer)", "local path resolution")
    _require(plugin_text, "self._add_layer_to_image_mate_group(mosaic_layer)", "project layer load")

    print("mosaicking_studio_wiring_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
