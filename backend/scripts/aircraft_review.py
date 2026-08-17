#!/usr/bin/env python3
"""Prepare and label phone-based aircraft review chips.

This CLI is intentionally transport-neutral.  The Hermes skill sends the paths
printed by ``next`` through Telegram and calls ``label`` for each reply.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.aircraft_review import (  # noqa: E402
    export_labelled_dataset,
    generate_grid_chips,
    prepare_review,
    record_label,
)
from backend.app.luna_aircraft import (  # noqa: E402
    LunaAircraftEvaluator,
    build_luna_examples,
    run_luna_evaluations,
)


def _bounds(value: str) -> list[float]:
    values = [float(part.strip()) for part in str(value).split(",")]
    if len(values) != 4:
        raise argparse.ArgumentTypeError("bounds must be west,south,east,north")
    return values


def _manifest(path: Path) -> dict:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def _prepare(args: argparse.Namespace) -> int:
    path = prepare_review(
        image_path=Path(args.image),
        detections_path=Path(args.detections),
        out_dir=Path(args.outdir),
        min_confidence=args.min_confidence,
        chip_size=args.chip_size,
        context_scale=args.context_scale,
        iou_threshold=args.iou,
    )
    data = _manifest(path)
    print(json.dumps({"manifest": str(path), "candidate_count": len(data["candidates"])}, indent=2))
    return 0


def _next(args: argparse.Namespace) -> int:
    path = Path(args.manifest).expanduser().resolve()
    data = _manifest(path)
    pending = [candidate for candidate in data.get("candidates", []) if candidate.get("label") is None]
    selected = pending[: max(1, int(args.count))]
    root = path.parent
    output = []
    for candidate in selected:
        output.append(
            {
                "candidate_id": candidate["candidate_id"],
                "chip_path": str(root / candidate["chip_path"]),
                "review_chip_path": str(root / candidate["review_chip_path"]),
                "proposed_class": candidate.get("proposed_class"),
                "confidence": candidate.get("confidence"),
                "prompt": "Reply 1=plane, 2=helicopter, 3=background/no detection, 0=unsure/skip",
            }
        )
    print(json.dumps({"manifest": str(path), "remaining": len(pending), "items": output}, indent=2))
    return 0


def _label(args: argparse.Namespace) -> int:
    path = record_label(
        Path(args.manifest),
        args.candidate,
        args.label,
        note=args.note,
        override=args.override,
    )
    print(path)
    return 0


def _export(args: argparse.Namespace) -> int:
    path = export_labelled_dataset(Path(args.manifest), Path(args.outdir), split=args.split)
    data = _manifest(path)
    print(json.dumps({"manifest": str(path), "counts": data["counts"], "item_count": len(data["items"])}, indent=2))
    return 0


def _grid(args: argparse.Namespace) -> int:
    path = generate_grid_chips(
        image_path=Path(args.image),
        out_dir=Path(args.outdir),
        chip_size=args.chip_size,
        stride=args.stride,
        item_id=args.item_id,
        bounds_wgs84=_bounds(args.bounds),
        collection_id=args.collection_id,
    )
    data = _manifest(path)
    print(json.dumps({"manifest": str(path), "cell_count": len(data["cells"])}, indent=2))
    return 0


def _batch_prepare(args: argparse.Namespace) -> int:
    image_dir = Path(args.image_dir).expanduser().resolve()
    detections_dir = Path(args.detections_dir).expanduser().resolve()
    out_dir = Path(args.outdir).expanduser().resolve()
    images = sorted(path for path in image_dir.glob(args.glob) if path.is_file())
    if not images:
        raise ValueError(f"No images matched {args.glob!r} in {image_dir}")
    scene_manifests = []
    rows = []
    for image_path in images:
        detections_path = detections_dir / f"{image_path.stem}.json"
        if not detections_path.is_file():
            rows.append({"image": str(image_path), "status": "error", "error": f"missing detections: {detections_path}"})
            continue
        scene_dir = out_dir / image_path.stem
        try:
            manifest_path = prepare_review(
                image_path=image_path,
                detections_path=detections_path,
                out_dir=scene_dir,
                min_confidence=args.min_confidence,
                chip_size=args.chip_size,
                context_scale=args.context_scale,
                iou_threshold=args.iou,
            )
            manifest = _manifest(manifest_path)
            scene_manifests.append(str(manifest_path))
            rows.append({"image": str(image_path), "manifest": str(manifest_path), "candidates": len(manifest.get("candidates", [])), "status": "complete"})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            rows.append({"image": str(image_path), "status": "error", "error": str(exc)[:400]})
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_manifest = {"schema_version": "aircraft-review-batch.v1", "image_dir": str(image_dir), "detections_dir": str(detections_dir), "manifests": scene_manifests, "items": rows}
    batch_path = out_dir / "batch_review_manifest.json"
    batch_path.write_text(json.dumps(batch_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(batch_path), "scenes": len(scene_manifests), "errors": sum(row["status"] == "error" for row in rows)}, indent=2))
    return 0 if not any(row["status"] == "error" for row in rows) else 1


def _status(args: argparse.Namespace) -> int:
    path = Path(args.manifest).expanduser().resolve()
    data = _manifest(path)
    counts = {"plane": 0, "helicopter": 0, "background": 0, "skip": 0, "unlabelled": 0}
    for candidate in data.get("candidates", []):
        label = candidate.get("label") or "unlabelled"
        counts[label] = counts.get(label, 0) + 1
    print(json.dumps({"manifest": str(path), "counts": counts}, indent=2, sort_keys=True))
    return 0


def _luna_prime(args: argparse.Namespace) -> int:
    examples = build_luna_examples(
        [Path(path) for path in args.manifest],
        max_per_label=args.max_per_label,
    )
    out_dir = Path(args.outdir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "luna_examples.json"
    path.write_text(json.dumps(examples, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"examples": str(path), "counts": examples["counts"]}, indent=2, sort_keys=True))
    return 0


def _luna_evaluate(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).expanduser().resolve()
    if args.prime_manifest:
        examples = _manifest(Path(args.prime_manifest))
    else:
        examples = build_luna_examples(
            [Path(path) for path in args.examples_manifest],
            max_per_label=args.max_per_label,
        )
    evaluator = LunaAircraftEvaluator(
        model=args.model,
        transport=args.transport,
        hermes_bin=args.hermes_bin,
    )
    result = run_luna_evaluations(
        manifest_path,
        examples,
        candidate_ids=args.candidate,
        limit=args.limit,
        evaluator=evaluator,
    )
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, indent=2, sort_keys=True))
    return 0 if result["errors"] == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and label L1D-SR aircraft review chips")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="create low-threshold candidate chips")
    prepare_parser.add_argument("--image", required=True)
    prepare_parser.add_argument("--detections", required=True)
    prepare_parser.add_argument("--outdir", required=True)
    prepare_parser.add_argument("--min-confidence", type=float, default=0.05)
    prepare_parser.add_argument("--chip-size", type=int, default=512)
    prepare_parser.add_argument("--context-scale", type=float, default=2.5)
    prepare_parser.add_argument("--iou", type=float, default=0.45)
    prepare_parser.set_defaults(handler=_prepare)

    next_parser = subparsers.add_parser("next", help="print the next unlabelled chips")
    next_parser.add_argument("--manifest", required=True)
    next_parser.add_argument("--count", type=int, default=1)
    next_parser.set_defaults(handler=_next)

    label_parser = subparsers.add_parser("label", help="record one phone label")
    label_parser.add_argument("--manifest", required=True)
    label_parser.add_argument("--candidate", required=True)
    label_parser.add_argument("--label", required=True, help="1/2/3/0 or plane/helicopter/background/skip")
    label_parser.add_argument("--note")
    label_parser.add_argument("--override", action="store_true")
    label_parser.set_defaults(handler=_label)

    export_parser = subparsers.add_parser("export", help="export labeled chips for training")
    export_parser.add_argument("--manifest", required=True)
    export_parser.add_argument("--outdir", required=True)
    export_parser.add_argument("--split", default="train")
    export_parser.set_defaults(handler=_export)

    grid_parser = subparsers.add_parser("grid", help="create missed-object discovery chips")
    grid_parser.add_argument("--image", required=True)
    grid_parser.add_argument("--outdir", required=True)
    grid_parser.add_argument("--item-id", required=True)
    grid_parser.add_argument("--bounds", required=True, help="west,south,east,north")
    grid_parser.add_argument("--collection-id", default="l1d-sr")
    grid_parser.add_argument("--chip-size", type=int, default=512)
    grid_parser.add_argument("--stride", type=int, default=384)
    grid_parser.set_defaults(handler=_grid)

    batch_parser = subparsers.add_parser("batch-prepare", help="prepare review chips for a directory of detector results")
    batch_parser.add_argument("--image-dir", required=True)
    batch_parser.add_argument("--detections-dir", required=True)
    batch_parser.add_argument("--outdir", required=True)
    batch_parser.add_argument("--glob", default="*.png")
    batch_parser.add_argument("--min-confidence", type=float, default=0.05)
    batch_parser.add_argument("--chip-size", type=int, default=512)
    batch_parser.add_argument("--context-scale", type=float, default=2.5)
    batch_parser.add_argument("--iou", type=float, default=0.45)
    batch_parser.set_defaults(handler=_batch_prepare)

    status_parser = subparsers.add_parser("status", help="summarize labels")
    status_parser.add_argument("--manifest", required=True)
    status_parser.set_defaults(handler=_status)

    prime_parser = subparsers.add_parser(
        "luna-prime",
        help="build a reusable few-shot manifest from human-confirmed examples",
    )
    prime_parser.add_argument("--manifest", action="append", required=True, help="Review manifest; repeat for additional scenes")
    prime_parser.add_argument("--outdir", required=True)
    prime_parser.add_argument("--max-per-label", type=int, default=12)
    prime_parser.set_defaults(handler=_luna_prime)

    luna_parser = subparsers.add_parser(
        "luna-evaluate",
        help="send review chips plus confirmed examples to GPT-5.6 Luna",
    )
    luna_parser.add_argument("--manifest", required=True, help="Review manifest containing target candidates")
    examples_group = luna_parser.add_mutually_exclusive_group(required=True)
    examples_group.add_argument("--prime-manifest", help="Output from luna-prime")
    examples_group.add_argument("--examples-manifest", action="append", help="Review manifest(s) containing confirmed examples")
    luna_parser.add_argument("--candidate", action="append", help="Evaluate one candidate ID; repeat as needed")
    luna_parser.add_argument("--limit", type=int, help="Maximum number of pending candidates")
    luna_parser.add_argument("--max-per-label", type=int, default=12)
    luna_parser.add_argument("--model", default=None)
    luna_parser.add_argument("--transport", choices=("hermes", "api"), default=None)
    luna_parser.add_argument("--hermes-bin", default=None)
    luna_parser.set_defaults(handler=_luna_evaluate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
