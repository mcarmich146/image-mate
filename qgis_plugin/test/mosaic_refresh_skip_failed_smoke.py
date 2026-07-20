#!/usr/bin/env python3
"""Smoke checks for Mosaic status refresh behavior (skip failed + single-tile refresh)."""

from __future__ import annotations

from pathlib import Path
import types
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


def _install_qgis_stubs() -> None:
    if "qgis" in sys.modules:
        return

    qgis_module = types.ModuleType("qgis")
    qgis_core_module = types.ModuleType("qgis.core")
    qgis_pyqt_module = types.ModuleType("qgis.PyQt")
    qgis_qtcore_module = types.ModuleType("qgis.PyQt.QtCore")

    class _Dummy:  # pragma: no cover - smoke-test helper
        def __init__(self, *args, **kwargs):
            pass

    class _QgsVectorFileWriter(_Dummy):  # pragma: no cover - smoke-test helper
        NoError = 0

    qgis_core_module.QgsCoordinateReferenceSystem = _Dummy
    qgis_core_module.QgsCoordinateTransform = _Dummy
    qgis_core_module.QgsFeature = _Dummy
    qgis_core_module.QgsField = _Dummy
    qgis_core_module.QgsGeometry = _Dummy
    qgis_core_module.QgsPointXY = _Dummy
    qgis_core_module.QgsProject = _Dummy
    qgis_core_module.QgsVectorFileWriter = _QgsVectorFileWriter
    qgis_core_module.QgsVectorLayer = _Dummy

    qgis_qtcore_module.QVariant = _Dummy

    qgis_module.core = qgis_core_module
    qgis_module.PyQt = qgis_pyqt_module
    qgis_pyqt_module.QtCore = qgis_qtcore_module

    sys.modules["qgis"] = qgis_module
    sys.modules["qgis.core"] = qgis_core_module
    sys.modules["qgis.PyQt"] = qgis_pyqt_module
    sys.modules["qgis.PyQt.QtCore"] = qgis_qtcore_module


class _FakeSourceService:
    def __init__(self):
        self.calls = []

    def get_tasking_order(self, collection_id, contract_id=None):
        self.calls.append({"collection_id": str(collection_id or ""), "contract_id": str(contract_id or "")})
        return {"order": {"id": str(collection_id or ""), "status": "Completed"}}


