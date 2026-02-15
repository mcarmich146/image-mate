from __future__ import annotations

import copy
import unittest
from unittest.mock import Mock, patch

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

WMTS_CAPABILITIES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Capabilities xmlns="http://www.opengis.net/wmts/1.0" xmlns:ows="http://www.opengis.net/ows/1.1">
  <Contents>
    <Layer>
      <ows:Identifier>NATURAL-COLOR</ows:Identifier>
      <Dimension>
        <ows:Identifier>time</ows:Identifier>
        <Default>2026-02-14</Default>
      </Dimension>
      <TileMatrixSetLink>
        <TileMatrixSet>PopularWebMercator256</TileMatrixSet>
      </TileMatrixSetLink>
    </Layer>
    <Layer>
      <ows:Identifier>TRUE-COLOR-S2L2A</ows:Identifier>
      <TileMatrixSetLink>
        <TileMatrixSet>PopularWebMercator256</TileMatrixSet>
      </TileMatrixSetLink>
    </Layer>
  </Contents>
</Capabilities>
"""


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
        main.app.state.tile_cache_stats = {"hits": 0, "misses": 0}
        main.app.state.tile_delivery_stats = {
            "newsat": {"requests": 0, "errors": 0, "bytes": 0, "ms": 0},
            "merlin": {"requests": 0, "errors": 0, "bytes": 0, "ms": 0},
        }

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

    def test_sources_endpoint_lists_available_sources(self):
        resp = self.api.get("/api/sources")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIn("default_source_id", body)
        source_ids = {row.get("source_id") for row in body.get("sources", [])}
        self.assertIn("satellogic", source_ids)

    def test_sentinel_wmts_endpoint_reports_unavailable_without_instance(self):
        with patch.object(main.settings, "merlin_s2_enabled", True), \
             patch.object(main.settings, "cdse_wmts_instance_id", ""):
            resp = self.api.get("/api/layers/sentinel/wmts")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertFalse(bool(body.get("available")))
        self.assertIn("CDSE_WMTS_INSTANCE_ID", body.get("reason", ""))

    def test_sentinel_wmts_endpoint_returns_template_when_configured(self):
        mocked_capabilities = Mock(status_code=200, text=WMTS_CAPABILITIES_XML, headers={"content-type": "application/xml"})
        mocked_probe_ok = Mock(status_code=200, text="", headers={"content-type": "image/png"})
        with patch.object(main.settings, "merlin_s2_enabled", True), \
             patch.object(main.settings, "cdse_wmts_base_url", "https://example.com/wmts"), \
             patch.object(main.settings, "cdse_wmts_instance_id", "instance-123"), \
             patch.object(main.settings, "cdse_wmts_layer_id", "TRUE-COLOR"), \
             patch.object(main.settings, "cdse_wmts_format", "image/png"), \
             patch.object(main.settings, "cdse_wmts_tile_matrix_set", "PopularWebMercator256"), \
             patch.object(main.requests, "get", side_effect=[mocked_capabilities, mocked_probe_ok]):
            resp = self.api.get("/api/layers/sentinel/wmts")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(bool(body.get("available")))
        self.assertTrue(str(body.get("template_url", "")).startswith("/api/layers/sentinel/wmts/tiles/{z}/{x}/{y}"))
        self.assertIn("layer_id=NATURAL-COLOR", body.get("template_url", ""))
        self.assertIn("tile_matrix_set=PopularWebMercator256", body.get("template_url", ""))
        self.assertIn("time=2026-02-14", body.get("template_url", ""))
        self.assertIn("/instance-123", body.get("upstream_template_url", ""))
        self.assertIn("LAYER=NATURAL-COLOR", body.get("upstream_template_url", ""))
        self.assertNotIn("STYLE=", body.get("upstream_template_url", ""))
        self.assertIn("TILEMATRIXSET=PopularWebMercator256", body.get("upstream_template_url", ""))
        self.assertIn("TIME=2026-02-14", body.get("upstream_template_url", ""))
        self.assertIn("NATURAL-COLOR", body.get("available_layers", []))
        self.assertEqual(body.get("requested_layer_id"), "TRUE-COLOR")
        self.assertEqual(body.get("default_time"), "2026-02-14")
        self.assertIn("Configured layer 'TRUE-COLOR' was not in WMTS capabilities.", body.get("warning", ""))

    def test_sentinel_wmts_endpoint_marks_unavailable_when_tile_probe_fails(self):
        mocked_capabilities = Mock(status_code=200, text=WMTS_CAPABILITIES_XML, headers={"content-type": "application/xml"})
        mocked_probe = Mock(
            status_code=400,
            text="<ows:ExceptionReport><ows:ExceptionText>No style defined in TRUE-COLOR</ows:ExceptionText></ows:ExceptionReport>",
            headers={"content-type": "application/xml"},
        )
        with patch.object(main.settings, "merlin_s2_enabled", True), \
             patch.object(main.settings, "cdse_wmts_base_url", "https://example.com/wmts"), \
             patch.object(main.settings, "cdse_wmts_instance_id", "instance-123"), \
             patch.object(main.settings, "cdse_wmts_layer_id", "NATURAL-COLOR"), \
             patch.object(main.settings, "cdse_wmts_format", "image/png"), \
             patch.object(main.settings, "cdse_wmts_tile_matrix_set", "PopularWebMercator256"), \
             patch.object(main.requests, "get", side_effect=[mocked_capabilities, mocked_probe]):
            resp = self.api.get("/api/layers/sentinel/wmts")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertFalse(bool(body.get("available")))
        self.assertIn("WMTS tile probe failed", body.get("reason", ""))
        self.assertIn("No style defined in TRUE-COLOR", body.get("warning", ""))

    def test_sentinel_wmts_endpoint_honors_layer_id_query_override(self):
        mocked_capabilities = Mock(status_code=200, text=WMTS_CAPABILITIES_XML, headers={"content-type": "application/xml"})
        mocked_probe_ok = Mock(status_code=200, text="", headers={"content-type": "image/png"})
        with patch.object(main.settings, "merlin_s2_enabled", True), \
             patch.object(main.settings, "cdse_wmts_base_url", "https://example.com/wmts"), \
             patch.object(main.settings, "cdse_wmts_instance_id", "instance-123"), \
             patch.object(main.settings, "cdse_wmts_layer_id", "TRUE-COLOR"), \
             patch.object(main.settings, "cdse_wmts_format", "image/png"), \
             patch.object(main.settings, "cdse_wmts_tile_matrix_set", "PopularWebMercator256"), \
             patch.object(main.requests, "get", side_effect=[mocked_capabilities, mocked_probe_ok]):
            resp = self.api.get("/api/layers/sentinel/wmts?layer_id=TRUE-COLOR-S2L2A")

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(bool(body.get("available")))
        self.assertEqual(body.get("requested_layer_id"), "TRUE-COLOR-S2L2A")
        self.assertEqual(body.get("layer_id"), "TRUE-COLOR-S2L2A")

    def test_sentinel_wmts_tile_proxy_updates_delivery_stats(self):
        mocked_tile = Mock(status_code=200, content=b"\x89PNG\x0d\x0a", headers={"Content-Type": "image/png"})
        with patch.object(main.settings, "merlin_s2_enabled", True), \
             patch.object(main.settings, "cdse_wmts_base_url", "https://example.com/wmts"), \
             patch.object(main.settings, "cdse_wmts_instance_id", "instance-123"), \
             patch.object(main.requests, "get", return_value=mocked_tile):
            resp = self.api.get(
                "/api/layers/sentinel/wmts/tiles/10/511/384"
                "?layer_id=NATURAL-COLOR&tile_matrix_set=PopularWebMercator256&format=image/png&time=2026-02-14"
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.headers.get("content-type"), "image/png")
        stats = self.api.get("/api/debug/stats").json()
        merlin_stats = stats.get("tile_delivery", {}).get("merlin", {})
        self.assertGreaterEqual(int(merlin_stats.get("requests", 0)), 1)
        self.assertGreater(int(merlin_stats.get("bytes", 0)), 0)

    def test_raster_cog_tile_proxy_updates_newsat_delivery_stats(self):
        mocked_upstream = Mock(status_code=200, content=b"\x89PNG\x0d\x0a", headers={"Content-Type": "image/png"})
        with patch.object(main, "_cog_upstream_request", return_value=(mocked_upstream, "oauth_client_credentials")):
            resp = self.api.get(
                "/api/raster/cog/tiles/12/659/1583"
                "?url=s3://demo-bucket/demo.tif&tileMatrixSetId=WebMercatorQuad&format=png&render_layer=raw&bidx=1&bidx=2&bidx=3"
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        stats = self.api.get("/api/debug/stats").json()
        newsat_stats = stats.get("tile_delivery", {}).get("newsat", {})
        self.assertGreaterEqual(int(newsat_stats.get("requests", 0)), 1)
        self.assertGreater(int(newsat_stats.get("bytes", 0)), 0)

    def test_archive_search_merlin_source_uses_source_router(self):
        payload = {
            "source_id": "merlin-s2",
            "geometry": copy.deepcopy(TEST_GEOMETRY),
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-02-11T00:00:00Z",
            "collection_id": "sentinel-2-l2a",
            "limit": 25,
            "max_cloud_cover": 40,
        }
        mocked_items = [
            {
                "id": "merlin-s2:S2A_ITEM",
                "source_id": "merlin-s2",
                "collection": "sentinel-2-l2a",
                "datetime": "2026-02-01T00:00:00Z",
                "outcome_id": "S2A_ITEM",
                "satellite_name": "S2A",
                "gsd": 10.0,
                "cloud_cover": 8.0,
                "valid_pixel_percent": 90.0,
                "geometry": copy.deepcopy(TEST_GEOMETRY),
                "assets": {
                    "visual": "https://example.com/s2_visual.tif",
                    "preview": "https://example.com/s2_preview.png",
                    "thumbnail": "https://example.com/s2_thumb.png",
                    "analytic": "https://example.com/s2_analytic.tif",
                },
            }
        ]

        with patch.object(main, "_search_items", return_value=mocked_items) as mocked_search:
            resp = self.api.post("/api/archive/search", json=payload)

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["source_id"], "merlin-s2")
        mocked_search.assert_called_once()
        kwargs = mocked_search.call_args.args[0]
        self.assertEqual(kwargs["source_id"], "merlin-s2")

if __name__ == "__main__":
    unittest.main()
