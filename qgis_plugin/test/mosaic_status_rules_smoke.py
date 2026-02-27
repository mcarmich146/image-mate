#!/usr/bin/env python3
"""Smoke checks for Mosaic status rule behavior."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile


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

    from image_mate_qgis_plugin.services.mosaic_contracts import QA_STATUS_ACCEPTED, QA_STATUS_NOT_ACCEPTED  # noqa: PLC0415
    from image_mate_qgis_plugin.services.mosaic_tracking_store import MosaicTrackingStore  # noqa: PLC0415

    temp_root = Path(tempfile.mkdtemp(prefix="image_mate_mosaic_status_"))
    try:
        db_path = temp_root / "mosaic.sqlite3"
        store = MosaicTrackingStore(db_path)
        store.initialize()
        store.create_project_with_tiles(
            project_id="proj_status",
            campaign_uid="camp_status",
            source_id="satellogic",
            aoi_source="map_extent",
            aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            estimated_price_usd=8.0,
            shapefile_path=str(temp_root / "tiles.shp"),
            tile_rows=[
                {
                    "tile_id": "tile_a",
                    "geometry_wkt": "POLYGON((0 0,1 0,1 1,0 1,0 0))",
                    "clipped_area_km2": 1.0,
                }
            ],
            mutation_source="create",
        )

        tile = store.load_tile(project_id="proj_status", tile_id="tile_a")
        _assert_equal(str(tile.get("qa_status") or ""), QA_STATUS_NOT_ACCEPTED, "initial_qa_status")

        # API completed does not imply accepted.
        store.update_tile_api_status(
            project_id="proj_status",
            tile_id="tile_a",
            api_status="Completed",
            mutation_source="refresh_status",
            note="api_refresh",
        )
        tile_after_api = store.load_tile(project_id="proj_status", tile_id="tile_a")
        _assert_equal(str(tile_after_api.get("qa_status") or ""), QA_STATUS_NOT_ACCEPTED, "completed_not_accepted")

        changed = store.mark_tile_accepted(project_id="proj_status", tile_id="tile_a", accepted_by="qa_user")
        _assert_true(changed, "accepted_changed")
        tile_after_accept = store.load_tile(project_id="proj_status", tile_id="tile_a")
        _assert_equal(str(tile_after_accept.get("qa_status") or ""), QA_STATUS_ACCEPTED, "accepted_status")

        open_tiles = store.non_accepted_tiles("proj_status")
        _assert_equal(len(open_tiles), 0, "accepted_excluded_from_non_accepted")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print("mosaic_status_rules_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
