from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend.app.satellogic_client import SatellogicClient, normalize_item


class SatellogicClientTests(unittest.TestCase):
    def test_normalize_item_maps_official_cloud_asset_to_cloud_mask(self):
        item = normalize_item(
            {
                "id": "l1d-sr-item",
                "collection": "l1d-sr",
                "properties": {},
                "assets": {
                    "visual": {"href": "https://example.test/visual.tif"},
                    "cloud": {"href": "https://example.test/cloud.tif"},
                },
            }
        )

        self.assertEqual(item["assets"]["cloud_mask"], "https://example.test/cloud.tif")

    def test_search_expands_date_only_values_to_rfc3339_interval(self):
        response = Mock()
        response.ok = True
        response.json.return_value = {"features": [], "links": []}
        client = SatellogicClient()
        with patch.object(client, "auth_headers", return_value={}), \
             patch("backend.app.satellogic_client.requests.post", return_value=response) as post:
            client.search(
                geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                start_date="2026-03-31",
                end_date="2026-04-02",
                collection_id="l1d-sr",
                contract_id="contract-1",
                limit=10,
                max_cloud_cover=None,
            )
        self.assertEqual(
            post.call_args.kwargs["json"]["datetime"],
            "2026-03-31T00:00:00Z/2026-04-02T23:59:59Z",
        )


if __name__ == "__main__":
    unittest.main()
