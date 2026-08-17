from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from backend.app.aircraft_review import prepare_review, record_label
from backend.app.luna_aircraft import (
    LunaAircraftEvaluator,
    build_aircraft_prompt,
    build_luna_examples,
    extract_json_object,
    run_luna_evaluations,
)


class LunaAircraftTests(unittest.TestCase):
    def _manifest(self, root: Path, item_id: str, label: str | None) -> Path:
        image_path = root / f"{item_id}.png"
        detections_path = root / f"{item_id}.json"
        Image.new("RGB", (128, 128), (80, 90, 100)).save(image_path)
        detections_path.write_text(
            json.dumps(
                {
                    "detector": "aircraft",
                    "model": {"name": "yolo11n-obb.onnx"},
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
            out_dir=root / item_id,
            chip_size=96,
            context_scale=2,
        )
        if label:
            record_label(manifest_path, "cand-0001", label)
        return manifest_path

    def test_prompt_requires_reviewable_json_and_distinguishes_classes(self):
        prompt = build_aircraft_prompt(
            target={"candidate_id": "cand-0002", "proposed_class": "plane"},
            examples=[{"example_id": "scene:cand-1", "label": "helicopter", "source_item_id": "scene"}],
            model="gpt-5.6-luna",
        )
        self.assertIn("fixed-wing", prompt)
        self.assertIn("rotorcraft", prompt)
        self.assertIn('"needs_human_review":true', prompt)

    def test_extract_json_object_handles_fenced_output(self):
        self.assertEqual(extract_json_object('```json\n{"label":"plane"}\n```'), {"label": "plane"})

    def test_build_examples_uses_only_human_confirmed_labels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            confirmed = self._manifest(root, "scene-confirmed", "helicopter")
            pending = self._manifest(root, "scene-pending", None)
            result = build_luna_examples([pending, confirmed])
            self.assertEqual(result["counts"], {"background": 0, "helicopter": 1, "plane": 0})
            self.assertEqual(result["examples"][0]["label"], "helicopter")

    def test_run_evaluations_records_model_evidence_without_changing_human_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            examples_manifest = self._manifest(root, "scene-example", "helicopter")
            target_manifest = self._manifest(root, "scene-target", None)
            examples = build_luna_examples([examples_manifest])
            evaluator = LunaAircraftEvaluator(transport="api", api_key="test-key")
            with patch.object(
                evaluator,
                "_complete_api",
                return_value={"label": "plane", "confidence": 0.72, "rationale": "fixed-wing silhouette"},
            ):
                result = run_luna_evaluations(target_manifest, examples, evaluator=evaluator)
            self.assertEqual(result["complete"], 1)
            manifest = json.loads(target_manifest.read_text(encoding="utf-8"))
            self.assertEqual(manifest["candidates"][0]["label"], None)
            self.assertEqual(manifest["candidates"][0]["luna_evaluation"]["label"], "plane")
            self.assertTrue((target_manifest.parent / "luna_evaluations.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
