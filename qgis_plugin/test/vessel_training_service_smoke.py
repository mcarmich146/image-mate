#!/usr/bin/env python3
"""Smoke checks for vessel QA batch training scaffold orchestration."""

from __future__ import annotations

from pathlib import Path
import json
import os
import sys
import tempfile


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_true(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)


def _write_batch_manifest(batch_dir: Path, *, batch_id: str, approved: int) -> Path:
    batch_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = batch_dir / "qa_batch_manifest.json"
    payload = {
        "schema_version": 1,
        "batch_id": str(batch_id),
        "dataset_id": "",
        "created_utc": "2026-02-27T00:00:00+00:00",
        "counts": {
            "total": int(approved),
            "approved": int(approved),
            "rejected": 0,
            "pending": 0,
        },
        "defaults": {
            "chip_size": 1024,
            "padding": 128,
            "split": {"train": 70, "val": 15, "test": 15},
        },
        "files": {},
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.campaign_storage_service import CampaignStorageService  # noqa: PLC0415
    from image_mate_qgis_plugin.services.vessel_training_service import VesselTrainingService  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="image_mate_vessel_train_smoke_") as tmp_dir_value:
        temp_root = Path(tmp_dir_value).resolve()
        temp_dir = temp_root / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        campaign_storage = CampaignStorageService(
            base_dir=str(temp_root / "campaign_base"),
            managed_storage_enabled=False,
        )
        service = VesselTrainingService(plugin_dir=plugin_root / "image_mate_qgis_plugin")

        qa_root = temp_dir / "ml" / "vessel" / "qa_exports"
        old_batch_dir = qa_root / "qa_batch_old"
        new_batch_dir = qa_root / "qa_batch_new"
        zero_batch_dir = qa_root / "qa_batch_zero"
        old_manifest = _write_batch_manifest(old_batch_dir, batch_id="qa_batch_old", approved=2)
        new_manifest = _write_batch_manifest(new_batch_dir, batch_id="qa_batch_new", approved=3)
        zero_manifest = _write_batch_manifest(zero_batch_dir, batch_id="qa_batch_zero", approved=0)

        os.utime(str(old_manifest), (1_000_000_000, 1_000_000_000))
        os.utime(str(new_manifest), (1_100_000_000, 1_100_000_000))
        os.utime(str(zero_manifest), (900_000_000, 900_000_000))

        latest_context = service.resolve_batch_context(
            campaign_storage_enabled=False,
            campaign_storage=campaign_storage,
            current_campaign_uid="",
            temp_dir=temp_dir,
        )
        _assert_true(latest_context.batch_id == "qa_batch_new", "latest batch resolution failed")

        preferred_context = service.resolve_batch_context(
            campaign_storage_enabled=False,
            campaign_storage=campaign_storage,
            current_campaign_uid="",
            temp_dir=temp_dir,
            preferred_batch_dir=str(old_batch_dir),
        )
        _assert_true(preferred_context.batch_id == "qa_batch_old", "preferred batch resolution failed")

        try:
            service.initialize_model_update_from_batch(
                campaign_storage_enabled=False,
                campaign_storage=campaign_storage,
                current_campaign_uid="",
                temp_dir=temp_dir,
                request={"batch_id": "qa_batch_zero"},
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError for zero-approved QA batch")

        result = service.initialize_model_update_from_batch(
            campaign_storage_enabled=False,
            campaign_storage=campaign_storage,
            current_campaign_uid="",
            temp_dir=temp_dir,
            request={
                "batch_id": "qa_batch_new",
                "dataset_id": "demo_dataset",
                "epochs": 5,
                "image_size": 640,
            },
        )

        dataset_manifest_path = Path(str(result.get("dataset_manifest_path") or ""))
        train_manifest_path = Path(str(result.get("train_run_manifest_path") or ""))
        _assert_true(dataset_manifest_path.exists(), "dataset manifest was not created")
        _assert_true(train_manifest_path.exists(), "train run manifest was not created")

        dataset_manifest = json.loads(dataset_manifest_path.read_text(encoding="utf-8"))
        _assert_true(dataset_manifest.get("dataset_id") == "demo_dataset", "dataset id mismatch")
        _assert_true(
            dataset_manifest.get("source_manifest") == str(new_manifest.resolve()),
            "dataset source manifest mismatch",
        )

        train_manifest = json.loads(train_manifest_path.read_text(encoding="utf-8"))
        _assert_true(train_manifest.get("epochs") == 5, "epochs mismatch")
        _assert_true(train_manifest.get("img_size") == 640, "image size mismatch")
        _assert_true(str(train_manifest.get("dataset_dir") or "").endswith("demo_dataset"), "dataset dir mismatch")

    print("vessel_training_service_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
