#!/usr/bin/env python3
"""Evaluate one aircraft OBB model against a prepared YOLO dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate an aircraft YOLO-OBB model")
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--split", choices=("val", "train"), default="val")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out_dir = Path(args.outdir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        from ultralytics import YOLO
    except Exception as exc:
        print(
            "Ultralytics is not installed in the configured training runtime. "
            "Install backend/requirements-aircraft-training.txt on the host.",
            file=sys.stderr,
        )
        return 2
    model_path = Path(args.model).expanduser().resolve()
    data_path = Path(args.data).expanduser().resolve()
    if not model_path.is_file():
        print(f"Model not found: {model_path}", file=sys.stderr)
        return 2
    if not data_path.is_file():
        print(f"Dataset YAML not found: {data_path}", file=sys.stderr)
        return 2
    try:
        model = YOLO(str(model_path), task="obb")
        result = model.val(
            data=str(data_path),
            split=str(args.split),
            task="obb",
            device=str(args.device),
            project=str(out_dir / "runs"),
            name="evaluation",
            exist_ok=False,
            plots=True,
        )
        metrics = getattr(result, "results_dict", {}) or {}
        summary = {
            "model": str(model_path),
            "data": str(data_path),
            "split": str(args.split),
            "device": str(args.device),
            "metrics": _jsonable(metrics),
        }
        summary_path = out_dir / "evaluation_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"Aircraft evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
