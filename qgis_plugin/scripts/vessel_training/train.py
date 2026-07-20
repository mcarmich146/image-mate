#!/usr/bin/env python3
"""Initialize vessel training run metadata (phase scaffold)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a local vessel training run manifest.")
    parser.add_argument("--dataset-dir", required=True, help="Path to dataset directory (expects dataset_manifest.json).")
    parser.add_argument("--runs-dir", required=True, help="Directory where run folders are written.")
    parser.add_argument("--base-weights", default="", help="Optional base weights/model path.")
    parser.add_argument("--epochs", type=int, default=100, help="Planned epochs for Ultralytics training.")
    parser.add_argument("--img-size", type=int, default=1024, help="Image size for training.")
    args = parser.parse_args()

    dataset_dir = Path(str(args.dataset_dir)).expanduser().resolve()
    runs_dir = Path(str(args.runs_dir)).expanduser().resolve()
    if not dataset_dir.exists():
        raise RuntimeError(f"Dataset directory not found: {dataset_dir}")

    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "created_utc": _utc_now(),
        "dataset_dir": str(dataset_dir),
        "base_weights": str(args.base_weights or "").strip(),
        "epochs": int(args.epochs),
        "img_size": int(args.img_size),
        "status": "initialized",
        "notes": "Training execution integration with Ultralytics will update this manifest.",
    }
    manifest_path = run_dir / "train_run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Training run initialized: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
