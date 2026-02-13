from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import main


TEST_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[
        [-122.5, 37.7],
        [-122.3, 37.7],
        [-122.3, 37.9],
        [-122.5, 37.9],
        [-122.5, 37.7],
    ]],
}


def _sample_feature(item_id: str, dt: str, outcome_id: str | None = None, geometry: dict | None = None) -> dict:
    return {
        "id": item_id,
        "collection": "l1d-sr",
        "properties": {
            "datetime": dt,
            "eo:cloud_cover": 12.5,
            "satl:outcome_id": outcome_id or f"outcome-{item_id}",
        },
        "geometry": copy.deepcopy(geometry or TEST_GEOMETRY),
        "assets": {
            "visual": {"href": f"https://example.com/{item_id}_visual.tif"},
            "preview": {"href": f"https://example.com/{item_id}_preview.png"},
        },
    }


class ArchiveSearchApiTests(unittest.TestCase):
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
        main.app.state.archive_search_stats = {"total": 0, "by_collection": {}}
        main.app.state.item_cache = {}

    def test_archive_search_success_updates_stats(self):
        payload = {
            "geometry": copy.deepcopy(TEST_GEOMETRY),
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-02-11T00:00:00Z",
            "collection_id": "l1d-sr",
            "limit": 25,
            "max_cloud_cover": 40,
        }
        features = [
            _sample_feature("item-a", "2026-02-01T00:00:00Z"),
            _sample_feature("item-b", "2026-01-31T00:00:00Z"),
        ]

        with patch.object(main.client, "search", return_value=features) as mocked_search:
            resp = self.api.post("/api/archive/search", json=payload)

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["items"][0]["id"], "item-a")
        self.assertEqual(body["items"][0]["collection"], "l1d-sr")

        mocked_search.assert_called_once()
        kwargs = mocked_search.call_args.kwargs
        self.assertEqual(kwargs["collection_id"], "l1d-sr")
        self.assertEqual(kwargs["start_date"], payload["start_date"])
        self.assertEqual(kwargs["end_date"], payload["end_date"])
        self.assertEqual(kwargs["limit"], payload["limit"])

        stats = main.app.state.archive_search_stats
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["by_collection"]["l1d-sr"], 1)

    def test_archive_search_failure_returns_400(self):
        payload = {
            "geometry": copy.deepcopy(TEST_GEOMETRY),
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-02-11T00:00:00Z",
            "collection_id": "l1d-sr",
            "limit": 10,
            "max_cloud_cover": 40,
        }

        with patch.object(main.client, "search", side_effect=RuntimeError("upstream failure")):
            resp = self.api.post("/api/archive/search", json=payload)

        self.assertEqual(resp.status_code, 400)
        self.assertIn("Archive search failed", resp.json().get("detail", ""))

    def test_collections_endpoint_returns_sorted_options(self):
        fake_collections = [
            {"id": "quickview-visual-thumb", "title": "Quickview"},
            {"id": "l1d-sr", "title": "L1D SR"},
        ]
        with patch.object(main.client, "list_collections", return_value=fake_collections):
            resp = self.api.get("/api/collections")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual([item["id"] for item in body["collections"]], ["l1d-sr", "quickview-visual-thumb"])
        self.assertIn("default_collection_id", body)

if __name__ == "__main__":
    unittest.main()
