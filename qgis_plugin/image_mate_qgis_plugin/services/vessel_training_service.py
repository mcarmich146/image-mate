# -*- coding: utf-8 -*-
"""Vessel QA batch training scaffold orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import subprocess
import sys


def _sanitize_component(value, *, fallback="artifact"):
    text = str(value or "").strip()
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", text).strip("._-")
    if not text:
        text = str(fallback or "artifact").strip() or "artifact"
    return text[:120]


def _safe_int(value, *, default, min_value, max_value):
    try:
        number = int(value)
    except Exception:
        number = int(default)
    number = max(int(min_value), min(int(max_value), int(number)))
    return int(number)


def _split_from_manifest(manifest):
    defaults = manifest.get("defaults") if isinstance(manifest.get("defaults"), dict) else {}
    split_payload = defaults.get("split") if isinstance(defaults.get("split"), dict) else {}
    train = _safe_int(split_payload.get("train"), default=70, min_value=1, max_value=99)
    val = _safe_int(split_payload.get("val"), default=15, min_value=1, max_value=99)
    test = _safe_int(split_payload.get("test"), default=15, min_value=1, max_value=99)
    return {"train": train, "val": val, "test": test}


@dataclass(frozen=True)
class VesselQABatchContext:
    """Resolved QA batch context for downstream training actions."""

    batch_id: str
    batch_dir: Path
    manifest_path: Path
    manifest: dict


class VesselTrainingService:
    """Resolve vessel QA batches and initialize training scaffolds."""

    def __init__(self, *, plugin_dir):
        plugin_path = Path(plugin_dir).expanduser().resolve()
        plugin_root = plugin_path.parent
        self._export_script_path = plugin_root / "scripts" / "vessel_training" / "export.py"
        self._train_script_path = plugin_root / "scripts" / "vessel_training" / "train.py"

    @staticmethod
    def _qa_exports_root(*, campaign_storage_enabled, campaign_storage, current_campaign_uid, temp_dir):
        if bool(campaign_storage_enabled) and str(current_campaign_uid or "").strip():
            return campaign_storage.campaign_vessel_ml_root(str(current_campaign_uid)) / "qa_exports"
        path = Path(temp_dir).expanduser() / "ml" / "vessel" / "qa_exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _dataset_and_runs_dirs(*, campaign_storage_enabled, campaign_storage, current_campaign_uid, temp_dir, dataset_id):
        if bool(campaign_storage_enabled) and str(current_campaign_uid or "").strip():
            dataset_dir = campaign_storage.campaign_vessel_dataset_dir(str(current_campaign_uid), str(dataset_id))
            runs_dir = campaign_storage.campaign_vessel_runs_dir(str(current_campaign_uid))
            return dataset_dir, runs_dir

        vessel_root = Path(temp_dir).expanduser() / "ml" / "vessel"
        dataset_dir = vessel_root / "datasets" / str(dataset_id)
        runs_dir = vessel_root / "runs"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        runs_dir.mkdir(parents=True, exist_ok=True)
        return dataset_dir, runs_dir

    @staticmethod
    def _load_batch_manifest(batch_dir):
        manifest_path = Path(batch_dir) / "qa_batch_manifest.json"
        if not manifest_path.exists():
            raise RuntimeError(f"QA batch manifest not found: {manifest_path}")
        try:
            parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"QA batch manifest is invalid JSON: {manifest_path}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"QA batch manifest must be a JSON object: {manifest_path}")
        return manifest_path, parsed

    @staticmethod
    def _pick_latest_batch_dir(qa_exports_root):
        root = Path(qa_exports_root)
        if not root.exists():
            return None

        rows = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            manifest_path = child / "qa_batch_manifest.json"
            if not manifest_path.exists():
                continue
            try:
                sort_key = float(manifest_path.stat().st_mtime)
            except Exception:
                sort_key = 0.0
            rows.append((sort_key, child))
        if not rows:
            return None
        rows.sort(key=lambda row: row[0], reverse=True)
        return rows[0][1]

    @staticmethod
    def _tail_summary(text):
        lines = [str(line).strip() for line in str(text or "").splitlines() if str(line).strip()]
        if not lines:
            return ""
        return " | ".join(lines[-6:])

    @staticmethod
    def _run_command(command, *, action_label):
        process = subprocess.run(command, capture_output=True, text=True)
        if int(process.returncode) != 0:
            details = VesselTrainingService._tail_summary(process.stderr) or VesselTrainingService._tail_summary(
                process.stdout
            )
            summary = details or f"exit_code={process.returncode}"
            raise RuntimeError(f"{action_label} failed: {summary}")
        return {
            "stdout": str(process.stdout or "").strip(),
            "stderr": str(process.stderr or "").strip(),
            "return_code": int(process.returncode),
        }

    @staticmethod
    def _latest_train_manifest(runs_dir):
        root = Path(runs_dir)
        rows = []
        for manifest_path in root.glob("run_*/train_run_manifest.json"):
            if not manifest_path.exists():
                continue
            try:
                sort_key = float(manifest_path.stat().st_mtime)
            except Exception:
                sort_key = 0.0
            rows.append((sort_key, manifest_path))
        if not rows:
            raise RuntimeError(f"No training run manifest found under: {root}")
        rows.sort(key=lambda row: row[0], reverse=True)
        return rows[0][1]

    @staticmethod
    def _resolve_batch_dir(
        *,
        qa_exports_root,
        batch_id,
        preferred_batch_dir="",
    ):
        preferred = str(preferred_batch_dir or "").strip()
        if preferred:
            preferred_path = Path(preferred).expanduser()
            if (preferred_path / "qa_batch_manifest.json").exists():
                return preferred_path

        requested_batch = str(batch_id or "").strip()
        if requested_batch:
            batch_key = _sanitize_component(requested_batch, fallback="qa_batch")
            candidate = Path(qa_exports_root) / batch_key
            if (candidate / "qa_batch_manifest.json").exists():
                return candidate
            raise RuntimeError(f"Requested QA batch folder was not found: {candidate}")

        latest = VesselTrainingService._pick_latest_batch_dir(qa_exports_root)
        if latest is None:
            raise RuntimeError(
                "No finalized QA batch folder was found. Finalize a Vessel QA batch before this action."
            )
        return latest

    def resolve_batch_context(
        self,
        *,
        campaign_storage_enabled,
        campaign_storage,
        current_campaign_uid,
        temp_dir,
        batch_id="",
        preferred_batch_dir="",
    ):
        qa_exports_root = self._qa_exports_root(
            campaign_storage_enabled=campaign_storage_enabled,
            campaign_storage=campaign_storage,
            current_campaign_uid=current_campaign_uid,
            temp_dir=temp_dir,
        )
        batch_dir = self._resolve_batch_dir(
            qa_exports_root=qa_exports_root,
            batch_id=batch_id,
            preferred_batch_dir=preferred_batch_dir,
        )
        manifest_path, manifest = self._load_batch_manifest(batch_dir)
        resolved_batch_id = str(manifest.get("batch_id") or batch_dir.name).strip() or str(batch_dir.name)
        return VesselQABatchContext(
            batch_id=resolved_batch_id,
            batch_dir=Path(batch_dir).resolve(),
            manifest_path=Path(manifest_path).resolve(),
            manifest=manifest,
        )

    def initialize_model_update_from_batch(
        self,
        *,
        campaign_storage_enabled,
        campaign_storage,
        current_campaign_uid,
        temp_dir,
        request=None,
        preferred_batch_dir="",
    ):
        request_payload = request if isinstance(request, dict) else {}
        batch_id = str(request_payload.get("batch_id") or "").strip()
        batch_context = self.resolve_batch_context(
            campaign_storage_enabled=campaign_storage_enabled,
            campaign_storage=campaign_storage,
            current_campaign_uid=current_campaign_uid,
            temp_dir=temp_dir,
            batch_id=batch_id,
            preferred_batch_dir=preferred_batch_dir,
        )

        counts = batch_context.manifest.get("counts") if isinstance(batch_context.manifest.get("counts"), dict) else {}
        approved_count = _safe_int(counts.get("approved"), default=0, min_value=0, max_value=1_000_000)
        if approved_count <= 0:
            raise RuntimeError(
                "QA batch has zero approved records. Mark and finalize approved labels before model update."
            )

        dataset_id_input = str(request_payload.get("dataset_id") or "").strip()
        if dataset_id_input:
            dataset_id = _sanitize_component(dataset_id_input, fallback="dataset")
        else:
            dataset_id = _sanitize_component(f"dataset_{batch_context.batch_id}", fallback="dataset")

        dataset_dir, runs_dir = self._dataset_and_runs_dirs(
            campaign_storage_enabled=campaign_storage_enabled,
            campaign_storage=campaign_storage,
            current_campaign_uid=current_campaign_uid,
            temp_dir=temp_dir,
            dataset_id=dataset_id,
        )

        defaults = (
            batch_context.manifest.get("defaults")
            if isinstance(batch_context.manifest.get("defaults"), dict)
            else {}
        )
        chip_size = _safe_int(defaults.get("chip_size"), default=1024, min_value=64, max_value=16384)
        padding = _safe_int(defaults.get("padding"), default=128, min_value=0, max_value=4096)
        split = _split_from_manifest(batch_context.manifest)

        python_bin = str(request_payload.get("python_executable") or "").strip() or str(sys.executable)
        if not python_bin:
            python_bin = "python"

        epochs = _safe_int(request_payload.get("epochs"), default=100, min_value=1, max_value=10000)
        image_size = _safe_int(request_payload.get("image_size"), default=1024, min_value=128, max_value=4096)
        base_weights = str(request_payload.get("base_weights") or "").strip()

        if not self._export_script_path.exists():
            raise RuntimeError(f"Dataset export script not found: {self._export_script_path}")
        if not self._train_script_path.exists():
            raise RuntimeError(f"Training scaffold script not found: {self._train_script_path}")

        split_value = f"{split['train']},{split['val']},{split['test']}"
        export_cmd = [
            python_bin,
            str(self._export_script_path),
            "--output-dir",
            str(dataset_dir),
            "--dataset-id",
            str(dataset_id),
            "--chip-size",
            str(chip_size),
            "--padding",
            str(padding),
            "--split",
            split_value,
            "--source-manifest",
            str(batch_context.manifest_path),
        ]
        export_result = self._run_command(export_cmd, action_label="Vessel dataset export scaffold")

        train_cmd = [
            python_bin,
            str(self._train_script_path),
            "--dataset-dir",
            str(dataset_dir),
            "--runs-dir",
            str(runs_dir),
            "--epochs",
            str(epochs),
            "--img-size",
            str(image_size),
        ]
        if base_weights:
            train_cmd.extend(["--base-weights", str(base_weights)])
        train_result = self._run_command(train_cmd, action_label="Vessel training run scaffold")

        dataset_manifest_path = Path(dataset_dir) / "dataset_manifest.json"
        if not dataset_manifest_path.exists():
            raise RuntimeError(f"Dataset manifest was not generated: {dataset_manifest_path}")
        train_run_manifest_path = self._latest_train_manifest(runs_dir)

        return {
            "batch_id": str(batch_context.batch_id),
            "batch_dir": str(batch_context.batch_dir),
            "batch_manifest_path": str(batch_context.manifest_path),
            "dataset_id": str(dataset_id),
            "dataset_dir": str(Path(dataset_dir).resolve()),
            "dataset_manifest_path": str(dataset_manifest_path.resolve()),
            "runs_dir": str(Path(runs_dir).resolve()),
            "train_run_manifest_path": str(train_run_manifest_path.resolve()),
            "approved_count": int(approved_count),
            "created_utc": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
            "export_result": export_result,
            "train_result": train_result,
        }
