from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from backend.app.aircraft_review import prepare_review, record_label
from backend.app.aircraft_training import build_training_bundle


class AircraftTrainingBundleTests(unittest.TestCase):
    def _make_review(self, root: Path, item_id: str, label: str) -> Path:
        review_dir = root / item_id
        image_path = root / f"{item_id}.png"
        detections_path = root / f"{item_id}.json"
        Image.new("RGB", (256, 192), (80, 90, 100)).save(image_path)
        detections_path.write_text(
            json.dumps(
                {
                    "detector": "aircraft",
                    "model": {"name": "yolo11n-obb.pt"},
                    "input": {
                        "item_id": item_id,
                        "collection_id": "l1d-sr",
                        "bounds_wgs84": [-7.9, 12.5, -7.8, 12.6],
                    },
                    "detections": [
                        {
                            "detection_id": "aircraft_001",
                            "class_id": 0,
                            "class_name": "plane",
                            "confidence": 0.8,
                            "bbox_px": [20, 30, 70, 80],
                            "obb_px": [[20, 30], [70, 30], [70, 80], [20, 80]],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        manifest_path = prepare_review(
            image_path=image_path,
            detections_path=detections_path,
            out_dir=review_dir,
            chip_size=128,
            context_scale=2.0,
        )
        record_label(manifest_path, "cand-0001", label)
        return manifest_path

    def test_build_training_bundle_prefixes_items_by_scene_and_writes_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plane_manifest = self._make_review(root, "scene-plane", "plane")
            helicopter_manifest = self._make_review(root, "scene-helicopter", "helicopter")
            out_dir = root / "training"

            result = build_training_bundle([plane_manifest, helicopter_manifest], out_dir)

            self.assertEqual(result["counts"], {"plane": 1, "helicopter": 1, "background": 0})
            self.assertEqual(result["scene_count"], 2)
            self.assertTrue((out_dir / "data.yaml").exists())
            self.assertEqual(len(list((out_dir / "images" / "train").glob("*.png"))), 2)
            self.assertEqual(len(list((out_dir / "labels" / "train").glob("*.txt"))), 2)
            self.assertTrue(result["scene_separated"])

    def test_single_scene_bundle_is_marked_as_experimental(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = self._make_review(root, "scene-only", "plane")
            result = build_training_bundle([manifest], root / "training")
            self.assertEqual(result["scene_count"], 1)
            self.assertFalse(result["scene_separated"])
            self.assertIn("single-scene", " ".join(result["warnings"]))

    def test_explicit_validation_manifest_writes_held_out_split(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            train_manifest = self._make_review(root, "scene-train", "plane")
            validation_manifest = self._make_review(root, "scene-validation", "helicopter")
            result = build_training_bundle(
                [train_manifest],
                root / "training",
                validation_manifest_paths=[validation_manifest],
            )
            self.assertTrue(result["validation_ready"])
            self.assertEqual(result["validation_counts"]["helicopter"], 1)
            self.assertTrue((root / "training" / "images" / "val").exists())
            self.assertIn("val: images/val", (root / "training" / "data.yaml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
