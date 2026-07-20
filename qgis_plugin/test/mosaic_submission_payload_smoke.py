#!/usr/bin/env python3
"""Smoke checks for Mosaic submission payload defaults and re-task append behavior."""

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


class _FakeSourceService:
    def __init__(self):
        self.calls = []

    def create_tasking_order(self, payload):
        self.calls.append(dict(payload or {}))
        return {
            "order": {
                "id": "COLL-999",
                "status": "queued",
            }
        }


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    try:
        from image_mate_qgis_plugin.services.mosaic_contracts import ATTEMPT_STATUS_SKIPPED, ATTEMPT_STATUS_SUBMITTED  # noqa: PLC0415
        from image_mate_qgis_plugin.services.mosaic_tasking_service import MosaicTaskingService  # noqa: PLC0415
        from image_mate_qgis_plugin.services.mosaic_tracking_store import MosaicTrackingStore  # noqa: PLC0415
    except Exception as exc:
        print(f"mosaic_submission_payload_smoke: skipped ({exc})")
        return 0

    temp_root = Path(tempfile.mkdtemp(prefix="image_mate_mosaic_submit_"))
    try:
        db_path = temp_root / "mosaic.sqlite3"
        store = MosaicTrackingStore(db_path)
        store.initialize()
        store.create_project_with_tiles(
            project_id="proj_submit",
            campaign_uid="camp_submit",
            source_id="satellogic",
            aoi_source="map_extent",
            aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            estimated_price_usd=8.0,
            shapefile_path=str(temp_root / "tiles.shp"),
            tile_rows=[
                {
                    "tile_id": "tile_a",
                    "geometry_wkt": "POLYGON((0 0,1 0,1 1,0 1,0 0))",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                    },
                    "clipped_area_km2": 1.0,
                }
            ],
            mutation_source="create",
        )

        service = MosaicTaskingService()
        tile_row = store.load_tile(project_id="proj_submit", tile_id="tile_a")
        tile_row["geometry"] = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        }

        skipped = service.submit_single_tile(
            store=store,
            source_service=_FakeSourceService(),
            project_id="proj_submit",
            tile_id="tile_a",
            tile_row=tile_row,
            contract_id="contract-a",
            source_id="merlin-s2",
            sku="TSKPOI-M",
            mutation_source="create",
        )
        _assert_equal(skipped.get("attempt_status"), ATTEMPT_STATUS_SKIPPED, "non_satellogic_skip")

        fake_source = _FakeSourceService()
        submitted = service.submit_single_tile(
            store=store,
            source_service=fake_source,
            project_id="proj_submit",
            tile_id="tile_a",
            tile_row=tile_row,
            contract_id="contract-a",
            source_id="satellogic",
            sku="TSKPOI-M",
            mutation_source="retask",
        )
        _assert_equal(submitted.get("attempt_status"), ATTEMPT_STATUS_SUBMITTED, "satellogic_submit")
        _assert_true(bool(submitted.get("collection_id")), "collection_id_set")

        payload = fake_source.calls[-1]
        _assert_equal(str(payload.get("target_type") or ""), "point", "target_type")
        _assert_equal(str(payload.get("sku") or ""), "TSKPOI-M", "sku_default")
        geometry = payload.get("geometry") if isinstance(payload, dict) else {}
        _assert_equal(str((geometry or {}).get("type") or ""), "Point", "geometry_type")
        coords = (geometry or {}).get("coordinates")
        _assert_true(isinstance(coords, list) and len(coords) >= 2, "geometry_coordinates")
        _assert_true(str(payload.get("order_name") or "").startswith("mosaic-proj_submit-tile_a-a"), "order_name")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print("mosaic_submission_payload_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
