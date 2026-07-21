#!/usr/bin/env python3
"""Static smoke checks for Mosaic Tracking preview candidate fan-out path."""

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
    plugin = (repo_root / "qgis_plugin" / "image_mate_qgis_plugin" / "plugin.py").read_text(encoding="utf-8")

    _assert_contains(
        plugin,
        "def _resolve_mosaic_tracking_preview_items(",
        "resolve_plural_entrypoint",
    )
    _assert_contains(
        plugin,
        "def _mosaic_preview_item_from_deliverable(",
        "deliverable_to_preview_item_helper",
    )
    _assert_contains(
        plugin,
        "list_tasking_order_deliverables(",
        "deliverables_fetch",
    )
    _assert_contains(
        plugin,
        "for item_id in preview_item_id_candidates(detail):",
        "candidate_iteration",
    )
    _assert_contains(
        plugin,
        "resolved_items.append(resolved)",
        "candidate_item_append",
    )
    _assert_ordered(
        plugin,
        "list_tasking_order_deliverables(",
        "for item_id in preview_item_id_candidates(detail):",
        "deliverables_before_item_id_guessing",
    )
    _assert_ordered(
        plugin,
        "resolved_items.append(resolved)",
        "geometry = extract_order_geometry(detail)",
        "candidate_path_returns_full_list",
    )
    _assert_contains(
        plugin,
        "items = self._resolve_mosaic_tracking_preview_items(",
        "toggle_uses_plural_resolution",
    )
    _assert_contains(
        plugin,
        "for item in items:",
        "toggle_renders_every_resolved_item",
    )
    _assert_contains(
        plugin,
        "if isinstance(layer_value, list):",
        "clear_supports_multiple_layers_per_tile",
    )
    _assert_contains(
        plugin,
        "preview_map[tile_key] = layer_ids",
        "map_tracks_multiple_layer_ids_per_tile",
    )

    print("mosaic_tracking_preview_all_candidates_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
