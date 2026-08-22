from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from backend.app import main
from backend.app.aircraft_training_jobs import AircraftTrainingJobStore, run_job_command
from backend.app.models import (
    AircraftDatasetBuildRequest,
    AircraftEvaluationJobRequest,
    AircraftLabAnnotationRequest,
    AircraftTrainingJobRequest,
)


class AircraftLabWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.previous_lab_dir = main.settings.aircraft_lab_dir
        self.previous_training_dir = main.settings.aircraft_training_dir
        self.previous_training_python = main.settings.aircraft_training_python
        main.settings.aircraft_lab_dir = root / "lab"
        main.settings.aircraft_training_dir = root / "training"
        main.settings.aircraft_training_python = "python"
        main.app.state.aircraft_training_jobs = None

        image = Image.new("RGB", (256, 256), (80, 90, 100))
        handle = BytesIO()
        image.save(handle, format="PNG")
        self.tile_bytes = handle.getvalue()

    def tearDown(self):
        main.settings.aircraft_lab_dir = self.previous_lab_dir
        main.settings.aircraft_training_dir = self.previous_training_dir
        main.settings.aircraft_training_python = self.previous_training_python
        main.app.state.aircraft_training_jobs = None
        self.temp_dir.cleanup()

    def _request(self, item_id: str, label: str, *, detection_id: str | None = None):
        return AircraftLabAnnotationRequest(
            item_id=item_id,
            source_id="satellogic",
            collection_id="l1d-sr",
            asset_key="visual",
            z=17,
            x=10,
            y=20,
            scale=4,
            contract_id="contract-test",
            bounds_wgs84=[-7.9, 12.5, -7.8, 12.6],
            source_width_px=256,
            source_height_px=256,
            geometry_px=[[40, 40], [100, 40], [100, 100], [40, 100]],
            label=label,
            detection_id=detection_id,
            confidence=0.8,
        )

    def test_annotations_materialize_and_build_scene_separated_bundle(self):
        with patch.object(main, "_decode_aircraft_image", return_value=(self.tile_bytes, {})):
            main.create_aircraft_lab_annotation(self._request("scene-train", "plane", detection_id="det-1"))
            main.create_aircraft_lab_annotation(self._request("scene-validation", "helicopter", detection_id="det-2"))

        rows = main._read_aircraft_lab_annotations()
        self.assertEqual(len(rows), 2)
        self.assertTrue(Path(rows[0]["source_image_path"]).is_file())
        preview = main.aircraft_lab_dataset_preview()
        self.assertEqual({row["item_id"] for row in preview["scenes"]}, {"scene-train", "scene-validation"})

        response = main.build_aircraft_lab_dataset(
            AircraftDatasetBuildRequest(
                name="ui-test",
                train_item_ids=["scene-train"],
                validation_item_ids=["scene-validation"],
            )
        )
        dataset = response["dataset"]
        self.assertTrue(dataset["validation_ready"])
        self.assertEqual(dataset["counts"]["plane"], 1)
        self.assertEqual(dataset["validation_counts"]["helicopter"], 1)
        self.assertTrue(Path(dataset["data_yaml"]).is_file())
        self.assertEqual(len(dataset["manifests"]), 1)
        self.assertEqual(len(dataset["validation_manifests"]), 1)

    def test_same_detection_is_upserted_for_relabeling(self):
        with patch.object(main, "_decode_aircraft_image", return_value=(self.tile_bytes, {})):
            first = main.create_aircraft_lab_annotation(self._request("scene-one", "plane", detection_id="det-1"))
            second = main.create_aircraft_lab_annotation(self._request("scene-one", "helicopter", detection_id="det-1"))
        self.assertNotEqual(first["annotation_id"], second["annotation_id"])
        rows = main._read_aircraft_lab_annotations()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "helicopter")

    def test_training_and_evaluation_commands_are_wired_to_dataset(self):
        with patch.object(main, "_decode_aircraft_image", return_value=(self.tile_bytes, {})):
            main.create_aircraft_lab_annotation(self._request("scene-train", "plane", detection_id="det-1"))
            main.create_aircraft_lab_annotation(self._request("scene-validation", "helicopter", detection_id="det-2"))
        dataset = main.build_aircraft_lab_dataset(
            AircraftDatasetBuildRequest(
                name="commands",
                train_item_ids=["scene-train"],
                validation_item_ids=["scene-validation"],
            )
        )["dataset"]

        with patch.object(main, "_start_aircraft_host_job", return_value={"job_id": "train-test"}) as start_job:
            result = main.start_aircraft_training(
                AircraftTrainingJobRequest(dataset_id=dataset["id"], device="cpu")
            )
        self.assertEqual(result["job_id"], "train-test")
        command = start_job.call_args.kwargs["command"]
        self.assertIn("--validation-manifest", command)
        self.assertIn("--export-onnx", command)

        with patch.object(main, "_start_aircraft_host_job", return_value={"job_id": "eval-test"}) as start_job:
            result = main.start_aircraft_evaluation(
                AircraftEvaluationJobRequest(dataset_id=dataset["id"], model_id="configured", device="cpu")
            )
        self.assertEqual(result["job_id"], "eval-test")
        command = start_job.call_args.kwargs["command"]
        self.assertIn("evaluate_aircraft.py", command[1])
        self.assertIn("--split", command)

    def test_job_store_persists_successful_host_command(self):
        store = AircraftTrainingJobStore(Path(self.temp_dir.name) / "jobs")
        output_dir = Path(self.temp_dir.name) / "job-output"
        job = store.create(kind="test", payload={}, output_dir=output_dir)
        run_job_command(
            store,
            job["job_id"],
            [sys.executable, "-c", "print('aircraft job ok')"],
            cwd=Path(self.temp_dir.name),
            summary_path=output_dir / "summary.json",
        )
        persisted = store.get(job["job_id"])
        self.assertEqual(persisted["status"], "succeeded")
        self.assertIn("aircraft job ok", persisted["logs"])


if __name__ == "__main__":
    unittest.main()
