from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.archive_watch import ArchiveWatchService
from backend.app.monitoring_store import MonitoringStore


TEST_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [30.10, 50.40],
        [30.30, 50.40],
        [30.30, 50.55],
        [30.10, 50.55],
        [30.10, 50.40],
    ]],
}


def _item(item_id: str, outcome_id: str, dt: str) -> dict:
    return {
        "id": item_id,
        "source_id": "satellogic",
        "collection": "quickview-visual-thumb",
        "datetime": dt,
        "outcome_id": outcome_id,
        "satellite_name": "newsat48",
        "sensor_generation": "mark-v",
        "gsd": 0.7,
        "cloud_cover": 12.0,
        "geometry": copy.deepcopy(TEST_GEOMETRY),
        "assets": {
            "thumbnail": "https://signed.example/provider-thumbnail.png",
            "preview": "https://signed.example/provider-preview.png",
        },
    }


class ArchiveWatchApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.api.close()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_store = main.app.state.monitoring_store
        self.previous_service = main.app.state.archive_watch_service
        self.sent = []
        self.store = MonitoringStore(Path(self.temp_dir.name) / "monitoring.sqlite3")

        def fake_email(watch, items, settings):
            self.sent.append((watch["watch_id"], items))
            return {"status": "sent", "recipients": ["analyst@example.org"], "count": len(items)}

        main.app.state.monitoring_store = self.store
        main.app.state.archive_watch_service = ArchiveWatchService(
            self.store,
            main.sources,
            main.settings,
            email_sender=fake_email,
        )

    def tearDown(self):
        main.app.state.monitoring_store = self.previous_store
        main.app.state.archive_watch_service = self.previous_service
        self.temp_dir.cleanup()

    def test_watch_checks_deduplicate_and_email_identity_based_preview_links(self):
        created = self.api.post(
            "/api/archive-watches",
            json={
                "name": "Eastern border airbase",
                "geometry": copy.deepcopy(TEST_GEOMETRY),
                "source_id": "satellogic",
                "collection_id": "quickview-visual-thumb",
                "contract_id": "contract-123",
                "filters": {"max_cloud_cover": 60, "sensor_generation": "mark-v"},
                "poll_interval_seconds": 15,
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        watch_id = created.json()["watch_id"]

        item = _item("scene-1", "outcome-1", "2026-08-16T08:00:00Z")
        with patch.object(main.sources, "search", return_value=[item]) as search:
            first = self.api.post(f"/api/archive-watches/{watch_id}/check", json={})
            second = self.api.post(f"/api/archive-watches/{watch_id}/check", json={})

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["new_count"], 1)
        self.assertEqual(first.json()["email"]["status"], "sent")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["new_count"], 0)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(search.call_count, 2)
        preview_url = self.sent[0][1][0]["preview_url"]
        self.assertIn("/api/archive/preview", preview_url)
        self.assertIn("item_id=scene-1", preview_url)
        self.assertNotIn("signed.example", preview_url)

        stored = self.api.get(f"/api/archive-watches/{watch_id}")
        self.assertEqual(stored.status_code, 200, stored.text)
        self.assertEqual(stored.json()["pending_count"], 0)

    def test_email_failure_keeps_items_pending_for_retry(self):
        created = self.api.post(
            "/api/archive-watches",
            json={"name": "Retry watch", "geometry": copy.deepcopy(TEST_GEOMETRY)},
        )
        watch_id = created.json()["watch_id"]
        service = main.app.state.archive_watch_service
        service.email_sender = lambda watch, items, settings: (_ for _ in ()).throw(RuntimeError("SMTP unavailable"))
        with patch.object(main.sources, "search", return_value=[_item("scene-2", "outcome-2", "2026-08-16T09:00:00Z")]):
            result = self.api.post(f"/api/archive-watches/{watch_id}/check", json={})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["email"]["status"], "failed")
        self.assertEqual(result.json()["pending_count"], 1)
        self.assertEqual(self.api.get(f"/api/archive-watches/{watch_id}").json()["pending_count"], 1)

    def test_watch_rejects_non_polygon_geometry(self):
        response = self.api.post(
            "/api/archive-watches",
            json={"name": "Point is not enough", "geometry": {"type": "Point", "coordinates": [30.2, 50.4]}},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Polygon", response.json().get("detail", ""))

    def test_manual_is_served_from_the_root_and_links_back_to_ui(self):
        response = self.api.get("/manual.html")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Image-Mate User Manual", response.text)
        self.assertIn('href="/"', response.text)


if __name__ == "__main__":
    unittest.main()
