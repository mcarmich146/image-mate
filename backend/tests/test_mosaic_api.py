from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.mosaic_store import MosaicStore


def _box(west: float, south: float, east: float, north: float) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]],
    }


def _item(item_id: str, geometry: dict, *, generation: str = "mark-v", collection: str = "l1d-sr") -> dict:
    thumbnail = f"https://api.satellogic.com/assets/{item_id}/thumbnail.png"
    visual = f"https://api.satellogic.com/assets/{item_id}/visual.tif"
    return {
        "id": item_id,
        "source_id": "satellogic",
        "collection": collection,
        "datetime": "2026-08-16T00:00:00Z",
        "satellite_name": "SN48",
        "sensor_generation": generation,
        "sensor_generation_source": "test",
        "gsd": 0.5,
        "cloud_cover": 4,
        "geometry": copy.deepcopy(geometry),
        "assets": {"thumbnail": thumbnail, "preview": thumbnail, "visual": visual},
        "raw": {
            "id": item_id,
            "collection": collection,
            "properties": {},
            "assets": {
                "thumbnail": {"href": thumbnail, "type": "image/png"},
                "visual": {"href": visual, "type": "image/tiff"},
            },
        },
    }


def _quickview(item_id: str, geometry: dict, outcome_id: str) -> dict:
    item = _item(item_id, geometry, collection="quickview-visual-thumb")
    item["gsd"] = 20.0
    item["outcome_id"] = outcome_id
    item["raw"]["properties"] = {"satl:outcome_id": outcome_id}
    return item


class MosaicApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.api.close()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_store = main.app.state.mosaic_store
        self.previous_cache = main.app.state.item_cache
        self.previous_asset_cache = main.app.state.asset_cache
        self.previous_worker_processes = main.app.state.mosaic_worker_processes
        self.previous_output_dir = main.settings.output_dir
        main.app.state.mosaic_store = MosaicStore(Path(self.temp_dir.name) / "mosaic.sqlite3")
        main.app.state.item_cache = {}
        main.app.state.asset_cache = {}
        main.app.state.mosaic_worker_processes = {}
        main.settings.output_dir = Path(self.temp_dir.name) / "output"

    def tearDown(self):
        main.app.state.mosaic_store = self.previous_store
        main.app.state.item_cache = self.previous_cache
        main.app.state.asset_cache = self.previous_asset_cache
        main.app.state.mosaic_worker_processes = self.previous_worker_processes
        main.settings.output_dir = self.previous_output_dir
        self.temp_dir.cleanup()

    def _cache(self, *items: dict) -> None:
        main.app.state.item_cache.update({item["id"]: item for item in items})

    @staticmethod
    def _input(item_id: str, *, generation: str = "mark-v") -> dict:
        return {
            "item_id": item_id,
            "source_id": "satellogic",
            "collection_id": "l1d-sr",
            "asset_key": "visual",
            "sensor_generation": generation,
        }

    def test_preview_resolves_by_item_identity_and_returns_thumbnail(self):
        item = _item("scene-a", _box(0, 0, 2, 2))
        self._cache(item)
        with patch.object(main, "_validate_proxy_url", side_effect=lambda url: url) as validate, \
             patch.object(main, "_download_bytes_for_url", return_value=b"png-bytes") as download:
            response = self.api.get(
                "/api/archive/preview",
                params={"item_id": "scene-a", "asset_key": "thumbnail", "source_id": "satellogic"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, b"png-bytes")
        self.assertEqual(response.headers["content-type"], "image/png")
        validate.assert_called_once_with(item["raw"]["assets"]["thumbnail"]["href"])
        download.assert_called_once_with(
            item["raw"]["assets"]["thumbnail"]["href"],
            contract_id=None,
            source_hint="satellogic",
        )

    def test_preflight_accepts_one_connected_overlap_group(self):
        self._cache(
            _item("scene-a", _box(-122.401, 37.699, -122.399, 37.701)),
            _item("scene-b", _box(-122.400, 37.699, -122.398, 37.701)),
        )
        response = self.api.post(
            "/api/mosaics/preflight",
            json={"inputs": [self._input("scene-a"), self._input("scene-b")], "mode": "whole_strip"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["valid"])
        self.assertEqual(body["overlap_groups"], [[0, 1]])
        self.assertEqual(body["sensor_generations"], ["mark-v"])
        self.assertGreater(body["estimated_pixels"], 0)

    def test_preflight_rejects_disconnected_selection(self):
        self._cache(
            _item("scene-a", _box(0, 0, 1, 1)),
            _item("scene-b", _box(5, 5, 6, 6)),
        )
        response = self.api.post(
            "/api/mosaics/preflight",
            json={"inputs": [self._input("scene-a"), self._input("scene-b")], "mode": "whole_strip"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["valid"])
        self.assertTrue(any("disconnected" in message.lower() for message in body["messages"]))

    def test_preflight_rejects_requested_sensor_mismatch(self):
        self._cache(
            _item("scene-a", _box(0, 0, 2, 2), generation="mark-v"),
            _item("scene-b", _box(1, 0, 3, 2), generation="mark-v"),
        )
        response = self.api.post(
            "/api/mosaics/preflight",
            json={
                "inputs": [self._input("scene-a"), self._input("scene-b")],
                "mode": "polygon",
                "aoi": _box(0.5, 0.5, 1.5, 1.5),
                "sensor_generation": "mark-iv",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["valid"])
        self.assertTrue(any("sensor mismatch" in message.lower() for message in body["messages"]))

    def test_job_is_durable_and_can_be_canceled(self):
        self._cache(
            _item("scene-a", _box(-122.401, 37.699, -122.399, 37.701)),
            _item("scene-b", _box(-122.400, 37.699, -122.398, 37.701)),
        )
        payload = {"inputs": [self._input("scene-a"), self._input("scene-b")], "mode": "whole_strip"}
        created = self.api.post("/api/mosaics/jobs", json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["job"]["job_id"]
        self.assertEqual(created.json()["job"]["status"], "queued")
        fetched = self.api.get(f"/api/mosaics/jobs/{job_id}")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["job"]["payload"]["inputs"][0]["item_id"], "scene-a")
        canceled = self.api.post(f"/api/mosaics/jobs/{job_id}/cancel")
        self.assertEqual(canceled.status_code, 200, canceled.text)
        self.assertEqual(canceled.json()["job"]["status"], "canceled")

    def test_start_endpoint_launches_job_scoped_host_worker(self):
        self._cache(
            _item("scene-a", _box(-122.401, 37.699, -122.399, 37.701)),
            _item("scene-b", _box(-122.400, 37.699, -122.398, 37.701)),
        )
        created = self.api.post(
            "/api/mosaics/jobs",
            json={"inputs": [self._input("scene-a"), self._input("scene-b")], "mode": "whole_strip", "accelerator": "mps"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        job_id = created.json()["job"]["job_id"]
        process = Mock()
        process.pid = 4321
        process.poll.return_value = None
        with patch.object(main.subprocess, "Popen", return_value=process) as popen:
            started = self.api.post(f"/api/mosaics/jobs/{job_id}/start")
        self.assertEqual(started.status_code, 200, started.text)
        self.assertTrue(started.json()["worker"]["started"])
        command = popen.call_args.args[0]
        self.assertIn("--accelerator", command)
        self.assertEqual(command[command.index("--accelerator") + 1], "mps")
        self.assertEqual(started.json()["job"]["message"], "Starting host mosaic worker (mps)")

    def test_worker_contract_claims_reports_progress_and_downloads_job_input(self):
        item_a = _item("scene-a", _box(-122.401, 37.699, -122.399, 37.701))
        item_b = _item("scene-b", _box(-122.400, 37.699, -122.398, 37.701))
        self._cache(item_a, item_b)
        payload = {"inputs": [self._input("scene-a"), self._input("scene-b")], "mode": "whole_strip"}
        with patch.object(main, "_validate_proxy_url", side_effect=lambda url: url), \
             patch.object(main, "_download_bytes_for_url", return_value=b"geotiff-bytes"):
            created = self.api.post("/api/mosaics/jobs", json=payload)
            job_id = created.json()["job"]["job_id"]
            claimed = self.api.post(f"/api/mosaics/jobs/{job_id}/claim")
            progress = self.api.post(
                f"/api/mosaics/jobs/{job_id}/progress",
                json={"status": "running", "progress": 42, "message": "Downloading inputs"},
            )
            source = self.api.get(
                f"/api/mosaics/jobs/{job_id}/input",
                params={"item_id": "scene-a", "asset_key": "visual"},
            )
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(claimed.json()["job"]["status"], "running")
        self.assertEqual(progress.status_code, 200, progress.text)
        self.assertEqual(progress.json()["job"]["progress"], 42)
        self.assertEqual(source.status_code, 200, source.text)
        self.assertEqual(source.content, b"geotiff-bytes")

    def test_worker_cannot_download_an_unselected_item(self):
        self._cache(
            _item("scene-a", _box(-122.401, 37.699, -122.399, 37.701)),
            _item("scene-b", _box(-122.400, 37.699, -122.398, 37.701)),
        )
        created = self.api.post(
            "/api/mosaics/jobs",
            json={"inputs": [self._input("scene-a"), self._input("scene-b")], "mode": "whole_strip"},
        )
        job_id = created.json()["job"]["job_id"]
        response = self.api.get(
            f"/api/mosaics/jobs/{job_id}/input",
            params={"item_id": "not-in-job", "asset_key": "visual"},
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_quickview_selection_waits_for_l1d_sr_product_request(self):
        self._cache(
            _quickview("quick-a", _box(0, 0, 0.002, 0.002), "outcome-a"),
            _quickview("quick-b", _box(0.001, 0, 0.003, 0.002), "outcome-b"),
        )
        payload = {
            "inputs": [
                {**self._input("quick-a"), "collection_id": "quickview-visual-thumb"},
                {**self._input("quick-b"), "collection_id": "quickview-visual-thumb"},
            ],
            "mode": "polygon",
            "aoi": _box(0.0011, 0.0002, 0.0019, 0.0018),
        }
        with patch.object(main.sources, "search", return_value=[]):
            preflight = self.api.post("/api/mosaics/preflight", json=payload)
            created = self.api.post("/api/mosaics/jobs", json=payload)
        self.assertEqual(preflight.status_code, 200, preflight.text)
        self.assertTrue(preflight.json()["valid"])
        self.assertFalse(preflight.json()["ready"])
        self.assertEqual(preflight.json()["required_collection_id"], "l1d-sr")
        self.assertEqual(len(preflight.json()["missing_products"]), 2)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertTrue(created.json()["product_request_required"])
        self.assertEqual(created.json()["job"]["status"], "awaiting_product_request")

    def test_product_request_and_listener_resume_with_l1d_sr_inputs(self):
        source_a = _quickview("quick-a", _box(0, 0, 0.002, 0.002), "outcome-a")
        source_b = _quickview("quick-b", _box(0.001, 0, 0.003, 0.002), "outcome-b")
        self._cache(source_a, source_b)
        payload = {
            "inputs": [
                {**self._input("quick-a"), "collection_id": "quickview-visual-thumb"},
                {**self._input("quick-b"), "collection_id": "quickview-visual-thumb"},
            ],
            "mode": "polygon",
            "aoi": _box(0.0011, 0.0002, 0.0019, 0.0018),
            "contract_id": "contract-1",
        }
        with patch.object(main.sources, "search", return_value=[]):
            created = self.api.post("/api/mosaics/jobs", json=payload)
        job_id = created.json()["job"]["job_id"]
        remote_orders = [
            {"properties": {"order_id": "order-a"}},
            {"properties": {"order_id": "order-b"}},
        ]
        with patch.object(main.client, "list_orders", return_value={"features": []}), \
             patch.object(main.client, "create_order", side_effect=remote_orders) as create_order:
            requested = self.api.post(
                f"/api/mosaics/jobs/{job_id}/request-products",
                json={"confirmation": "REQUEST L1D-SR"},
            )
        self.assertEqual(requested.status_code, 200, requested.text)
        self.assertEqual(requested.json()["job"]["status"], "awaiting_products")
        self.assertEqual(create_order.call_count, 2)
        for call in create_order.call_args_list:
            feature = call.args[0]
            self.assertEqual(feature["properties"]["sku"], "ARCIMG-M.NN.NN")
            self.assertEqual(feature["properties"]["parameters"]["processing_level"], "L1D_SR")

        product_a = _item("l1dsr-a", _box(0.001, 0.0, 0.002, 0.002))
        product_a["outcome_id"] = "outcome-a"
        product_a["raw"]["properties"] = {"satl:outcome_id": "outcome-a"}
        product_b = _item("l1dsr-b", _box(0.001, 0.0, 0.002, 0.002))
        product_b["outcome_id"] = "outcome-b"
        product_b["raw"]["properties"] = {"satl:outcome_id": "outcome-b"}
        with patch.object(main.sources, "search", return_value=[product_a, product_b]), \
             patch.object(main, "_start_mosaic_worker", return_value={"started": True}) as start_worker:
            checked = self.api.post(f"/api/mosaics/jobs/{job_id}/check-products")
        self.assertEqual(checked.status_code, 200, checked.text)
        resumed = checked.json()["job"]
        self.assertEqual(resumed["status"], "queued")
        self.assertTrue(all(row["collection_id"] == "l1d-sr" for row in resumed["payload"]["inputs"]))
        self.assertEqual({row["item_id"] for row in resumed["payload"]["inputs"]}, {"l1dsr-a", "l1dsr-b"})
        start_worker.assert_called_once()
