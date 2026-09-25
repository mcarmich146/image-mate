from __future__ import annotations

import copy
import json
import requests
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.monitoring_store import MonitoringStore


POINT_GEOMETRY = {"type": "Point", "coordinates": [-122.4, 37.7]}
POLYGON_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [-122.6, 37.6],
        [-122.2, 37.6],
        [-122.2, 37.9],
        [-122.6, 37.9],
        [-122.6, 37.6],
    ]],
}


class WebUpgradeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._refresh_patcher = patch.object(main.client, "refresh_access_token", return_value=(True, None))
        cls._refresh_patcher.start()
        cls.api = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.api.close()
        cls._refresh_patcher.stop()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_store = main.app.state.monitoring_store
        main.app.state.monitoring_store = MonitoringStore(Path(self.temp_dir.name) / "monitoring.sqlite3")

    def tearDown(self):
        main.app.state.monitoring_store = self.previous_store
        self.temp_dir.cleanup()

    def test_tasking_write_requires_typed_confirmation(self):
        payload = {
            "target_type": "point",
            "geometry": copy.deepcopy(POINT_GEOMETRY),
            "order_name": "safe-order",
            "project_name": "web-test",
            "sku": "TSKPOI-M",
            "start_date": "2026-09-01T00:00:00Z",
            "end_date": "2026-09-04T00:00:00Z",
            "contract_id": "contract-123",
        }
        with patch.object(main.client, "create_order") as create_order:
            response = self.api.post("/api/tasking/orders", json=payload)
        self.assertEqual(response.status_code, 400, response.text)
        create_order.assert_not_called()
        self.assertIn("confirmation", response.json()["detail"].lower())

    def test_tasking_preview_is_read_only_and_returns_feature(self):
        payload = {
            "target_type": "area",
            "geometry": copy.deepcopy(POLYGON_GEOMETRY),
            "order_name": "preview-order",
            "project_name": "web-test",
            "sku": "TSKARE-M",
            "start_date": "2026-09-01T00:00:00Z",
            "end_date": "2026-09-04T00:00:00Z",
            "contract_id": "contract-123",
        }
        with patch.object(main.client, "create_order") as create_order:
            response = self.api.post("/api/tasking/orders/preview", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["feature"]["properties"]["order_name"], "Mark - preview-order")
        create_order.assert_not_called()

    def test_confirmed_tasking_is_verified_by_follow_up_get(self):
        payload = {
            "target_type": "point",
            "geometry": copy.deepcopy(POINT_GEOMETRY),
            "order_name": "confirmed-order",
            "project_name": "web-test",
            "sku": "TSKPOI-M",
            "start_date": "2026-09-01T00:00:00Z",
            "end_date": "2026-09-04T00:00:00Z",
            "contract_id": "contract-123",
            "confirmation": "Mark - confirmed-order",
        }
        created = {
            "id": "remote-1",
            "type": "Feature",
            "geometry": copy.deepcopy(POINT_GEOMETRY),
            "properties": {
                "order_name": "Mark - confirmed-order",
                "project_name": "web-test",
                "sku": "TSKPOI-M",
                "status": "received",
            },
        }
        verified = copy.deepcopy(created)
        verified["properties"]["status"] = "in_progress"
        with patch.object(main.client, "create_order", return_value=created) as create_order, \
             patch.object(main.client, "get_order", return_value=verified) as get_order:
            response = self.api.post("/api/tasking/orders", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["verified"])
        self.assertEqual(body["order"]["status"], "in_progress")
        create_order.assert_called_once()
        get_order.assert_called_once_with("remote-1", contract_id="contract-123")

    def test_ambiguous_tasking_timeout_reconciles_without_replaying_post(self):
        payload = {
            "target_type": "point",
            "geometry": copy.deepcopy(POINT_GEOMETRY),
            "order_name": "ambiguous-order",
            "project_name": "web-test",
            "sku": "TSKPOI-M",
            "start_date": "2026-09-01T00:00:00Z",
            "end_date": "2026-09-04T00:00:00Z",
            "contract_id": "contract-123",
            "confirmation": "Mark - ambiguous-order",
        }
        remote = {
            "id": "remote-timeout-1",
            "type": "Feature",
            "geometry": copy.deepcopy(POINT_GEOMETRY),
            "properties": {
                "order_name": "Mark - ambiguous-order",
                "project_name": "web-test",
                "sku": "TSKPOI-M",
                "status": "received",
            },
        }
        with patch.object(main.client, "create_order", side_effect=requests.Timeout("provider timeout")) as create_order, \
             patch.object(main.client, "list_orders", return_value={"results": [remote]}) as list_orders, \
             patch.object(main.client, "get_order", return_value=remote):
            response = self.api.post("/api/tasking/orders", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["reconciled"])
        create_order.assert_called_once()
        list_orders.assert_called_once()

    def test_opportunity_analysis_is_read_only_and_pollable(self):
        payload = {
            "target_type": "area",
            "geometry": copy.deepcopy(POLYGON_GEOMETRY),
            "order_name": "opportunity-preview",
            "project_name": "web-test",
            "sku": "TSKARE-M",
            "start_date": "2026-09-01T00:00:00Z",
            "end_date": "2026-09-04T00:00:00Z",
            "contract_id": "contract-123",
        }
        with patch.object(main.client, "create_opportunity_analysis", return_value={"analysis_id": "analysis-1", "status": "PENDING"}) as create_analysis, \
             patch.object(main.client, "get_opportunity_analysis", return_value={"id": "analysis-1", "status": "SUCCESS"}) as get_analysis, \
             patch.object(main.client, "create_order") as create_order:
            response = self.api.post("/api/tasking/opportunities", json=payload)
            status = self.api.get("/api/tasking/opportunities/analysis-1?contract_id=contract-123")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["read_only"])
        self.assertEqual(response.json()["analysis_id"], "analysis-1")
        self.assertEqual(status.status_code, 200, status.text)
        self.assertEqual(status.json()["status"], "success")
        create_analysis.assert_called_once()
        get_analysis.assert_called_once_with("analysis-1", contract_id="contract-123")
        create_order.assert_not_called()

    def test_cancellation_requires_exact_order_id_and_verifies_follow_up_status(self):
        order = {
            "id": "cancel-me",
            "type": "Feature",
            "geometry": copy.deepcopy(POINT_GEOMETRY),
            "properties": {"order_name": "cancel-order", "sku": "TSKPOI-M", "status": "canceled"},
        }
        with patch.object(main.client, "cancel_order", return_value={"status": "cancellation_requested"}) as cancel_order, \
             patch.object(main.client, "get_order", return_value=order) as get_order:
            rejected = self.api.post(
                "/api/tasking/orders/cancel-me/cancel",
                json={"confirmation": "wrong-id", "contract_id": "contract-123"},
            )
            accepted = self.api.post(
                "/api/tasking/orders/cancel-me/cancel",
                json={"confirmation": "cancel-me", "contract_id": "contract-123"},
            )
        self.assertEqual(rejected.status_code, 400, rejected.text)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertTrue(accepted.json()["requested"])
        self.assertTrue(accepted.json()["verified"])
        cancel_order.assert_called_once_with("cancel-me", contract_id="contract-123")
        get_order.assert_called_once_with("cancel-me", contract_id="contract-123")

    def test_lifecycle_rollup_reads_order_events_captures_and_deliverables(self):
        order = {
            "id": "remote-1",
            "properties": {"status": "closed", "order_name": "confirmed-order", "sku": "TSKARE-M"},
        }
        with patch.object(main.client, "get_order", return_value=order), \
             patch.object(main.client, "list_order_events", return_value={"results": []}), \
             patch.object(main.client, "list_order_captures", return_value={"results": [{"id": "cap-1", "properties": {"status": "acquired"}}]}), \
             patch.object(main.client, "list_order_deliverables", return_value={"results": [{"id": "del-1", "properties": {"status": "DELIVERED"}}]}):
            response = self.api.get("/api/tasking/orders/remote-1/lifecycle?contract_id=contract-123")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["rollup_status"], "delivered")
        self.assertEqual(len(body["captures"]), 1)
        self.assertEqual(len(body["deliverables"]), 1)

    def test_grid_plan_is_read_only_and_returns_individual_order_features(self):
        payload = {
            "campaign_name": "grid-web-test",
            "project_name": "grid-project",
            "order_prefix": "grid-web-test_",
            "geometry": copy.deepcopy(POLYGON_GEOMETRY),
            "parameters": {
                "cell_size_km": 20,
                "min_area_km2": 1,
                "start": "2026-09-01T00:00:00Z",
                "end": "2026-10-01T00:00:00Z",
            },
            "contract_id": "contract-123",
        }
        with patch.object(main.client, "create_order") as create_order:
            response = self.api.post("/api/tasking/grid/plan", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertGreater(body["summary"]["cell_count"], 0)
        self.assertTrue(body["order_payloads"])
        self.assertTrue(all(row["type"] == "Feature" for row in body["order_payloads"]))
        create_order.assert_not_called()

    def test_analytics_summary_counts_categories_and_classes(self):
        deliverable = {
            "id": "del-analytics",
            "assets": {"analytics_vessels": {"href": "https://api.satellogic.com/vessels.geojson"}},
        }
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "properties": {"classification": {"category": "vessel"}, "class": "cargo", "confidence": 0.8}},
                {"type": "Feature", "properties": {"classification": {"category": "vessel"}, "class": "cargo", "confidence": 0.6}},
                {"type": "Feature", "properties": {"classification": {"category": "vessel"}, "class": "tanker", "confidence": 0.9}},
            ],
        }
        with patch.object(main.client, "get_deliverable", return_value=deliverable), \
             patch.object(main.client, "download_bytes", return_value=json.dumps(geojson).encode("utf-8")):
            response = self.api.get("/api/analytics/deliverables/del-analytics/summary?asset_key=analytics_vessels")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["feature_count"], 3)
        self.assertEqual(body["categories"]["vessel"]["count"], 3)
        self.assertEqual(body["categories"]["vessel"]["classes"]["cargo"]["count"], 2)

    def test_proxy_blocks_loopback_urls(self):
        response = self.api.get("/api/assets/proxy", params={"url": "http://127.0.0.1/secret"})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("private", response.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
