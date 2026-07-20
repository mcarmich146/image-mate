#!/usr/bin/env python3
"""Static smoke checks for Explore minimum coverage filter wiring."""

from __future__ import annotations

from pathlib import Path


def _assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing snippet {needle!r}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    main_dock_path = repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "ui" / "main_dock.py"
    search_controller_path = (
        repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "controllers" / "search_controller.py"
    )
    plugin_path = repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "plugin.py"
    streaming_path = repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "mixins" / "search_streaming.py"

    main_dock_text = main_dock_path.read_text(encoding="utf-8")
    search_controller_text = search_controller_path.read_text(encoding="utf-8")
    plugin_text = plugin_path.read_text(encoding="utf-8")
    streaming_text = streaming_path.read_text(encoding="utf-8")

    _assert_contains(main_dock_text, "self.min_coverage_filter_combo = QComboBox()", "coverage_combo_widget")
    _assert_contains(
        main_dock_text,
        'self.min_coverage_filter_combo.addItem("Touching (No Filter)", "touching")',
        "touching_option",
    )
    _assert_contains(main_dock_text, 'self.min_coverage_filter_combo.addItem("Half Coverage", "half")', "half_option")
    _assert_contains(main_dock_text, 'self.min_coverage_filter_combo.addItem("Full Coverage", "full")', "full_option")
    _assert_contains(main_dock_text, 'form.addRow("Min. Converage Filter", self.min_coverage_filter_combo)', "coverage_label")
    _assert_contains(main_dock_text, 'if coverage_mode not in {"touching", "full", "half"}:', "payload_coverage_mode_guard")
    _assert_contains(main_dock_text, '"min_coverage_filter": coverage_mode', "payload_coverage_mode")
    _assert_contains(
        main_dock_text,
        '"require_full_aoi_overlap": coverage_mode == "full"',
        "payload_legacy_bool",
    )

    _assert_contains(search_controller_text, 'payload.get("min_coverage_filter")', "request_coverage_mode_in")
    _assert_contains(
        search_controller_text,
        'if min_coverage_filter not in {"touching", "full", "half"}:',
        "request_coverage_mode_guard",
    )
    _assert_contains(search_controller_text, '"min_coverage_filter": min_coverage_filter', "request_coverage_mode_out")
    _assert_contains(
        search_controller_text,
        '"require_full_aoi_overlap": min_coverage_filter == "full"',
        "request_legacy_bool",
    )

    _assert_contains(plugin_text, 'coverage_mode = str(request_payload.get("min_coverage_filter")', "search_mode_read")
    _assert_contains(plugin_text, 'if coverage_mode not in {"touching", "full", "half"}:', "search_mode_guard")
    _assert_contains(
        plugin_text,
        'min_overlap_ratio = 1.0 if coverage_mode == "full" else (0.5 if coverage_mode == "half" else None)',
        "search_mode_threshold",
    )
    _assert_contains(plugin_text, "def _filter_items_min_aoi_overlap", "coverage_filter_helper")
    _assert_contains(plugin_text, "if overlap_ratio + 1e-9 >= threshold:", "coverage_threshold_check")

    _assert_contains(streaming_text, 'hasattr(self.dock, "min_coverage_filter_combo")', "source_change_combo_path")
    _assert_contains(
        streaming_text,
        "Touching disables overlap threshold; Half Coverage keeps at least 50% AOI overlap.",
        "source_change_tooltip",
    )
    _assert_contains(
        streaming_text,
        "Coverage filter auto-adjusted to Half Coverage for Sentinel-2.",
        "source_change_auto_adjust",
    )

    print("explore_min_converage_filter_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
