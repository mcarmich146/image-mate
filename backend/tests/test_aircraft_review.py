from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from backend.app.aircraft_review import (
    LABELS,
    compute_chip_geometry,
    dedupe_proposals,
    export_labelled_dataset,
    generate_grid_chips,
    prepare_review,
    record_label,
)


class AircraftReviewUnitTests(unittest.TestCase):
    def test_cross_class_duplicate_becomes_one_candidate_with_alternatives(self):
        rows = [
            {
                "detection_id": "aircraft_001",
                "class_name": "plane",
                "class_id": 0,
                "confidence": 0.41,
                "bbox_px": [100, 100, 180, 180],
                "obb_px": [[100, 100], [180, 100], [180, 180], [100, 180]],
            },
            {
                "detection_id": "aircraft_002",
                "class_name": "helicopter",
                "class_id": 11,
                "confidence": 0.39,
                "bbox_px": [101, 101, 179, 179],
                "obb_px": [[101, 101], [179, 101], [179, 179], [101, 179]],
            },
            {
                "detection_id": "aircraft_003",
                "class_name": "plane",
                "class_id": 0,
                "confidence": 0.80,
                "bbox_px": [300, 300, 360, 360],
                "obb_px": [[300, 300], [360, 300], [360, 360], [300, 360]],
            },
        ]

        candidates = dedupe_proposals(rows, min_confidence=0.05, iou_threshold=0.45)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_detection_ids"], ["aircraft_003"])
        merged = next(candidate for candidate in candidates if len(candidate["source_detection_ids"]) == 2)
        self.assertEqual(merged["proposed_class"], "plane")
        self.assertEqual(
            [(item["class_name"], item["confidence"]) for item in merged["alternative_proposals"]],
            [("plane", 0.41), ("helicopter", 0.39)],
        )

    def test_compute_chip_geometry_is_fixed_square_and_records_padding(self):
        geometry = compute_chip_geometry(
            [5, 10, 45, 70],
            image_width=100,
            image_height=80,
            chip_size=128,
            context_scale=2.0,
        )

        self.assertEqual(geometry["chip_size_px"], 128)
        self.assertEqual(geometry["source_crop_box_px"], [0, 0, 89, 80])
        self.assertEqual(geometry["paste_offset_px"], [39, 24])
        self.assertEqual(geometry["center_px"], [25.0, 40.0])

    def test_prepare_review_writes_clean_chips_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "tile.png"
            detections_path = root / "detections.json"
            out_dir = root / "review"
            Image.new("RGB", (256, 192), (90, 100, 110)).save(image_path)
            detections_path.write_text(
                json.dumps(
                    {
                        "detector": "aircraft",
                        "model": {"name": "test.onnx"},
                        "input": {
                            "item_id": "scene-1",
                            "collection_id": "l1d-sr",
                            "bounds_wgs84": [-7.9, 12.5, -7.8, 12.6],
                        },
                        "detections": [
                            {
                                "detection_id": "aircraft_001",
                                "class_id": 0,
                                "class_name": "plane",
                                "confidence": 0.12,
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
                out_dir=out_dir,
                min_confidence=0.05,
                chip_size=128,
                iou_threshold=0.45,
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "aircraft-review.v1")
            self.assertEqual(len(manifest["candidates"]), 1)
            chip_path = out_dir / manifest["candidates"][0]["chip_path"]
            review_chip_path = out_dir / manifest["candidates"][0]["review_chip_path"]
            self.assertTrue(chip_path.exists())
            self.assertTrue(review_chip_path.exists())
            self.assertEqual(Image.open(chip_path).size, (128, 128))
            self.assertEqual(Image.open(review_chip_path).size, (128, 128))
            self.assertEqual(manifest["candidates"][0]["label"], None)
            self.assertEqual(manifest["source"]["collection_id"], "l1d-sr")
            self.assertEqual(manifest["source"]["bounds_wgs84"], [-7.9, 12.5, -7.8, 12.6])

    def test_prepare_review_rejects_non_l1d_sr_or_missing_georeferencing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "tile.png"
            detections_path = root / "detections.json"
            Image.new("RGB", (128, 128), (1, 2, 3)).save(image_path)
            base = {
                "detector": "aircraft",
                "model": {"name": "test.onnx"},
                "input": {
                    "item_id": "scene-1",
                    "collection_id": "quickview-visual",
                    "bounds_wgs84": [-7.9, 12.5, -7.8, 12.6],
                },
                "detections": [],
            }
            detections_path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare_review(image_path=image_path, detections_path=detections_path, out_dir=root / "bad")

            base["input"]["collection_id"] = "l1d-sr"
            base["input"]["bounds_wgs84"] = None
            detections_path.write_text(json.dumps(base), encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare_review(image_path=image_path, detections_path=detections_path, out_dir=root / "bad2")

    def test_record_label_accepts_only_known_labels_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "aircraft-review.v1",
                        "labels_path": "labels.jsonl",
                        "candidates": [{"candidate_id": "cand-0001", "label": None}],
                    }
                ),
                encoding="utf-8",
            )

            record_label(manifest_path, "cand-0001", "plane")
            record_label(manifest_path, "cand-0001", "plane")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["candidates"][0]["label"], "plane")
            self.assertEqual(len((root / "labels.jsonl").read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(set(LABELS), {"plane", "helicopter", "background", "skip"})
            with self.assertRaises(ValueError):
                record_label(manifest_path, "cand-0001", "unknown")
            with self.assertRaises(ValueError):
                record_label(manifest_path, "cand-0001", "helicopter")

    def test_export_labelled_dataset_preserves_boxes_and_hard_negatives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "tile.png"
            detections_path = root / "detections.json"
            review_dir = root / "review"
            export_dir = root / "export"
            Image.new("RGB", (256, 192), (90, 100, 110)).save(image_path)
            detections_path.write_text(
                json.dumps(
                    {
                        "detector": "aircraft",
                        "model": {"name": "test.onnx"},
                        "input": {
                            "item_id": "scene-1",
                            "collection_id": "l1d-sr",
                            "bounds_wgs84": [-7.9, 12.5, -7.8, 12.6],
                        },
                        "detections": [
                            {
                                "detection_id": "aircraft_001",
                                "class_id": 0,
                                "class_name": "plane",
                                "confidence": 0.9,
                                "bbox_px": [20, 30, 70, 80],
                                "obb_px": [[20, 30], [70, 30], [70, 80], [20, 80]],
                            },
                            {
                                "detection_id": "aircraft_002",
                                "class_id": 0,
                                "class_name": "plane",
                                "confidence": 0.8,
                                "bbox_px": [150, 100, 190, 140],
                                "obb_px": [[150, 100], [190, 100], [190, 140], [150, 140]],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = prepare_review(
                image_path=image_path,
                detections_path=detections_path,
                out_dir=review_dir,
                min_confidence=0.05,
                chip_size=128,
                context_scale=2.0,
            )
            record_label(manifest_path, "cand-0001", "plane")
            record_label(manifest_path, "cand-0002", "background")

            export_manifest_path = export_labelled_dataset(manifest_path, export_dir, split="train")
            export_manifest = json.loads(export_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(export_manifest["classes"], {"0": "plane", "1": "helicopter"})
            self.assertEqual(export_manifest["counts"], {"plane": 1, "helicopter": 0, "background": 1, "skip": 0})
            positive_label = export_dir / "yolo" / "labels" / "train" / "cand-0001.txt"
            negative_label = export_dir / "yolo" / "labels" / "train" / "cand-0002.txt"
            self.assertTrue((export_dir / "yolo" / "images" / "train" / "cand-0001.png").exists())
            self.assertTrue((export_dir / "classifier" / "plane" / "cand-0001.png").exists())
            self.assertTrue((export_dir / "classifier" / "background" / "cand-0002.png").exists())
            self.assertTrue(positive_label.read_text(encoding="utf-8").startswith("0 "))
            self.assertEqual(negative_label.read_text(encoding="utf-8"), "")

    def test_generate_grid_chips_has_overlap_and_discovery_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "tile.png"
            out_dir = root / "grid"
            Image.new("RGB", (300, 220), (10, 20, 30)).save(image_path)

            manifest_path = generate_grid_chips(
                image_path=image_path,
                out_dir=out_dir,
                chip_size=128,
                stride=96,
                item_id="scene-1",
                bounds_wgs84=[-7.9, 12.5, -7.8, 12.6],
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "aircraft-grid-review.v1")
            self.assertGreater(len(manifest["cells"]), 4)
            self.assertTrue(any(cell["x_px"] == 96 for cell in manifest["cells"]))
            self.assertTrue((out_dir / manifest["cells"][0]["chip_path"]).exists())
            self.assertEqual(manifest["purpose"], "missed-object-discovery")
            self.assertEqual(manifest["source"]["collection_id"], "l1d-sr")


if __name__ == "__main__":
    unittest.main()
