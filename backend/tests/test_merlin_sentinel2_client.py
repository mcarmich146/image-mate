from __future__ import annotations

import unittest
from unittest.mock import patch
import requests

from backend.app.merlin_sentinel2_client import MerlinSentinel2Client, normalize_merlin_item
from backend.app import merlin_sentinel2_client as merlin_mod


class _FakeResponse:
    def __init__(self, status_code: int, payload: object):
        self.status_code = int(status_code)
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class MerlinAssetNormalizationTests(unittest.TestCase):
    def test_prefers_https_alternate_over_s3_preview(self):
        feature = {
            "id": "S2A_TEST",
            "collection": "sentinel-2-l2a",
            "properties": {"datetime": "2026-02-14T00:00:00Z"},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            "assets": {
                "thumbnail": {
                    "href": "s3://eodata/Sentinel-2/quicklook.jpg",
                    "alternate": {
                        "https": {"href": "https://catalogue.dataspace.copernicus.eu/quicklook.jpg"},
                    },
                }
            },
        }

        row = normalize_merlin_item(feature, source_id="merlin-s2")
        self.assertTrue(row["assets"]["thumbnail"].startswith("https://"))
        self.assertEqual(row["assets"]["thumbnail"], "https://catalogue.dataspace.copernicus.eu/quicklook.jpg")

    def test_supports_preview_from_links_when_assets_missing(self):
        feature = {
            "id": "S2B_TEST",
            "collection": "sentinel-2-l2a",
            "properties": {"datetime": "2026-02-14T00:00:00Z"},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            "assets": {},
            "links": [
                {
                    "rel": "preview",
                    "href": "https://catalogue.dataspace.copernicus.eu/previews/S2B_TEST.png",
                    "type": "image/png",
                }
            ],
        }

        row = normalize_merlin_item(feature, source_id="merlin-s2")
        self.assertEqual(row["assets"]["preview"], "https://catalogue.dataspace.copernicus.eu/previews/S2B_TEST.png")
        self.assertEqual(row["assets"]["thumbnail"], "https://catalogue.dataspace.copernicus.eu/previews/S2B_TEST.png")

    def test_resolves_relative_asset_href_to_cdse_origin(self):
        feature = {
            "id": "S2C_TEST",
            "collection": "sentinel-2-l2a",
            "properties": {"datetime": "2026-02-14T00:00:00Z"},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            "assets": {
                "preview": {"href": "/api/v1/previews/S2C_TEST.png"},
            },
        }

        with patch("backend.app.merlin_sentinel2_client.settings.cdse_stac_url", "https://catalogue.dataspace.copernicus.eu/stac"):
            row = normalize_merlin_item(feature, source_id="merlin-s2")
        self.assertEqual(row["assets"]["preview"], "https://catalogue.dataspace.copernicus.eu/api/v1/previews/S2C_TEST.png")

    def test_rewrites_internal_catalogue_host_to_public_catalogue_host(self):
        feature = {
            "id": "S2D_TEST",
            "collection": "sentinel-2-l2a",
            "properties": {"datetime": "2026-02-14T00:00:00Z"},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            "assets": {
                "visual": {
                    "href": "https://catalogue-svc.prod-catalogue.svc.cluster.local:8250/odata/v1/Assets(abc)/$value",
                }
            },
        }
        row = normalize_merlin_item(feature, source_id="merlin-s2")
        self.assertEqual(
            row["assets"]["visual"],
            "https://catalogue.dataspace.copernicus.eu/odata/v1/Assets(abc)/$value",
        )

    def test_visual_avoids_xml_download_links(self):
        feature = {
            "id": "S2E_TEST",
            "collection": "sentinel-2-l2a",
            "properties": {"datetime": "2026-02-14T00:00:00Z"},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            "assets": {
                "data": {
                    "href": "https://zipper.dataspace.copernicus.eu/odata/v1/Products(x)/Nodes(MTD_TL.xml)/$value",
                },
                "preview": {
                    "href": "https://catalogue.dataspace.copernicus.eu/previews/S2E_TEST.png",
                },
            },
        }
        row = normalize_merlin_item(feature, source_id="merlin-s2")
        self.assertEqual(row["assets"]["visual"], "https://catalogue.dataspace.copernicus.eu/previews/S2E_TEST.png")
        self.assertNotIn(".xml", row["assets"]["visual"].lower())

    def test_prefers_non_preview_visual_for_fullres(self):
        feature = {
            "id": "S2F_TEST",
            "collection": "sentinel-2-l2a",
            "properties": {"datetime": "2026-02-14T00:00:00Z"},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            "assets": {
                "visual": {
                    "href": "https://catalogue.dataspace.copernicus.eu/odata/v1/Assets(fullres-id)/$value",
                    "title": "True Color Image 10m",
                    "roles": ["data", "visual"],
                    "type": "image/tiff",
                },
                "thumbnail": {
                    "href": "https://catalogue.dataspace.copernicus.eu/previews/S2F_TEST.png",
                    "title": "Thumbnail",
                    "roles": ["thumbnail"],
                    "type": "image/png",
                },
            },
        }
        row = normalize_merlin_item(feature, source_id="merlin-s2")
        self.assertEqual(
            row["assets"]["visual_fullres"],
            "https://catalogue.dataspace.copernicus.eu/odata/v1/Assets(fullres-id)/$value",
        )
        self.assertEqual(row["assets"]["visual"], row["assets"]["visual_fullres"])

    def test_prefers_tci_over_aot_for_visual_fullres(self):
        feature = {
            "id": "S2G_TEST",
            "collection": "sentinel-2-l2a",
            "properties": {"datetime": "2026-02-14T00:00:00Z"},
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            "assets": {
                "AOT_10m": {
                    "href": "https://eodata.dataspace.copernicus.eu/path/T11XXX_20260214T000000_AOT_10m.jp2",
                    "roles": ["data"],
                    "type": "image/jp2",
                },
                "TCI_10m": {
                    "href": "https://eodata.dataspace.copernicus.eu/path/T11XXX_20260214T000000_TCI_10m.jp2",
                    "roles": ["visual", "data"],
                    "type": "image/jp2",
                },
                "thumbnail": {
                    "href": "https://catalogue.dataspace.copernicus.eu/previews/S2G_TEST.png",
                    "roles": ["thumbnail"],
                    "type": "image/png",
                },
            },
        }
        row = normalize_merlin_item(feature, source_id="merlin-s2")
        self.assertIn("TCI_10m.jp2", row["assets"]["visual_fullres"])
        self.assertIn("TCI_10m.jp2", row["assets"]["visual"])

