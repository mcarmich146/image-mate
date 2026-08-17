#!/usr/bin/env python3
"""Run the local aircraft detector over a directory of L1D-SR tiles.

Each input tile must have a same-stem JSON sidecar containing at least
``item_id`` and ``bounds_wgs84``.  Keeping provenance beside the image prevents
batch outputs from becoming an untraceable pile of detector JSON files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.aircraft_detector import AircraftDetector, AircraftDetectorConfig, AircraftDetectorError  # noqa: E402
from backend.app.config import settings  # noqa: E402


def _model_path(value: str | None) -> Path:
    raw = Path(str(value or settings.aircraft_detector_model or "yolo11n-obb.onnx")).expanduser()
    return raw if raw.is_absolute() else (PROJECT_ROOT / raw).resolve()


def _metadata(path: Path) -> dict:
    sidecar = path.with_suffix(".json")
    if not sidecar.is_file():
        raise ValueError(f"Missing L1D-SR provenance sidecar: {sidecar}")
    value = json.loads(sidecar.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Sidecar must be a JSON object: {sidecar}")
    collection = str(value.get("collection_id") or "l1d-sr").strip().lower().replace("_", "-")
    if collection != "l1d-sr":
        raise ValueError(f"Batch aircraft detection accepts only l1d-sr sidecars: {sidecar}")
    item_id = str(value.get("item_id") or "").strip()
    bounds = value.get("bounds_wgs84")
    if not item_id or not isinstance(bounds, list) or len(bounds) != 4:
        raise ValueError(f"Sidecar requires item_id and bounds_wgs84: {sidecar}")
    return {"item_id": item_id, "collection_id": collection, "bounds": bounds, "crs": "EPSG:4326", "asset_key": "visual"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local aircraft detection over a directory of L1D-SR tiles")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--glob", default="*.png", help="Input glob, e.g. '*.png' or '*.jpg'")
    parser.add_argument("--model")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--confidence", type=float, default=None)
    parser.add_argument("--iou", type=float, default=None)
    parser.add_argument("--max-detections", type=int, default=None)
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()
    if not input_dir.is_dir():
        parser.error(f"input directory does not exist: {input_dir}")
    outdir.mkdir(parents=True, exist_ok=True)
    images = sorted(path for path in input_dir.glob(args.glob) if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"})
    if not images:
        parser.error(f"no image tiles matched {args.glob!r} in {input_dir}")
    detector = AircraftDetector(
        AircraftDetectorConfig(
            model_path=_model_path(args.model),
            provider_mode=str(args.provider or settings.aircraft_detector_provider or "auto"),
            confidence=float(args.confidence if args.confidence is not None else settings.aircraft_detector_confidence),
            iou=float(args.iou if args.iou is not None else settings.aircraft_detector_iou),
            max_detections=int(args.max_detections if args.max_detections is not None else settings.aircraft_detector_max_detections),
            window_size_px=int(settings.aircraft_detector_window_px),
            window_overlap=float(settings.aircraft_detector_window_overlap),
            max_image_bytes=int(settings.aircraft_detector_max_image_bytes),
            max_image_pixels=int(settings.aircraft_detector_max_image_pixels),
        )
    )
    outputs: list[dict] = []
    for image_path in images:
        try:
            provenance = _metadata(image_path)
            result = detector.detect_bytes(image_path.read_bytes(), provenance=provenance)
            output_path = outdir / f"{image_path.stem}.json"
            output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            outputs.append({"image": str(image_path), "detections": len(result.get("detections", [])), "output": str(output_path), "status": "complete"})
        except (OSError, ValueError, json.JSONDecodeError, AircraftDetectorError) as exc:
            outputs.append({"image": str(image_path), "status": "error", "error": str(exc)[:400]})
    summary = {"schema_version": "aircraft-batch-detection.v1", "input_dir": str(input_dir), "outdir": str(outdir), "items": outputs}
    (outdir / "batch_manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(outdir / "batch_manifest.json"), "images": len(images), "complete": sum(row["status"] == "complete" for row in outputs), "errors": sum(row["status"] == "error" for row in outputs)}, indent=2))
    return 0 if all(row["status"] == "complete" for row in outputs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
