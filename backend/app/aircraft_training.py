"""Build a safe, provenance-preserving training bundle from review manifests."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable

from .aircraft_review import (
    _load_json,
    _training_obb_points,
    _validate_l1d_sr_metadata,
    normalize_label,
)


_CLASS_IDS = {"plane": 0, "helicopter": 1}


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    return cleaned.strip("-_.") or "scene"


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
