#!/usr/bin/env python3
"""Static smoke checks for Mosaic Tracking 'More' button wiring."""

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

    _assert_contains(main_dock_text, "mosaic_more_requested = pyqtSignal(dict)", "dock_signal")
    _assert_contains(main_dock_text, "QTableWidget(0, 12)", "tracking_table_column_count")
    _assert_contains(main_dock_text, '"Refresh",', "tracking_table_refresh_header")
    _assert_contains(main_dock_text, '"More",', "tracking_table_more_header")
    _assert_contains(main_dock_text, 'more_btn = QPushButton("More")', "row_more_button")
    _assert_contains(main_dock_text, "self._emit_mosaic_more_for_tile(tile_key)", "row_more_click_wiring")
    _assert_contains(main_dock_text, "table.setCellWidget(idx, 11, more_btn)", "row_more_column")
    _assert_contains(main_dock_text, "def show_mosaic_collection_api_detail_popup", "dock_popup_method")

    _assert_contains(
        plugin_text,
        "self.dock.mosaic_more_requested.connect(self.handle_mosaic_more_request)",
        "plugin_signal_connection",
    )
    _assert_contains(plugin_text, "def handle_mosaic_more_request", "plugin_handler")
    _assert_contains(plugin_text, "self.source_service.get_tasking_order", "handler_api_fetch")
    _assert_contains(plugin_text, "show_mosaic_collection_api_detail_popup", "handler_popup_call")

    print("mosaic_tracking_more_wiring_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
