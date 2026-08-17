"""Human-in-the-loop review helpers for local aircraft detection.

This module intentionally has no Telegram or provider dependencies.  The Hermes
skill/CLI can send the generated chip paths and record replies while this module
keeps a reproducible manifest and append-only label history.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable

from PIL import Image, ImageDraw


LABELS = ("plane", "helicopter", "background", "skip")
_LABEL_ALIASES = {
    "1": "plane",
    "plane": "plane",
    "aircraft": "plane",
    "fixed-wing": "plane",
    "fixed_wing": "plane",
    "2": "helicopter",
    "helicopter": "helicopter",
    "helo": "helicopter",
    "3": "background",
    "background": "background",
    "none": "background",
    "no": "background",
    "no-detection": "background",
    "no_detection": "background",
    "0": "skip",
    "skip": "skip",
    "unsure": "skip",
}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _bbox(row: dict[str, Any]) -> list[float] | None:
    value = row.get("bbox_px")
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    result = [_float(item) for item in value[:4]]
    if result[2] <= result[0] or result[3] <= result[1]:
        return None
    return result


def bbox_iou(left: Iterable[float], right: Iterable[float]) -> float:
    """Return axis-aligned IoU for two ``[x1, y1, x2, y2]`` boxes."""

    a = list(left)
    b = list(right)
    if len(a) < 4 or len(b) < 4:
        return 0.0
    x1 = max(_float(a[0]), _float(b[0]))
    y1 = max(_float(a[1]), _float(b[1]))
    x2 = min(_float(a[2]), _float(b[2]))
    y2 = min(_float(a[3]), _float(b[3]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = max(0.0, _float(a[2]) - _float(a[0])) * max(0.0, _float(a[3]) - _float(a[1]))
    right_area = max(0.0, _float(b[2]) - _float(b[0])) * max(0.0, _float(b[3]) - _float(b[1]))
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _proposal_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "detection_id": str(row.get("detection_id") or ""),
        "class_id": int(row.get("class_id", -1)),
        "class_name": str(row.get("class_name") or "unknown"),
        "confidence": round(_float(row.get("confidence")), 6),
        "bbox_px": [round(value, 3) for value in (_bbox(row) or [0.0, 0.0, 0.0, 0.0])],
        "obb_px": [
            [round(_float(point[0]), 3), round(_float(point[1]), 3)]
            for point in (row.get("obb_px") or [])
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ][:4],
    }


def dedupe_proposals(
    rows: Iterable[dict[str, Any]],
    *,
    min_confidence: float = 0.05,
    iou_threshold: float = 0.45,
) -> list[dict[str, Any]]:
    """Collapse overlapping proposals across classes for human review.

    The detector's raw output remains unchanged.  This review-only pass prevents
    a plane/helicopter disagreement on one object from creating two labels while
    retaining every original proposal in ``alternative_proposals``.
    """

    threshold = max(0.0, min(1.0, float(iou_threshold)))
    ordered = []
    for row in rows:
        if not isinstance(row, dict) or _bbox(row) is None:
            continue
        if _float(row.get("confidence")) < float(min_confidence):
            continue
        ordered.append(row)
    ordered.sort(key=lambda row: _float(row.get("confidence")), reverse=True)

    candidates: list[dict[str, Any]] = []
    for row in ordered:
        summary = _proposal_summary(row)
        matched = None
        for candidate in candidates:
            if bbox_iou(summary["bbox_px"], candidate["bbox_px"]) >= threshold:
                matched = candidate
                break
        if matched is None:
            candidates.append(
                {
                    "candidate_id": f"cand-{len(candidates) + 1:04d}",
                    "source_detection_ids": [summary["detection_id"]],
                    "proposed_class": summary["class_name"],
                    "confidence": summary["confidence"],
                    "bbox_px": summary["bbox_px"],
                    "obb_px": summary["obb_px"],
                    "alternative_proposals": [summary],
                    "label": None,
                }
            )
        else:
            matched["source_detection_ids"].append(summary["detection_id"])
            matched["alternative_proposals"].append(summary)

    return candidates


def compute_chip_geometry(
    bbox_px: Iterable[float],
    *,
    image_width: int,
    image_height: int,
    chip_size: int = 512,
    context_scale: float = 2.5,
) -> dict[str, Any]:
    """Compute a square, candidate-centered crop and deterministic edge padding."""

    bbox = list(bbox_px)
    if len(bbox) < 4:
        raise ValueError("bbox_px must contain four coordinates")
    x1, y1, x2, y2 = (_float(value) for value in bbox[:4])
    if x2 <= x1 or y2 <= y1:
        raise ValueError("bbox_px must have positive width and height")
    width = max(1, int(image_width))
    height = max(1, int(image_height))
    base_size = max(16, int(chip_size))
    context = max(1.0, float(context_scale))
    side = max(base_size, int(math.ceil(max(x2 - x1, y2 - y1) * context)))
    center_x = (x1 + x2) / 2.0
    center_y = (y1 + y2) / 2.0
    target_x1 = int(round(center_x - side / 2.0))
    target_y1 = int(round(center_y - side / 2.0))
    target_x2 = target_x1 + side
    target_y2 = target_y1 + side
    source_x1 = max(0, target_x1)
    source_y1 = max(0, target_y1)
    source_x2 = min(width, target_x2)
    source_y2 = min(height, target_y2)
    if source_x2 <= source_x1 or source_y2 <= source_y1:
        raise ValueError("candidate crop does not intersect source image")
    return {
        "chip_size_px": side,
        "center_px": [round(center_x, 3), round(center_y, 3)],
        "target_crop_box_px": [target_x1, target_y1, target_x2, target_y2],
        "source_crop_box_px": [source_x1, source_y1, source_x2, source_y2],
        "paste_offset_px": [source_x1 - target_x1, source_y1 - target_y1],
    }


def _padded_canvas(image: Image.Image, geometry: dict[str, Any]) -> Image.Image:
    source_box = geometry["source_crop_box_px"]
    chip_size = int(geometry["chip_size_px"])
    crop = image.crop(tuple(source_box))
    canvas = Image.new("RGB", (chip_size, chip_size), (114, 114, 114))
    canvas.paste(crop, tuple(geometry["paste_offset_px"]))
    return canvas


def _save_padded_chip(image: Image.Image, geometry: dict[str, Any], path: Path) -> None:
    canvas = _padded_canvas(image, geometry)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG", optimize=False)


def _save_review_chip(
    image: Image.Image,
    geometry: dict[str, Any],
    candidate: dict[str, Any],
    path: Path,
) -> None:
    """Save a human-facing chip with the target proposal visibly marked."""

    canvas = _padded_canvas(image, geometry)
    target_x1, target_y1 = geometry["target_crop_box_px"][:2]
    points = candidate.get("obb_px") or []
    if not isinstance(points, list) or len(points) != 4:
        bbox = candidate.get("bbox_px") or [0.0, 0.0, 0.0, 0.0]
        x1, y1, x2, y2 = (_float(value) for value in bbox[:4])
        points = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    marked = [(round(_float(point[0]) - target_x1), round(_float(point[1]) - target_y1)) for point in points]
    marked.append(marked[0])
    class_name = str(candidate.get("proposed_class") or "candidate")
    color = (255, 220, 0) if class_name == "plane" else (255, 80, 80) if class_name == "helicopter" else (0, 220, 255)
    draw = ImageDraw.Draw(canvas)
    width = max(2, int(canvas.width / 128))
    draw.line(marked, fill=color, width=width, joint="curve")
    text = f"{candidate.get('candidate_id', '?')} {class_name} {_float(candidate.get('confidence')):.2f}"
    text_x = max(2, min(canvas.width - 160, marked[0][0] + 3))
    text_y = max(2, min(canvas.height - 16, marked[0][1] + 3))
    draw.text((text_x, text_y), text, fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG", optimize=False)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _validate_l1d_sr_metadata(
    *,
    collection_id: Any,
    item_id: Any,
    bounds_wgs84: Any,
) -> tuple[str, str, list[float]]:
    normalized_collection = str(collection_id or "").strip().lower().replace("_", "-")
    if normalized_collection != "l1d-sr":
        raise ValueError("Aircraft review accepts only Satellogic l1d-sr products")
    normalized_item = str(item_id or "").strip()
    if not normalized_item:
        raise ValueError("Aircraft review requires an l1d-sr item_id")
    if not isinstance(bounds_wgs84, (list, tuple)) or len(bounds_wgs84) != 4:
        raise ValueError("Aircraft review requires WGS84 bounds for image-to-map alignment")
    bounds = [_float(value) for value in bounds_wgs84]
    if not all(math.isfinite(value) for value in bounds) or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise ValueError("Aircraft review requires valid WGS84 bounds [west, south, east, north]")
    return normalized_collection, normalized_item, bounds


def prepare_review(
    *,
    image_path: Path,
    detections_path: Path,
    out_dir: Path,
    min_confidence: float = 0.05,
    chip_size: int = 512,
    context_scale: float = 2.5,
    iou_threshold: float = 0.45,
) -> Path:
    """Create candidate chips and a review manifest for one detector result."""

    image_path = Path(image_path).expanduser().resolve()
    detections_path = Path(detections_path).expanduser().resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    data = _load_json(detections_path)
    if str(data.get("detector") or "").strip().lower() != "aircraft":
        raise ValueError("Review input must be an aircraft detector result")
    input_data = data.get("input") if isinstance(data.get("input"), dict) else {}
    collection_id, item_id, bounds_wgs84 = _validate_l1d_sr_metadata(
        collection_id=input_data.get("collection_id"),
        item_id=input_data.get("item_id"),
        bounds_wgs84=input_data.get("bounds_wgs84"),
    )
    candidates = dedupe_proposals(
        data.get("detections", []),
        min_confidence=min_confidence,
        iou_threshold=iou_threshold,
    )
    chip_dir = out_dir / "chips"
    for candidate in candidates:
        geometry = compute_chip_geometry(
            candidate["bbox_px"],
            image_width=image.width,
            image_height=image.height,
            chip_size=chip_size,
            context_scale=context_scale,
        )
        candidate["chip_geometry"] = geometry
        chip_path = chip_dir / f"{candidate['candidate_id']}.png"
        review_chip_path = chip_dir / f"{candidate['candidate_id']}_review.png"
        _save_padded_chip(image, geometry, chip_path)
        _save_review_chip(image, geometry, candidate, review_chip_path)
        candidate["chip_path"] = str(chip_path.relative_to(out_dir))
        candidate["review_chip_path"] = str(review_chip_path.relative_to(out_dir))

    input_data = data.get("input") if isinstance(data.get("input"), dict) else {}
    model_data = data.get("model") if isinstance(data.get("model"), dict) else {}
    manifest = {
        "schema_version": "aircraft-review.v1",
        "purpose": "detector-candidate-labeling",
        "source": {
            "image_path": str(image_path),
            "detections_path": str(detections_path),
            "image_width_px": image.width,
            "image_height_px": image.height,
            "item_id": item_id,
            "collection_id": collection_id,
            "bounds_wgs84": bounds_wgs84,
            "crs": "EPSG:4326",
            "pixel_coordinate_convention": "origin_top_left_x_right_y_down",
        },
        "model": {
            "name": model_data.get("name"),
            "provider_mode": model_data.get("provider_mode"),
            "providers": model_data.get("providers", []),
        },
        "settings": {
            "min_confidence": float(min_confidence),
            "chip_size_px": int(chip_size),
            "context_scale": float(context_scale),
            "dedupe_iou_threshold": float(iou_threshold),
        },
        "labels_path": "labels.jsonl",
        "candidates": candidates,
    }
    manifest_path = out_dir / "review_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    return manifest_path


def normalize_label(label: str) -> str:
    key = str(label or "").strip().lower().replace(" ", "-")
    normalized = _LABEL_ALIASES.get(key)
    if normalized is None:
        raise ValueError(f"Unknown label {label!r}; use 1/2/3/0 or plane/helicopter/background/skip")
    return normalized


def record_label(
    manifest_path: Path,
    candidate_id: str,
    label: str,
    *,
    note: str | None = None,
    override: bool = False,
) -> Path:
    """Record one phone label, rejecting accidental conflicting relabels."""

    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest = _load_json(manifest_path)
    normalized = normalize_label(label)
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Review manifest has no candidate list")
    candidate = next((item for item in candidates if item.get("candidate_id") == candidate_id), None)
    if candidate is None:
        raise ValueError(f"Unknown candidate ID: {candidate_id}")
    previous = candidate.get("label")
    if previous is not None and previous != normalized and not override:
        raise ValueError(f"Candidate {candidate_id} already has label {previous!r}; use override to change it")
    if previous == normalized and not note:
        return manifest_path

    candidate["label"] = normalized
    labels_path = manifest_path.parent / str(manifest.get("labels_path") or "labels.jsonl")
    event = {
        "schema_version": "aircraft-label-event.v1",
        "candidate_id": candidate_id,
        "label": normalized,
        "previous_label": previous,
        "note": note,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    with labels_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    _atomic_write_json(manifest_path, manifest)
    return manifest_path


def _training_obb_points(candidate: dict[str, Any]) -> list[list[float]]:
    geometry = candidate.get("chip_geometry") if isinstance(candidate.get("chip_geometry"), dict) else {}
    target_x1, target_y1 = (geometry.get("target_crop_box_px") or [0, 0])[:2]
    side = max(1.0, _float(geometry.get("chip_size_px"), 1.0))
    points = candidate.get("obb_px") or []
    if not isinstance(points, list) or len(points) != 4:
        bbox = candidate.get("bbox_px") or [0.0, 0.0, 0.0, 0.0]
        x1, y1, x2, y2 = (_float(value) for value in bbox[:4])
        points = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    normalized = []
    for point in points[:4]:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x = max(0.0, min(1.0, (_float(point[0]) - _float(target_x1)) / side))
        y = max(0.0, min(1.0, (_float(point[1]) - _float(target_y1)) / side))
        normalized.append([x, y])
    if len(normalized) != 4:
        raise ValueError(f"Candidate {candidate.get('candidate_id')} has no usable four-point OBB")
    return normalized


def export_labelled_dataset(
    manifest_path: Path,
    out_dir: Path,
    *,
    split: str = "train",
) -> Path:
    """Export labeled chips for a reranker and a two-class YOLO-OBB dataset."""

    manifest_path = Path(manifest_path).expanduser().resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    data = _load_json(manifest_path)
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    collection_id, item_id, bounds_wgs84 = _validate_l1d_sr_metadata(
        collection_id=source.get("collection_id"),
        item_id=source.get("item_id"),
        bounds_wgs84=source.get("bounds_wgs84"),
    )
    split_name = str(split or "train").strip()
    if not split_name or Path(split_name).name != split_name or split_name in {".", ".."}:
        raise ValueError("Dataset split must be a simple directory name")

    yolo_images = out_dir / "yolo" / "images" / split_name
    yolo_labels = out_dir / "yolo" / "labels" / split_name
    counts = {"plane": 0, "helicopter": 0, "background": 0, "skip": 0}
    items: list[dict[str, Any]] = []
    class_ids = {"plane": 0, "helicopter": 1}

    for candidate in data.get("candidates", []):
        label = normalize_label(candidate.get("label")) if candidate.get("label") is not None else "skip"
        counts[label] += 1
        if label == "skip":
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            raise ValueError("Labeled candidate is missing candidate_id")
        source_chip = manifest_path.parent / str(candidate.get("chip_path") or "")
        if not source_chip.is_file():
            raise ValueError(f"Clean chip is missing for {candidate_id}: {source_chip}")

        classifier_path = out_dir / "classifier" / label / f"{candidate_id}.png"
        classifier_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_chip, classifier_path)

        yolo_image = yolo_images / f"{candidate_id}.png"
        yolo_label = yolo_labels / f"{candidate_id}.txt"
        yolo_image.parent.mkdir(parents=True, exist_ok=True)
        yolo_label.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_chip, yolo_image)
        yolo_line = ""
        if label in class_ids:
            points = _training_obb_points(candidate)
            flat = " ".join(f"{value:.6f}" for point in points for value in point)
            yolo_line = f"{class_ids[label]} {flat}\n"
        yolo_label.write_text(yolo_line, encoding="utf-8")
        items.append(
            {
                "candidate_id": candidate_id,
                "label": label,
                "classifier_path": str(classifier_path.relative_to(out_dir)),
                "yolo_image_path": str(yolo_image.relative_to(out_dir)),
                "yolo_label_path": str(yolo_label.relative_to(out_dir)),
                "source_bbox_px": candidate.get("bbox_px"),
                "source_obb_px": candidate.get("obb_px"),
                "chip_geometry": candidate.get("chip_geometry"),
            }
        )

    export_manifest = {
        "schema_version": "aircraft-training-export.v1",
        "source_review_manifest": str(manifest_path),
        "source": {
            "collection_id": collection_id,
            "item_id": item_id,
            "bounds_wgs84": bounds_wgs84,
            "crs": "EPSG:4326",
            "pixel_coordinate_convention": "origin_top_left_x_right_y_down",
        },
        "split": split_name,
        "classes": {"0": "plane", "1": "helicopter"},
        "counts": counts,
        "items": items,
    }
    export_manifest_path = out_dir / "dataset_manifest.json"
    _atomic_write_json(export_manifest_path, export_manifest)
    return export_manifest_path


def _grid_starts(length: int, chip_size: int, stride: int) -> list[int]:
    if length <= chip_size:
        return [0]
    starts = list(range(0, max(1, length - chip_size + 1), stride))
    last = length - chip_size
    if starts[-1] != last:
        starts.append(last)
    return sorted(set(starts))


def generate_grid_chips(
    *,
    image_path: Path,
    out_dir: Path,
    chip_size: int = 512,
    stride: int = 384,
    item_id: str,
    bounds_wgs84: Iterable[float],
    collection_id: str = "l1d-sr",
) -> Path:
    """Create overlapping discovery chips for objects absent from proposals."""

    image_path = Path(image_path).expanduser().resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    normalized_collection, normalized_item, bounds = _validate_l1d_sr_metadata(
        collection_id=collection_id,
        item_id=item_id,
        bounds_wgs84=bounds_wgs84,
    )
    size = max(32, int(chip_size))
    step = max(1, min(size, int(stride)))
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    cells: list[dict[str, Any]] = []
    for y in _grid_starts(image.height, size, step):
        for x in _grid_starts(image.width, size, step):
            source_x2 = min(image.width, x + size)
            source_y2 = min(image.height, y + size)
            geometry = {
                "chip_size_px": size,
                "source_crop_box_px": [x, y, source_x2, source_y2],
                "paste_offset_px": [0, 0],
            }
            cell_id = f"grid-{len(cells) + 1:04d}"
            chip_path = out_dir / "chips" / f"{cell_id}.png"
            _save_padded_chip(image, geometry, chip_path)
            cells.append(
                {
                    "cell_id": cell_id,
                    "x_px": x,
                    "y_px": y,
                    "source_crop_box_px": geometry["source_crop_box_px"],
                    "chip_path": str(chip_path.relative_to(out_dir)),
                    "label": None,
                    "purpose": "missed-object-discovery",
                }
            )
    manifest = {
        "schema_version": "aircraft-grid-review.v1",
        "purpose": "missed-object-discovery",
        "source": {
            "image_path": str(image_path),
            "image_width_px": image.width,
            "image_height_px": image.height,
            "collection_id": normalized_collection,
            "item_id": normalized_item,
            "bounds_wgs84": bounds,
            "crs": "EPSG:4326",
            "pixel_coordinate_convention": "origin_top_left_x_right_y_down",
        },
        "settings": {"chip_size_px": size, "stride_px": step},
        "cells": cells,
    }
    manifest_path = out_dir / "grid_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    return manifest_path
