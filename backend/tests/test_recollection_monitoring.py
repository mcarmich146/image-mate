from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.monitoring_store import MonitoringStore


TEST_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [-123.30, 49.19],
        [-123.02, 49.19],
        [-123.02, 49.33],
        [-123.30, 49.33],
        [-123.30, 49.19],
    ]],
}


def _item(scene_id: str, outcome_id: str, dt: str, cloud: float = 12.0) -> dict:
    return {
        "id": scene_id,
        "collection": "quickview-visual-thumb",
        "datetime": dt,
        "outcome_id": outcome_id,
        "satellite_name": "newsat48",
        "gsd": 20.0,
        "cloud_cover": cloud,
        "valid_pixel_percent": 92.0,
        "geometry": copy.deepcopy(TEST_GEOMETRY),
        "assets": {
            "thumbnail": "https://signed.example/thumb.png",
            "preview": "https://signed.example/preview.png",
        },
    }


class RecollectionMonitoringApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.api.close()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_store = main.app.state.monitoring_store
        main.app.state.monitoring_store = MonitoringStore(Path(self.temp_dir.name) / "monitoring.sqlite3")

    def tearDown(self):
        main.app.state.monitoring_store = self.previous_store
        self.temp_dir.cleanup()

    def test_create_refresh_and_dedupe_recollection_observations(self):
        create = self.api.post(
            "/api/recollection-monitors",
            json={
                "name": "Vancouver recollection watch",
                "geometry": copy.deepcopy(TEST_GEOMETRY),
                "source_id": "satellogic",
                "collection_id": "quickview-visual-thumb",
                "expected_revisit_days": 30,
                "filters": {"max_cloud_cover": 60},
            },
        )
        self.assertEqual(create.status_code, 200, create.text)
        monitor_id = create.json()["monitor_id"]

        recent_capture_at = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        older_capture_at = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        features = [
            _item("tile-a", "outcome-a", recent_capture_at),
            _item("tile-a-duplicate", "outcome-a", recent_capture_at),
            _item("tile-b", "outcome-b", older_capture_at, cloud=42.0),
        ]
        with patch.object(main.sources, "search", return_value=features) as search:
            refreshed = self.api.post(f"/api/recollection-monitors/{monitor_id}/refresh", json={})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        body = refreshed.json()
        self.assertEqual(body["monitor_id"], monitor_id)
        self.assertEqual(body["summary"]["observations_count"], 2)
        self.assertEqual(body["summary"]["new_observations"], 2)
        self.assertEqual(body["summary"]["archive_status"], "captured")
        self.assertEqual(body["summary"]["tasking_status"], "not_checked")
        self.assertEqual(body["summary"]["deliverable_status"], "not_checked")
        search.assert_called_once()

        with patch.object(main.sources, "search", return_value=features):
            refreshed_again = self.api.post(f"/api/recollection-monitors/{monitor_id}/refresh", json={})
        self.assertEqual(refreshed_again.status_code, 200, refreshed_again.text)
        self.assertEqual(refreshed_again.json()["summary"]["new_observations"], 0)

        listed = self.api.get("/api/recollection-monitors")
        self.assertEqual(listed.status_code, 200, listed.text)
        row = next(item for item in listed.json()["monitors"] if item["monitor_id"] == monitor_id)
        self.assertEqual(row["summary"]["observations_count"], 2)
        self.assertEqual(row["summary"]["latest_capture_at"], recent_capture_at)

    def test_recollection_monitor_rejects_unknown_source(self):
        response = self.api.post(
            "/api/recollection-monitors",
            json={
                "name": "Invalid source",
                "geometry": copy.deepcopy(TEST_GEOMETRY),
                "source_id": "unknown-source",
            },
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Unknown source_id", response.json().get("detail", ""))

    def test_linked_order_lifecycle_is_checked_without_persisting_raw_assets(self):
        create = self.api.post(
            "/api/recollection-monitors",
            json={
                "name": "Linked order watch",
                "geometry": copy.deepcopy(TEST_GEOMETRY),
                "source_id": "satellogic",
                "collection_id": "quickview-visual-thumb",
                "contract_id": "contract-123",
                "linked_order_id": "order-123",
            },
        )
        self.assertEqual(create.status_code, 200, create.text)
        monitor_id = create.json()["monitor_id"]
        lifecycle = {
            "order_id": "order-123",
            "order": {"status": "in_progress"},
            "events": [{"properties": {"type": "OrderAccepted"}}],
            "captures": [{"properties": {"status": "acquired"}}],
            "deliverables": [{"properties": {"status": "DELIVERED"}}],
            "rollup_status": "delivered",
            "checked_at": "2026-08-13T12:00:00Z",
        }
        with patch.object(main.sources, "search", return_value=[_item("tile-a", "outcome-a", "2026-08-10T18:00:00Z")]), \
             patch.object(main, "_order_lifecycle", return_value=lifecycle) as lifecycle_check:
            refreshed = self.api.post(f"/api/recollection-monitors/{monitor_id}/refresh", json={})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        body = refreshed.json()
        self.assertEqual(body["summary"]["tasking_status"], "delivered")
        self.assertEqual(body["summary"]["capture_status"], "acquired")
        self.assertEqual(body["summary"]["deliverable_status"], "delivered")
        lifecycle_check.assert_called_once_with("order-123", "contract-123")
        stored = self.api.get(f"/api/recollection-monitors/{monitor_id}").json()
        self.assertEqual(stored["summary"]["tasking_status"], "delivered")
        self.assertEqual(stored["observations"][0]["assets"], {})


if __name__ == "__main__":
    unittest.main()
