import json
from pathlib import Path
import unittest

import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from scripts import build_data_center_animations as animations


class DataCenterAnimationTests(unittest.TestCase):
    @staticmethod
    def cloud_raster(values):
        with MemoryFile() as mem:
            with mem.open(
                driver="GTiff",
                width=4,
                height=4,
                count=1,
                dtype="uint8",
                nodata=0,
                crs="EPSG:3857",
                transform=from_origin(0, 4, 1, 1),
            ) as dataset:
                dataset.write(np.asarray(values, dtype=np.uint8), 1)
            return mem.read()

    @staticmethod
    def grid():
        aoi = np.zeros((4, 4), dtype=bool)
        aoi[1:3, 1:3] = True
        return {
            "height": 4,
            "width": 4,
            "transform": from_origin(0, 4, 1, 1),
            "crs": "EPSG:3857",
            "aoi_mask": aoi,
            "aoi_pixels": int(aoi.sum()),
        }

    def test_scene_cloud_outside_focus_does_not_reject(self):
        values = np.ones((4, 4), dtype=np.uint8)
        values[0, 0] = 3  # cloud, but outside the focus
        item = {"id": "item-1", "_cloud_href": "cloud://item-1"}
        _, quality = animations._cloud_mask_precheck(
            [item], self.grid(), lambda href: self.cloud_raster(values)
        )
        self.assertEqual(quality["cloud_mask_decision"], "keep")
        self.assertEqual(quality["haze_fraction_over_focus"], 0.0)

    def test_target_grid_is_a_2000_metre_square_centered_on_pin(self):
        grid = animations._target_grid(
            {
                "center": [-100.0, 32.0],
                "geometry": {"type": "Polygon", "coordinates": []},
            }
        )
        self.assertEqual(grid["width"], 4000)
        self.assertEqual(grid["width"], grid["height"])
        self.assertAlmostEqual(grid["focus_size_m"], 2000.0)
        self.assertAlmostEqual(grid["focus_bounds_m"][2] - grid["focus_bounds_m"][0], 2000.0)
        self.assertAlmostEqual(grid["focus_bounds_m"][3] - grid["focus_bounds_m"][1], 2000.0)
        self.assertEqual(grid["focus_center"], [-100.0, 32.0])

    def test_haze_over_focus_is_allowed(self):
        values = np.ones((4, 4), dtype=np.uint8)
        values[1, 1] = 2
        item = {"id": "item-1", "_cloud_href": "cloud://item-1"}
        _, quality = animations._cloud_mask_precheck(
            [item], self.grid(), lambda href: self.cloud_raster(values)
        )
        self.assertEqual(quality["cloud_mask_decision"], "keep")
        self.assertEqual(quality["cloud_mask_decision_reason"], "haze_allowed_over_focus")
        self.assertGreater(quality["haze_fraction_over_focus"], 0.0)

    def test_cloud_over_focus_rejects(self):
        values = np.ones((4, 4), dtype=np.uint8)
        values[1, 1] = 3
        item = {"id": "item-1", "_cloud_href": "cloud://item-1"}
        _, quality = animations._cloud_mask_precheck(
            [item], self.grid(), lambda href: self.cloud_raster(values)
        )
        self.assertEqual(quality["cloud_mask_decision"], "reject")
        self.assertEqual(quality["cloud_mask_decision_reason"], "cloud_over_focus")
        self.assertGreater(quality["cloud_fraction_over_focus"], 0.0)

    def test_tasking_preview_is_not_a_submission(self):
        site = {
            "id": "site-1",
            "name": "Example site",
            "label": "Example",
            "center": [-100.0, 32.0],
            "note": "Research rectangle; not a verified property boundary.",
        }
        result = {"latest_capture_datetime": "2026-01-01T00:00:00+00:00"}
        preview = animations._tasking_preview(site, result)
        self.assertIsNotNone(preview)
        self.assertEqual(preview["properties"]["proposed_revisit_period"], "P7D")
        self.assertEqual(preview["properties"]["proposed_processing_level"], "L1D_SR")
        self.assertNotIn("order_id", preview["properties"])

    def test_refreshed_artifacts_have_expected_sequence_and_preview_state(self):
        root = Path(animations.ROOT) / "docs/research/data-center-map"
        index = json.loads((root / "animations/index.json").read_text())
        ready = [row for row in index["site_results"].values() if row.get("status") == "ready"]
        self.assertEqual(len(ready), 1)
        self.assertEqual({row["frame_count"] for row in ready}, {4})
        self.assertTrue(all(tuple(row["output_size"]) == (4000, 4000) for row in ready))
        preview = json.loads(
            (Path(animations.ROOT) / "docs/research/data-center-tasking-previews-2026-09-10.geojson").read_text()
        )
        self.assertEqual(len(preview["features"]), 12)
        self.assertIn(
            "blocked_unverified_location",
            {feature["properties"]["status"] for feature in preview["features"]},
        )
        self.assertEqual(
            sum(feature["properties"]["status"] == "blocked_unverified_location" for feature in preview["features"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