def _create_store(store, *, project_id: str, temp_root: Path) -> None:
    store.create_project_with_tiles(
        project_id=project_id,
        campaign_uid="camp_refresh",
        source_id="satellogic",
        aoi_source="map_extent",
        aoi_geojson={"type": "Polygon", "coordinates": [[[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]]]},
        estimated_price_usd=24.0,
        shapefile_path=str(temp_root / "tiles.shp"),
        tile_rows=[
            {"tile_id": "tile_active", "geometry_wkt": "POLYGON((0 0,1 0,1 1,0 1,0 0))", "clipped_area_km2": 1.0},
            {"tile_id": "tile_failed", "geometry_wkt": "POLYGON((1 0,2 0,2 1,1 1,1 0))", "clipped_area_km2": 1.0},
            {"tile_id": "tile_canceled", "geometry_wkt": "POLYGON((1 1,2 1,2 2,1 2,1 1))", "clipped_area_km2": 1.0},
            {"tile_id": "tile_missing", "geometry_wkt": "POLYGON((2 0,3 0,3 1,2 1,2 0))", "clipped_area_km2": 1.0},
        ],
        mutation_source="create",
    )

    store.append_attempt(
        project_id=project_id,
        tile_id="tile_active",
        attempt_no=1,
        collection_id="COLL-OK",
        attempt_status="submitted",
        api_status="Queued",
        request_payload={},
        response_payload={},
        error_text="",
        mutation_source="create",
    )
    store.append_attempt(
        project_id=project_id,
        tile_id="tile_failed",
        attempt_no=1,
        collection_id="COLL-FAIL",
        attempt_status="submitted",
        api_status="Failed",
        request_payload={},
        response_payload={},
        error_text="",
        mutation_source="create",
    )
    store.append_attempt(
        project_id=project_id,
        tile_id="tile_canceled",
        attempt_no=1,
        collection_id="COLL-CANCEL",
        attempt_status="submitted",
        api_status="canceled",
        request_payload={},
        response_payload={},
        error_text="",
        mutation_source="cancel_tasking",
    )


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    _install_qgis_stubs()
    try:
        from image_mate_qgis_plugin.services.mosaic_tasking_service import MosaicTaskingService  # noqa: PLC0415
        from image_mate_qgis_plugin.services.mosaic_tracking_store import MosaicTrackingStore  # noqa: PLC0415
    except Exception as exc:
        print(f"mosaic_refresh_skip_failed_smoke: skipped ({exc})")
        return 0

    temp_root = Path(tempfile.mkdtemp(prefix="image_mate_mosaic_refresh_"))
    try:
        db_path = temp_root / "mosaic.sqlite3"
        store = MosaicTrackingStore(db_path)
        store.initialize()
        _create_store(store, project_id="proj_refresh", temp_root=temp_root)

        service = MosaicTaskingService()
        fake_source = _FakeSourceService()

        updates = service.refresh_non_accepted_statuses(
            store=store,
            source_service=fake_source,
            project_id="proj_refresh",
            contract_id="contract-a",
            source_id="satellogic",
            skip_failed=True,
        )
        calls = [str(row.get("collection_id") or "") for row in fake_source.calls]
        _assert_equal(calls, ["COLL-OK"], "bulk_refresh_calls_non_terminal_only")

        failed_rows = [row for row in updates if str(row.get("tile_id") or "") == "tile_failed"]
        _assert_equal(len(failed_rows), 1, "failed_row_present")
        failed_row = failed_rows[0]
        _assert_true(bool(failed_row.get("skipped")), "failed_row_skipped")
        _assert_equal(str(failed_row.get("reason") or ""), "terminal_failed", "failed_skip_reason")

        canceled_rows = [row for row in updates if str(row.get("tile_id") or "") == "tile_canceled"]
        _assert_equal(len(canceled_rows), 1, "canceled_row_present")
        canceled_row = canceled_rows[0]
        _assert_true(bool(canceled_row.get("skipped")), "canceled_row_skipped")
        _assert_equal(str(canceled_row.get("reason") or ""), "terminal_canceled", "canceled_skip_reason")

        active_tile = store.load_tile(project_id="proj_refresh", tile_id="tile_active")
        _assert_equal(str(active_tile.get("api_status") or ""), "Completed", "active_tile_refreshed")

        fake_source.calls.clear()
        single_updates = service.refresh_non_accepted_statuses(
            store=store,
            source_service=fake_source,
            project_id="proj_refresh",
            contract_id="contract-a",
            source_id="satellogic",
            tile_ids=["tile_failed"],
            skip_failed=True,
        )
        _assert_equal(len(fake_source.calls), 0, "single_failed_refresh_no_api_call")
        _assert_equal(len(single_updates), 1, "single_failed_refresh_one_update")
        _assert_equal(str(single_updates[0].get("reason") or ""), "terminal_failed", "single_failed_skip_reason")

        fake_source.calls.clear()
        single_canceled_updates = service.refresh_non_accepted_statuses(
            store=store,
            source_service=fake_source,
            project_id="proj_refresh",
            contract_id="contract-a",
            source_id="satellogic",
            tile_ids=["tile_canceled"],
            skip_failed=True,
        )
        _assert_equal(len(fake_source.calls), 0, "single_canceled_refresh_no_api_call")
        _assert_equal(len(single_canceled_updates), 1, "single_canceled_refresh_one_update")
        _assert_equal(
            str(single_canceled_updates[0].get("reason") or ""),
            "terminal_canceled",
            "single_canceled_skip_reason",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    print("mosaic_refresh_skip_failed_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
