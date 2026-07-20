#!/usr/bin/env python3
"""Static smoke checks for Mosaic Tracking refresh wiring (bulk + per-row)."""

from __future__ import annotations

from pathlib import Path


def _assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing snippet {needle!r}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    main_dock_path = repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "ui" / "main_dock.py"
    plugin_path = repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "plugin.py"
    service_path = repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "services" / "mosaic_tasking_service.py"

    main_dock_text = main_dock_path.read_text(encoding="utf-8")
    plugin_text = plugin_path.read_text(encoding="utf-8")
    service_text = service_path.read_text(encoding="utf-8")

    _assert_contains(main_dock_text, "QTableWidget(0, 12)", "tracking_table_column_count")
    _assert_contains(main_dock_text, '"Refresh",', "tracking_table_refresh_header")
    _assert_contains(main_dock_text, 'refresh_btn = QPushButton("Refresh")', "row_refresh_button")
    _assert_contains(main_dock_text, "self._emit_mosaic_refresh_status_for_tile(tile_key)", "row_refresh_click_wiring")
    _assert_contains(main_dock_text, "table.setCellWidget(idx, 7, refresh_btn)", "row_refresh_column")
    _assert_contains(main_dock_text, "normalized_api_status", "row_refresh_status_normalization")
    _assert_contains(main_dock_text, '{"failed", "canceled", "cancelled"}', "row_refresh_terminal_statuses")
    _assert_contains(main_dock_text, "def _emit_mosaic_refresh_status_for_tile", "row_refresh_method")
    _assert_contains(
        main_dock_text,
        'self.mosaic_refresh_status_requested.emit({"project_id": project_id, "tile_id": tile_key})',
        "row_refresh_payload",
    )

    _assert_contains(plugin_text, 'tile_id = str(request.get("tile_id") or "").strip()', "plugin_tile_payload")
    _assert_contains(plugin_text, "tile_ids=[tile_id] if tile_id else None", "plugin_single_tile_forwarding")

    _assert_contains(service_text, "tile_ids: list[str] | None = None", "service_tile_ids_signature")
    _assert_contains(service_text, "skip_failed: bool = True", "service_skip_failed_signature")
    _assert_contains(service_text, '"reason": "terminal_failed"', "service_terminal_failed_skip")
    _assert_contains(service_text, '"reason": "terminal_canceled"', "service_terminal_canceled_skip")
    _assert_contains(service_text, "def _is_terminal_failed_status", "service_failed_helper")
    _assert_contains(service_text, "def _is_terminal_canceled_status", "service_canceled_helper")

    print("mosaic_tracking_refresh_wiring_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
