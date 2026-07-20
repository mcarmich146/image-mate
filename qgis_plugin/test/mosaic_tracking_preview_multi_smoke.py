#!/usr/bin/env python3
"""Static smoke checks for Mosaic Tracking multi-preview behavior."""

from __future__ import annotations

from pathlib import Path


def _assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing snippet {needle!r}")


def _assert_ordered(text: str, first: str, second: str, label: str) -> None:
    idx_first = text.find(first)
    idx_second = text.find(second)
    if idx_first < 0 or idx_second < 0 or idx_first >= idx_second:
        raise AssertionError(f"{label}: expected {first!r} before {second!r}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    main_dock = (repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "ui" / "main_dock.py").read_text(
        encoding="utf-8"
    )
    plugin = (repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "plugin.py").read_text(encoding="utf-8")
    streaming = (
        repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "mixins" / "search_streaming.py"
    ).read_text(encoding="utf-8")

    _assert_contains(main_dock, "_mosaic_tracking_preview_tile_ids = set()", "ui_preview_set_state")
    _assert_contains(main_dock, "def set_mosaic_tracking_preview_tiles(", "ui_preview_setter")
    _assert_contains(main_dock, "self._mosaic_tracking_preview_tile_ids.add(tile_key)", "ui_preview_add")
    _assert_contains(main_dock, "self._mosaic_tracking_preview_tile_ids.discard(tile_key)", "ui_preview_remove")

    _assert_contains(plugin, "_mosaic_tracking_preview_layer_ids = {}", "plugin_preview_map_state")
    _assert_contains(plugin, "def _clear_mosaic_tracking_preview_layer_for_tile(", "plugin_clear_tile_preview")
    _assert_contains(
        plugin,
        "self._clear_mosaic_tracking_preview_layer_for_tile(tile_id=tile_id)",
        "plugin_toggle_clears_only_target_tile",
    )
    _assert_contains(plugin, "image_mate/mosaic_tracking_tile_id", "plugin_preview_layer_tile_property")
    _assert_ordered(
        plugin,
        "layer = self._build_stream_layer_for_item(item, prefer_telluric=True)",
        "if layer is None:\n            try:\n                layer = self._load_item_imagery_layer(item)",
        "plugin_telluric_first_then_asset_fallback",
    )
    _assert_ordered(
        plugin,
        "if layer is None:\n            try:\n                layer = self._load_item_imagery_layer(item)",
        "if layer is None:\n            try:\n                layer = self._build_stream_layer_for_item(item)",
        "plugin_asset_then_generic_stream_fallback",
    )

    _assert_contains(
        streaming,
        'if key in {"preview", "thumbnail"} and not self._layer_has_georeference(layer):',
        "streaming_preview_georef_guard_download",
    )
    _assert_contains(streaming, "preview asset has no georeference", "streaming_preview_georef_error")

    print("mosaic_tracking_preview_multi_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
