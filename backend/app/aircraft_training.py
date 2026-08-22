"""Build a safe, provenance-preserving training bundle from review manifests."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from collections import defaultdict
from typing import Any, Iterable

from PIL import Image

from .aircraft_review import (
    _load_json,
    _save_padded_chip,
    _training_obb_points,
    _validate_l1d_sr_metadata,
    compute_chip_geometry,
    normalize_label,
)


_CLASS_IDS = {"plane": 0, "helicopter": 1}


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    return cleaned.strip("-_.") or "scene"


def _annotation_bbox(annotation: dict[str, Any]) -> list[float]:
    geometry = annotation.get("geometry_px")
    if not isinstance(geometry, list) or len(geometry) < 4:
        raise ValueError(f"Annotation {annotation.get('annotation_id')} has no four-point geometry")
    points = []
    for point in geometry:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        points.append((float(point[0]), float(point[1])))
    if len(points) < 4:
        raise ValueError(f"Annotation {annotation.get('annotation_id')} has invalid geometry")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    bbox = [min(xs), min(ys), max(xs), max(ys)]
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise ValueError(f"Annotation {annotation.get('annotation_id')} has zero-area geometry")
    return bbox


def _annotation_obb(annotation: dict[str, Any], bbox: list[float]) -> list[list[float]]:
    geometry = annotation.get("geometry_px")
    if isinstance(geometry, list) and len(geometry) == 4:
        points = []
        for point in geometry:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                break
            points.append([float(point[0]), float(point[1])])
        if len(points) == 4:
            return points
    x1, y1, x2, y2 = bbox
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _annotation_group_key(annotation: dict[str, Any]) -> tuple[str, str, tuple[float, ...]]:
    source_path = str(annotation.get("source_image_path") or "").strip()
    bounds = tuple(float(value) for value in (annotation.get("bounds_wgs84") or []))
    return str(annotation.get("item_id") or "").strip(), source_path, bounds


def build_review_manifests_from_annotations(
    annotations: Iterable[dict[str, Any]],
    out_dir: Path,
) -> list[Path]:
    """Materialize Model Lab annotations into review manifests with clean chips."""

    grouped: dict[tuple[str, str, tuple[float, ...]], list[dict[str, Any]]] = defaultdict(list)
    for annotation in annotations:
        label = normalize_label(annotation.get("label"))
        if label == "skip":
            continue
        image_path = Path(str(annotation.get("source_image_path") or "")).expanduser().resolve()
        if not image_path.is_file():
            raise ValueError(f"Annotation source image is missing: {image_path}")
        grouped[_annotation_group_key(annotation)].append(annotation)
    if not grouped:
        raise ValueError("No labeled annotations with source imagery were selected")

    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifests: list[Path] = []
    for scene_index, (group_key, rows) in enumerate(sorted(grouped.items()), start=1):
        item_id, source_path, bounds = group_key
        if not item_id:
            raise ValueError("Annotation is missing item_id")
        collection_id, item_id, bounds_list = _validate_l1d_sr_metadata(
            collection_id=rows[0].get("collection_id"),
            item_id=item_id,
            bounds_wgs84=bounds,
        )
        image_path = Path(source_path)
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        scene_dir = out_dir / f"scene{scene_index:02d}_{_safe_name(item_id)}"
        chip_dir = scene_dir / "chips"
        candidates: list[dict[str, Any]] = []
        for candidate_index, annotation in enumerate(rows, start=1):
            bbox = _annotation_bbox(annotation)
            geometry = compute_chip_geometry(
                bbox,
                image_width=image.width,
                image_height=image.height,
                chip_size=512,
                context_scale=2.5,
            )
            candidate_id = _safe_name(annotation.get("annotation_id") or f"ann-{candidate_index:04d}")
            chip_path = chip_dir / f"{candidate_id}.png"
            _save_padded_chip(image, geometry, chip_path)
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "source_detection_ids": [annotation.get("detection_id")] if annotation.get("detection_id") else [],
                    "proposed_class": annotation.get("label"),
                    "confidence": annotation.get("confidence"),
                    "bbox_px": bbox,
                    "obb_px": _annotation_obb(annotation, bbox),
                    "chip_geometry": geometry,
                    "chip_path": str(chip_path.relative_to(scene_dir)),
                    "label": normalize_label(annotation.get("label")),
                    "annotation_id": annotation.get("annotation_id"),
                    "annotation_key": annotation.get("annotation_key"),
                }
            )
        manifest = {
            "schema_version": "aircraft-review.v1",
            "purpose": "model-lab-annotation-training",
            "source": {
                "image_path": str(image_path),
                "image_width_px": image.width,
                "image_height_px": image.height,
                "item_id": item_id,
                "collection_id": collection_id,
                "bounds_wgs84": bounds_list,
                "crs": "EPSG:4326",
                "pixel_coordinate_convention": "origin_top_left_x_right_y_down",
            },
            "model": {"name": "model-lab-annotations"},
            "settings": {"chip_size_px": 512, "context_scale": 2.5},
            "labels_path": "labels.jsonl",
            "candidates": candidates,
        }
        manifest_path = scene_dir / "review_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifests.append(manifest_path)
    return manifests


def build_training_bundle_from_annotations(
    annotations: Iterable[dict[str, Any]],
    out_dir: Path,
    review_root: Path,
    *,
    train_item_ids: Iterable[str],
    validation_item_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Create review manifests and a scene-aware YOLO bundle from UI labels."""

    train_ids = {str(value).strip() for value in train_item_ids if str(value).strip()}
    validation_ids = {str(value).strip() for value in (validation_item_ids or []) if str(value).strip()}
    if not train_ids:
        raise ValueError("At least one training scene is required")
    if train_ids.intersection(validation_ids):
        raise ValueError("A scene cannot be both training and validation data")
    rows = [dict(row) for row in annotations]
    train_rows = [row for row in rows if str(row.get("item_id") or "").strip() in train_ids]
    validation_rows = [row for row in rows if str(row.get("item_id") or "").strip() in validation_ids]
    if not train_rows:
        raise ValueError("No labeled annotations were found for the selected training scenes")
    train_manifests = build_review_manifests_from_annotations(train_rows, Path(review_root) / "train")
    validation_manifests = build_review_manifests_from_annotations(validation_rows, Path(review_root) / "validation") if validation_rows else []
    result = build_training_bundle(train_manifests, Path(out_dir), validation_manifest_paths=validation_manifests)
    result["annotation_count"] = len(train_rows) + len(validation_rows)
    result["review_manifests"] = [str(path) for path in train_manifests]
    result["validation_review_manifests"] = [str(path) for path in validation_manifests]
    (Path(out_dir) / "training_manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _write_dataset_yaml(path: Path, root: Path, *, has_validation: bool) -> None:
    validation_path = "images/val" if has_validation else "images/train"
    path.write_text(
        "\n".join(
            [
                f"path: {root}",
                "train: images/train",
                f"val: {validation_path}",
                "names:",
                "  0: plane",
                "  1: helicopter",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build_training_bundle(
    manifest_paths: Iterable[Path],
    out_dir: Path,
    *,
    validation_manifest_paths: Iterable[Path] | None = None,
) -> dict[str, Any]:
    """Merge labeled L1D-SR review manifests into a two-class YOLO-OBB bundle.

    The function deliberately creates a train-only bundle.  Validation must be
    performed on a separate L1D-SR scene; using chips from the same scene would
    overstate generalization.
    """

    train_paths = [Path(path).expanduser().resolve() for path in manifest_paths]
    validation_paths = [Path(path).expanduser().resolve() for path in (validation_manifest_paths or [])]
    if not train_paths:
        raise ValueError("At least one review manifest is required")
    overlap = set(train_paths).intersection(validation_paths)
    if overlap:
        raise ValueError(f"A review manifest cannot be both training and validation data: {sorted(overlap)[0]}")
    out_dir = Path(out_dir).expanduser().resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError(f"Training output directory is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images" / "train"
    labels_dir = out_dir / "labels" / "train"
    validation_images_dir = out_dir / "images" / "val"
    validation_labels_dir = out_dir / "labels" / "val"
    classifier_dir = out_dir / "classifier"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    validation_images_dir.mkdir(parents=True, exist_ok=True)
    validation_labels_dir.mkdir(parents=True, exist_ok=True)

    counts = {"plane": 0, "helicopter": 0, "background": 0}
    items: list[dict[str, Any]] = []
    scene_ids: list[str] = []
    warnings: list[str] = []

    train_scene_ids: list[str] = []
    validation_scene_ids: list[str] = []
    validation_counts = {"plane": 0, "helicopter": 0, "background": 0}

    def copy_manifest(
        manifest_path: Path,
        scene_index: int,
        *,
        split: str,
        scene_id_list: list[str],
        split_counts: dict[str, int],
    ) -> None:
        manifest = _load_json(manifest_path)
        source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        collection_id, item_id, bounds = _validate_l1d_sr_metadata(
            collection_id=source.get("collection_id"),
            item_id=source.get("item_id"),
            bounds_wgs84=source.get("bounds_wgs84"),
        )
        scene_ids.append(item_id)
        scene_id_list.append(item_id)
        prefix = f"scene{scene_index:02d}_{_safe_name(item_id)}"
        split_images_dir = images_dir if split == "train" else validation_images_dir
        split_labels_dir = labels_dir if split == "train" else validation_labels_dir
        for candidate in manifest.get("candidates", []):
            raw_label = candidate.get("label")
            if raw_label is None:
                continue
            label = normalize_label(raw_label)
            if label == "skip":
                continue
            if label not in {"plane", "helicopter", "background"}:
                raise ValueError(f"Unsupported training label: {label}")
            candidate_id = _safe_name(candidate.get("candidate_id"))
            source_chip = manifest_path.parent / str(candidate.get("chip_path") or "")
            if not source_chip.is_file():
                raise ValueError(f"Clean chip is missing: {source_chip}")
            output_id = f"{prefix}_{candidate_id}"
            image_path = split_images_dir / f"{output_id}.png"
            label_path = split_labels_dir / f"{output_id}.txt"
            shutil.copy2(source_chip, image_path)
            line = ""
            if label in _CLASS_IDS:
                points = _training_obb_points(candidate)
                flat = " ".join(f"{value:.6f}" for point in points for value in point)
                line = f"{_CLASS_IDS[label]} {flat}\n"
            label_path.write_text(line, encoding="utf-8")
            classifier_path = classifier_dir / label / f"{output_id}.png"
            classifier_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_chip, classifier_path)
            split_counts[label] += 1
            items.append(
                {
                    "output_id": output_id,
                    "source_manifest": str(manifest_path),
                    "source_item_id": item_id,
                    "source_bounds_wgs84": bounds,
                    "candidate_id": candidate.get("candidate_id"),
                    "label": label,
                    "image_path": str(image_path.relative_to(out_dir)),
                    "label_path": str(label_path.relative_to(out_dir)),
                    "split": split,
                }
            )

    for scene_index, manifest_path in enumerate(train_paths, start=1):
        copy_manifest(
            manifest_path,
            scene_index,
            split="train",
            scene_id_list=train_scene_ids,
            split_counts=counts,
        )
    for scene_index, manifest_path in enumerate(validation_paths, start=1):
        copy_manifest(
            manifest_path,
            scene_index,
            split="val",
            scene_id_list=validation_scene_ids,
            split_counts=validation_counts,
        )

    unique_scene_ids = sorted(set(scene_ids))
    scene_separated = len(unique_scene_ids) >= 2
    validation_ready = bool(validation_paths) and not set(train_scene_ids).intersection(validation_scene_ids)
    if validation_paths and not validation_ready:
        warnings.append("validation manifests overlap training scenes; held-out validation is not independent")
    if not validation_paths:
        if len(unique_scene_ids) < 2:
            warnings.append("single-scene training bundle; no held-out scene validation is available")
        else:
            warnings.append("no held-out validation manifests supplied; training metrics are not a scene-separated quality check")
    if counts["background"] == 0:
        warnings.append("no background chips labeled; false-positive rejection is not trained")
    if counts["plane"] + counts["helicopter"] < 50:
        warnings.append("small labeled dataset; fine-tuned weights are experimental")

    dataset_yaml = out_dir / "data.yaml"
    _write_dataset_yaml(dataset_yaml, out_dir, has_validation=bool(validation_paths))
    result = {
        "schema_version": "aircraft-training-bundle.v1",
        "data_yaml": str(dataset_yaml),
        "out_dir": str(out_dir),
        "manifests": [str(path) for path in train_paths],
        "validation_manifests": [str(path) for path in validation_paths],
        "scene_ids": unique_scene_ids,
        "scene_count": len(unique_scene_ids),
        "train_scene_ids": sorted(set(train_scene_ids)),
        "validation_scene_ids": sorted(set(validation_scene_ids)),
        "scene_separated": scene_separated,
        "validation_ready": validation_ready,
        "classes": {"0": "plane", "1": "helicopter"},
        "counts": counts,
        "validation_counts": validation_counts,
        "warnings": warnings,
        "items": items,
    }
    (out_dir / "training_manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result
