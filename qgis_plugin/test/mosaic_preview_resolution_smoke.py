#!/usr/bin/env python3
"""Smoke checks for Mosaic tracking preview resolution helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_true(condition: bool, label: str) -> None:
    if not bool(condition):
        raise AssertionError(label)


def _assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected={expected!r} actual={actual!r}")


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.mosaic_preview_resolution import (  # noqa: PLC0415
        extract_order_geometry,
        preview_collection_candidates,
        preview_item_id_candidates,
        preview_search_window,
        should_enable_preview,
    )

    detail = {
        "order": {
            "id": "ORD-123",
            "status": "Completed",
            "geometry": {"type": "Point", "coordinates": [-58.4, -34.6]},
            "start": "2026-02-10T10:00:00Z",
            "end": "2026-02-11T10:00:00Z",
            "parameters": {
                "collection_id": "quickview_visual_thumb",
            },
        },
        "raw": {
            "deliveries": [
                {
                    "scene": {"id": "SCENE-001"},
                    "result_item_id": "ITEM-RAW-1",
                }
            ],
            "collections": ["l1d_sr"],
        },
    }

    _assert_true(
        should_enable_preview(api_status="Completed", latest_collection_id="ORD-123"),
        "preview_enabled_completed",
    )
    _assert_true(
        not should_enable_preview(api_status="Queued", latest_collection_id="ORD-123"),
        "preview_disabled_not_completed",
    )
    _assert_true(
        not should_enable_preview(api_status="Completed", latest_collection_id=""),
        "preview_disabled_missing_collection_id",
    )

    candidates = preview_item_id_candidates(detail)
    _assert_true("SCENE-001" in candidates, "scene_id_candidate")
    _assert_true("ITEM-RAW-1" in candidates, "raw_item_id_candidate")

    collections = preview_collection_candidates(detail)
    _assert_equal(collections[0], "l1d-sr", "first_collection_from_raw")
    _assert_true("quickview-visual-thumb" in collections, "quickview_collection_hint")

    start_date, end_date = preview_search_window(detail)
    _assert_equal(start_date, "2026-02-09T22:00:00Z", "search_window_start")
    _assert_equal(end_date, "2026-02-18T10:00:00Z", "search_window_end")

    geom = extract_order_geometry(detail)
    _assert_equal(geom.get("type"), "Point", "geometry_type")

    fallback_start, fallback_end = preview_search_window({}, now_utc=datetime(2026, 2, 26, 0, 0, 0, tzinfo=timezone.utc))
    _assert_equal(fallback_start, "2026-01-27T00:00:00Z", "fallback_start")
    _assert_equal(fallback_end, "2026-02-27T00:00:00Z", "fallback_end")

    print("mosaic_preview_resolution_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
