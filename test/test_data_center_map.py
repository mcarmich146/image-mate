import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import transform_geom

from scripts import build_data_center_map as builder


class DataCenterMapTests(unittest.TestCase):
    def test_inventory_has_thirteen_sites_and_qualified_locations(self):
        research = json.loads((builder.RESEARCH / "data-center-imagery-2026-09-09.json").read_text())
        geojson = json.loads((builder.RESEARCH / "data-center-search-aois-2026-09-09.geojson").read_text())
        sites = builder.prepare_sites(research, geojson)
        self.assertEqual(len(sites), 13)
        self.assertEqual(len({s["id"] for s in sites}), 13)
        colossus = next(s for s in sites if s["name"] == "Colossus 2 facility search")
        self.assertEqual(colossus["center"], [-90.042977, 34.999489])
        river = next(s for s in sites if "River Bend" in s["name"])
        self.assertIn("NOT a verified campus center", river["note"])
        self.assertFalse(river["tasking_location_verified"])
        lake_mariner = next(s for s in sites if "Lake Mariner" in s["name"])
        self.assertTrue(lake_mariner["tasking_location_verified"])
        self.assertTrue(next(s for s in sites if "Abilene" in s["name"])["expected_outcomes"])

    def raster(self):
        with MemoryFile() as mem:
            with mem.open(driver="GTiff", width=16, height=16, count=3, dtype="uint8",
                          crs="EPSG:3857", transform=from_origin(-10000000, 4000000, 20, 20)) as src:
                src.write(np.full((3,16,16), 120, dtype=np.uint8))
            return mem.read()

    def item(self):
        triangle = {"type":"Polygon", "coordinates":[[
            [-10000000,4000000], [-9999680,4000000], [-10000000,3999680], [-10000000,4000000],
        ]]}
        return {"id":"synthetic", "properties":{"proj:epsg":4326},
                "geometry":transform_geom("EPSG:3857", "EPSG:4326", triangle),
                "assets":{"analytic":{"type":"image/tiff", "href":"https://example.test/browse.tif"}}}

    def test_uses_embedded_crs_and_clips_alpha_to_footprint(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(builder, "OUT", Path(temp)):
            (Path(temp) / "images").mkdir()
            client = Mock()
            client.download_bytes.return_value = self.raster()
            result = builder.export_raster(client, self.item())
            self.assertEqual(result["raster_crs"], "EPSG:3857")
            self.assertEqual(result["stac_crs"], 4326)
            with Image.open(Path(temp) / result["image"]) as image:
                alpha = np.asarray(image)[:,:,3]
                self.assertTrue(np.any(alpha == 0))
                self.assertTrue(np.any(alpha == 255))
            self.assertLess(result["bounds"][0][0], result["bounds"][1][0])

    def test_rejects_georeferencing_that_does_not_match_footprint(self):
        item = self.item()
        item["geometry"] = {"type":"Polygon", "coordinates":[[[0,0],[.01,0],[0,.01],[0,0]]]}
        client = Mock()
        client.download_bytes.return_value = self.raster()
        with self.assertRaisesRegex(ValueError, "does not match footprint"):
            builder.export_raster(client, item)


if __name__ == "__main__":
    unittest.main()
