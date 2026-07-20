#!/usr/bin/env python3
"""Initialize vessel dataset export structure (phase scaffold)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_split(value: str) -> tuple[int, int, int]:
    text = str(value or "").strip() or "70,15,15"
    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 3:
        raise ValueError("split must have three comma-separated integers, e.g. 70,15,15")
    nums = [int(p) for p in parts]
    if any(n <= 0 for n in nums):
        raise ValueError("split values must be > 0")
    return nums[0], nums[1], nums[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize YOLO OBB dataset export directories for vessel training.")
    parser.add_argument("--output-dir", required=True, help="Dataset output directory.")
    parser.add_argument("--dataset-id", default="", help="Optional dataset identifier.")
    parser.add_argument("--chip-size", type=int, default=1024, help="Chip size in pixels (default 1024).")
    parser.add_argument("--padding", type=int, default=128, help="Context padding in pixels (default 128).")
    parser.add_argument("--split", default="70,15,15", help="Train/val/test split ratios.")
    parser.add_argument("--source-manifest", default="", help="Optional QA source manifest path for traceability.")
    args = parser.parse_args()

    train_pct, val_pct, test_pct = _parse_split(args.split)
    output_dir = Path(str(args.output_dir)).expanduser().resolve()
    dataset_id = str(args.dataset_id or "").strip() or datetime.now(timezone.utc).strftime("dataset_%Y%m%dT%H%M%SZ")

    for split_name in ("train", "val", "test"):
        (output_dir / "images" / split_name).mkdir(parents=True, exist_ok=True)
        (output_dir / "labels" / split_name).mkdir(parents=True, exist_ok=True)

    metadata = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "created_utc": _utc_now(),
        "chip_size": int(args.chip_size),
        "padding": int(args.padding),
        "split": {"train": train_pct, "val": val_pct, "test": test_pct},
        "source_manifest": str(args.source_manifest or "").strip(),
        "status": "initialized",
        "notes": "Dataset scaffold initialized. Populate images/labels with approved QA export.",
    }
    manifest_path = output_dir / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Dataset scaffold initialized: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
