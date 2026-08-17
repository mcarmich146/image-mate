#!/usr/bin/env python3
"""Run local aircraft inference on one L1D-SR image tile.

Examples:
  .venv/bin/python backend/scripts/detect_aircraft.py --image tile.png --output detections.json
  .venv/bin/python backend/scripts/detect_aircraft.py --image tile.png --bounds=-122.5,37.6,-122.4,37.7
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.aircraft_detector import AircraftDetector, AircraftDetectorConfig, AircraftDetectorError
from backend.app.config import settings


def _model_path(value: str | None) -> Path:
    raw = Path(str(value or settings.aircraft_detector_model or "yolo11n-obb.onnx")).expanduser()
    if raw.is_absolute():
        return raw
    return (Path(__file__).resolve().parents[2] / raw).resolve()


def _bounds(value: str | None) -> list[float] | None:
    if not value:
        return None
    values = [float(part.strip()) for part in value.split(",")]
    if len(values) != 4:
        raise ValueError("--bounds must be minx,miny,maxx,maxy")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local aircraft detection on one high-resolution L1D-SR tile")
    parser.add_argument("--image", required=True, help="Local PNG/JPEG tile path")
    parser.add_argument("--output", help="Write normalized JSON/GeoJSON result to this path")
    parser.add_argument("--model", help="ONNX model path; defaults to IMAGE_MATE_AIRCRAFT_MODEL")
    parser.add_argument("--provider", default=None, help="auto, coreml, cuda, or cpu")
    parser.add_argument("--confidence", type=float, default=None)
    parser.add_argument("--iou", type=float, default=None)
    parser.add_argument("--max-detections", type=int, default=None)
    parser.add_argument("--bounds", help="Optional minx,miny,maxx,maxy tile bounds")
    parser.add_argument("--crs", default="EPSG:4326")
    parser.add_argument("--z", type=int)
    parser.add_argument("--x", type=int)
    parser.add_argument("--y", type=int)
    parser.add_argument("--item-id")
    parser.add_argument("--asset-key", default="visual_fullres")
    parser.add_argument("--collection-id", default="l1d-sr")
    args = parser.parse_args()

    image_path = Path(args.image).expanduser()
    if not image_path.exists() or not image_path.is_file():
        parser.error(f"image does not exist: {image_path}")
    raw = image_path.read_bytes()
    config = AircraftDetectorConfig(
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
    provenance = {
        "source_id": "satellogic",
        "collection_id": str(args.collection_id).strip().lower().replace("_", "-"),
        "item_id": args.item_id,
        "asset_key": args.asset_key,
        "bounds": _bounds(args.bounds),
        "crs": args.crs,
        "z": args.z,
        "x": args.x,
        "y": args.y,
    }
    provenance = {key: value for key, value in provenance.items() if value is not None}
    detector = AircraftDetector(config)
    try:
        result = detector.detect_bytes(raw, provenance=provenance)
    except AircraftDetectorError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    encoded = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(encoded + "\n", encoding="utf-8")
        print(output_path)
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
