#!/usr/bin/env python3
"""Static smoke checks for Explore download-selected UI and rendering enhancements."""

from __future__ import annotations

from pathlib import Path


def _assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing snippet {needle!r}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    main_dock_path = repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "ui" / "main_dock.py"
    plugin_path = repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "plugin.py"

    main_dock_text = main_dock_path.read_text(encoding="utf-8")
    plugin_text = plugin_path.read_text(encoding="utf-8")

    _assert_contains(main_dock_text, 'self.select_all_results_btn = QPushButton("Select All")', "select_all_button")
    _assert_contains(main_dock_text, "self.select_all_results_btn.clicked.connect(self._select_all_search_results)", "select_all_wiring")
    _assert_contains(main_dock_text, "def _select_all_search_results(self):", "select_all_method")
    _assert_contains(main_dock_text, "item.setCheckState(Qt.Checked)", "select_all_checks_items")

    _assert_contains(plugin_text, "display_timestamp", "group_display_timestamp")
    _assert_contains(plugin_text, "band_order_text", "group_band_order_text")
    _assert_contains(plugin_text, "def _download_group_layer_name", "layer_name_helper")
    _assert_contains(plugin_text, 'return f"{stamp} {outcome_id}"', "layer_name_format")
    _assert_contains(plugin_text, "def _rgb_band_map_from_band_order_text", "band_map_helper")
    _assert_contains(plugin_text, 'if token == "rgb":', "rgb_token_expansion")
    _assert_contains(plugin_text, "self._apply_download_layer_rendering(layer=layer, band_order_text=band_order_text)", "rendering_apply_call")
    _assert_contains(plugin_text, "QgsCubicRasterResampler", "cubic_resampler")
    _assert_contains(plugin_text, "setMaxOversampling(float(5.0))", "oversampling_5")

    print("explore_download_selected_enhancements_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
