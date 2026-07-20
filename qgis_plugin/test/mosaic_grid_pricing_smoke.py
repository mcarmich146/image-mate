#!/usr/bin/env python3
"""Smoke checks for Mosaic AOI tiling and clipped-area pricing."""

from __future__ import annotations

from pathlib import Path
import math
import sys


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_true(condition: bool, label: str) -> None:
    if not bool(condition):
        raise AssertionError(label)


def _assert_close(actual: float, expected: float, eps: float, label: str) -> None:
    if abs(float(actual) - float(expected)) > float(eps):
        raise AssertionError(f"{label}: expected~={expected!r} actual={actual!r} eps={eps!r}")


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    try:
        from image_mate_qgis_plugin.services.mosaic_grid_service import MosaicGridService  # noqa: PLC0415
    except Exception as exc:
        print(f"mosaic_grid_pricing_smoke: skipped ({exc})")
        return 0

    service = MosaicGridService()

    # Small AOI near equator; should clip to one or more 3km cells and price by clipped area.
    aoi_geojson = {
        "type": "Polygon",
        "coordinates": [
            [
                [0.0, 0.0],
                [0.04, 0.0],
                [0.04, 0.04],
                [0.0, 0.04],
                [0.0, 0.0],
            ]
        ],
    }

    breakdown = service.build_breakdown(aoi_geojson)
    tiles = breakdown.get("tiles") if isinstance(breakdown, dict) else []
    _assert_true(isinstance(tiles, list) and len(tiles) > 0, "tile_rows_non_empty")

    total_area = float(breakdown.get("total_area_km2") or 0.0)
    estimated_price = float(breakdown.get("estimated_price_usd") or 0.0)
    _assert_true(total_area > 0.0, "total_area_positive")
    _assert_true(estimated_price > 0.0, "price_positive")

    recomputed_area = 0.0
    for row in tiles:
        area = float((row or {}).get("clipped_area_km2") or 0.0)
        _assert_true(area > 0.0, "tile_area_positive")
        _assert_true(area <= 9.0 + 1e-6, "tile_area_not_full_tile_cap")
        recomputed_area += area

    _assert_close(recomputed_area, total_area, 1e-5, "sum_matches_total")
    _assert_close(estimated_price, total_area * 8.0, 1e-4, "price_from_clipped_area")
    _assert_true(not math.isnan(estimated_price), "price_not_nan")

    print("mosaic_grid_pricing_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
