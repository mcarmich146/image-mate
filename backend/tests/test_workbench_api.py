from __future__ import annotations

import copy
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main


def _item(scene_id: str, dt: str, west: float = -122.6, south: float = 37.6) -> dict:
    east = west + 0.05
    north = south + 0.05
    return {
        "id": scene_id,
        "collection": "l1d-sr",
        "datetime": dt,
        "outcome_id": f"{scene_id}_outcome",
        "satellite_name": "SN52",
        "gsd": 0.9,
        "cloud_cover": 12.0,
        "valid_pixel_percent": 88.0,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]],
        },
        "assets": {
            "thumbnail": f"https://example.com/{scene_id}_thumb.png",
            "preview": f"https://example.com/{scene_id}_preview.png",
            "visual": f"https://example.com/{scene_id}_visual.tif",
        },
    }


class WorkbenchApiTests(unittest.TestCase):
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
        # Reset item cache per test to avoid cross-test drift.
        main.app.state.item_cache = {}

    def test_workflow_catalog_endpoint(self):
        resp = self.api.get("/api/workflows")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertGreaterEqual(body.get("count", 0), 3)
        self.assertIn("skills", body)
        self.assertIn("providers", body)
        workflow_ids = {w.get("workflow_id") for w in body.get("workflows", [])}
        self.assertIn("forest_urban_change_series", workflow_ids)

    def test_create_run_and_fetch_artifacts(self):
        a = _item("scene-a", "2026-02-01T00:00:00Z")
        b = _item("scene-b", "2026-02-02T00:00:00Z", west=-122.5)
        main.app.state.item_cache[a["id"]] = copy.deepcopy(a)
        main.app.state.item_cache[b["id"]] = copy.deepcopy(b)

        payload = {
            "workflow_id": "airbase_time_series_analyst",
            "workflow_version": "1.0.0",
            "idempotency_key": f"test-workbench-api-{time.time_ns()}",
            "inputs_payload": {
                "roi": copy.deepcopy(a["geometry"]),
                "scene_ids": [a["id"], b["id"]],
                "start_date": "2026-02-01T00:00:00Z",
                "end_date": "2026-02-02T00:00:00Z",
                "params": {"max_scenes": 12},
            },
        }
        resp = self.api.post("/api/runs", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        run_id = resp.json()["run_id"]

        status = None
        for _ in range(80):
            row = self.api.get(f"/api/runs/{run_id}")
            self.assertEqual(row.status_code, 200, row.text)
            status = row.json().get("status")
            if status in {"completed", "failed"}:
                break
            time.sleep(0.05)

        self.assertEqual(status, "completed")
        arts = self.api.get(f"/api/runs/{run_id}/artifacts")
        self.assertEqual(arts.status_code, 200, arts.text)
        names = [a.get("uri", "").split("/")[-1] for a in arts.json().get("artifacts", [])]
        self.assertIn("report.md", names)
        self.assertIn("report.json", names)
        self.assertIn("report.docx", names)
        self.assertIn("provenance.json", names)
        self.assertIn("hashes.txt", names)

    def test_poi_subscription_schedule_endpoints(self):
        poi_resp = self.api.post(
            "/api/poi_sets",
            json={
                "name": "test-poi",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-122.7, 37.5],
                        [-122.4, 37.5],
                        [-122.4, 37.8],
                        [-122.7, 37.8],
                        [-122.7, 37.5],
                    ]],
                },
            },
        )
        self.assertEqual(poi_resp.status_code, 200, poi_resp.text)
        poi_id = poi_resp.json()["poi_set_id"]

        sub_resp = self.api.post("/api/subscriptions", json={"poi_set_id": poi_id, "enabled": True})
        self.assertEqual(sub_resp.status_code, 200, sub_resp.text)
        sub_id = sub_resp.json()["subscription_id"]

        sch_resp = self.api.post(
            "/api/schedules",
            json={
                "type": "CRON",
                "workflow_id": "airbase_time_series_analyst",
                "workflow_version": "1.0.0",
                "subscription_id": sub_id,
                "cron": "*/30 * * * *",
                "enabled": True,
            },
        )
        self.assertEqual(sch_resp.status_code, 200, sch_resp.text)
        trigger_id = sch_resp.json()["trigger_id"]

        rows = self.api.get("/api/schedules")
        self.assertEqual(rows.status_code, 200, rows.text)
        self.assertGreaterEqual(rows.json().get("count", 0), 1)

        patched = self.api.patch(f"/api/schedules/{trigger_id}", json={"enabled": False})
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertFalse(bool(patched.json().get("enabled")))

if __name__ == "__main__":
    unittest.main()
