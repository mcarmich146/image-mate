#!/usr/bin/env python3
"""Smoke checks for Mosaic SQLite tracking store behavior."""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3
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

    from image_mate_qgis_plugin.services.mosaic_tracking_store import MosaicTrackingStore  # noqa: PLC0415

    temp_root = Path(tempfile.mkdtemp(prefix="image_mate_mosaic_store_"))
    try:
        db_path = temp_root / "mosaic.sqlite3"
        store = MosaicTrackingStore(db_path)
        store.initialize()

        tiles = [
            {
                "tile_id": "tile_1",
                "geometry_wkt": "POLYGON((0 0,1 0,1 1,0 1,0 0))",
                "clipped_area_km2": 12.5,
            },
            {
                "tile_id": "tile_2",
                "geometry_wkt": "POLYGON((1 1,2 1,2 2,1 2,1 1))",
                "clipped_area_km2": 8.0,
            },
        ]
        store.create_project_with_tiles(
            project_id="proj_a",
            campaign_uid="camp_a",
            source_id="satellogic",
            aoi_source="map_extent",
            aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]},
            estimated_price_usd=164.0,
            shapefile_path=str(temp_root / "tiles.shp"),
            tile_rows=tiles,
            mutation_source="create",
        )

        loaded_tiles = store.load_tiles("proj_a")
        _assert_equal(len(loaded_tiles), 2, "tile_count")

        attempt_no = store.next_attempt_no(project_id="proj_a", tile_id="tile_1")
        _assert_equal(attempt_no, 1, "attempt_no_1")
        store.append_attempt(
            project_id="proj_a",
            tile_id="tile_1",
            attempt_no=attempt_no,
            collection_id="COLL-123",
            attempt_status="submitted",
            api_status="queued",
            request_payload={"a": 1},
            response_payload={"b": 2},
            error_text="",
            mutation_source="create",
        )

        tile_1 = store.load_tile(project_id="proj_a", tile_id="tile_1")
        _assert_equal(int(tile_1.get("attempt_count") or 0), 1, "tile_1_attempt_count")
        _assert_equal(str(tile_1.get("latest_collection_id") or ""), "COLL-123", "tile_1_collection")

        # Failure injection path: append attempt for missing tile should fail and not orphan rows.
        failed = False
        try:
            store.append_attempt(
                project_id="proj_a",
                tile_id="tile_missing",
                attempt_no=1,
                collection_id=None,
                attempt_status="failed",
                api_status="submission_failed",
                request_payload={},
                response_payload={},
                error_text="missing",
                mutation_source="create",
            )
        except Exception:
            failed = True
        _assert_true(failed, "append attempt should fail for missing tile")

        with sqlite3.connect(str(db_path)) as conn:
            orphan_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM mosaic_attempt a
                LEFT JOIN mosaic_tile t
                  ON t.project_id = a.project_id AND t.tile_id = a.tile_id
                WHERE t.tile_id IS NULL
                """
            ).fetchone()[0]
        _assert_equal(int(orphan_count or 0), 0, "orphan_attempt_rows")

        changed = store.mark_tile_accepted(project_id="proj_a", tile_id="tile_1", accepted_by="tester")
        _assert_true(changed, "mark_accepted_changed")
        changed_again = store.mark_tile_accepted(project_id="proj_a", tile_id="tile_1", accepted_by="tester")
        _assert_true(not changed_again, "mark_accepted_idempotent")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print("mosaic_tracking_store_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