class MerlinAuthRoutingTests(unittest.TestCase):
    def _client(self) -> MerlinSentinel2Client:
        with patch.object(merlin_mod.settings, "merlin_s2_enabled", True):
            return MerlinSentinel2Client()

    def test_uses_download_token_for_cdse_odata(self):
        client = self._client()
        with patch.object(client, "_get_access_token", return_value="cc-token") as cc_mock, \
             patch.object(client, "_get_download_access_token", return_value="download-token") as dl_mock:
            headers = client.auth_headers_for_url("https://catalogue.dataspace.copernicus.eu/odata/v1/Products(abc)/$value")
        self.assertEqual(headers.get("Authorization"), "Bearer download-token")
        dl_mock.assert_called_once()
        cc_mock.assert_not_called()

    def test_uses_client_credentials_for_sentinel_hub_urls(self):
        client = self._client()
        with patch.object(client, "_get_access_token", return_value="cc-token") as cc_mock, \
             patch.object(client, "_get_download_access_token", return_value="download-token") as dl_mock:
            headers = client.auth_headers_for_url("https://sh.dataspace.copernicus.eu/ogc/wmts")
        self.assertEqual(headers.get("Authorization"), "Bearer cc-token")
        cc_mock.assert_called_once()
        dl_mock.assert_not_called()


class MerlinStacFallbackTests(unittest.TestCase):
    def _client(self) -> MerlinSentinel2Client:
        with patch.object(merlin_mod.settings, "merlin_s2_enabled", True), \
             patch.object(merlin_mod.settings, "cdse_stac_url", "https://primary.example.com/v1"):
            return MerlinSentinel2Client()

    def test_search_falls_back_when_primary_returns_404(self):
        client = self._client()
        fake_features = [{"id": "S2X", "properties": {}, "geometry": {"type": "Point", "coordinates": [0, 0]}, "assets": {}}]
        with patch.object(client, "auth_headers", return_value={"Authorization": "Bearer token"}), \
             patch("backend.app.merlin_sentinel2_client.requests.request", side_effect=[
                 _FakeResponse(404, {"detail": "not found"}),
                 _FakeResponse(200, {"features": fake_features}),
             ]) as req_mock:
            rows = client.search(
                geometry={"type": "Point", "coordinates": [0, 0]},
                start_date="2026-02-01T00:00:00Z",
                end_date="2026-02-02T00:00:00Z",
                collection_id="sentinel-2-l2a",
                limit=5,
                max_cloud_cover=40,
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(req_mock.call_count, 2)

if __name__ == "__main__":
    unittest.main()
