#!/usr/bin/env python3
"""Fine-tune the two-class L1D-SR aircraft OBB model on a host runtime.

The Hermes Docker runtime is intentionally not assumed to have PyTorch, MPS,
or CUDA. Use ``--prepare-only`` here to build/verify the bundle; run the full
command from the macOS host environment that exposes PyTorch MPS.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.aircraft_training import build_training_bundle  # noqa: E402


def _default_model() -> Path:
    return PROJECT_ROOT / "yolo11n-obb.pt"


def _preflight_torch(device: str) -> dict[str, Any]:
    try:
        import torch
    except Exception as exc:
        raise RuntimeError(
            "PyTorch is not installed in this runtime. On the macOS host, install "
            "backend/requirements-aircraft-training.txt in a separate training venv."
        ) from exc
    normalized = str(device or "cpu").strip().lower()
    result = {
        "torch_version": getattr(torch, "__version__", "unknown"),
        "device_requested": normalized,
        "mps_available": bool(getattr(getattr(torch, "backends", None), "mps", None) and torch.backends.mps.is_available()),
        "cuda_available": bool(torch.cuda.is_available()),
    }
    if normalized in {"mps", "metal"} and not result["mps_available"]:
        raise RuntimeError("MPS was requested but torch.backends.mps.is_available() is false")
    if normalized in {"cuda", "gpu"} and not result["cuda_available"]:
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
    return result


def _train(args: argparse.Namespace, bundle: dict[str, Any]) -> dict[str, Any]:
    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise RuntimeError(
            "Ultralytics is not installed in this runtime. Install the host-only "
            "training requirements before running without --prepare-only."
        ) from exc

    device_info = _preflight_torch(args.device)
    model_path = Path(args.model).expanduser().resolve()
    if not model_path.is_file():
        raise RuntimeError(f"Base YOLO model not found: {model_path}")
    out_dir = Path(args.outdir).expanduser().resolve()
    run_dir = out_dir / "runs"
    model = YOLO(str(model_path), task="obb")
    model.train(
        data=str(bundle["data_yaml"]),
        task="obb",
        epochs=int(args.epochs),
        imgsz=int(args.imgsz),
        batch=int(args.batch),
        device=str(args.device),
        workers=int(args.workers),
        project=str(run_dir),
        name="l1d-aircraft",
        exist_ok=False,
        val=bool(bundle.get("validation_manifests")),
        cache=False,
        plots=True,
        pretrained=True,
        lr0=0.001,
        lrf=0.01,
        warmup_epochs=1.0,
        freeze=10,
        mosaic=0.10,
        mixup=0.0,
        close_mosaic=5,
        verbose=True,
    )
    best_pt = run_dir / "l1d-aircraft" / "weights" / "best.pt"
    if not best_pt.is_file():
        raise RuntimeError(f"Training completed without expected checkpoint: {best_pt}")
    summary: dict[str, Any] = {
        "base_model": str(model_path),
        "best_model": str(best_pt),
        "device": device_info,
        "epochs": int(args.epochs),
        "imgsz": int(args.imgsz),
        "warnings": list(bundle.get("warnings", [])),
    }
    if args.export_onnx:
        trained = YOLO(str(best_pt), task="obb")
        exported = trained.export(
            format="onnx",
            imgsz=int(args.imgsz),
            opset=12,
            dynamic=False,
            simplify=False,
            device="cpu",
        )
        exported_path = Path(str(exported)).expanduser().resolve()
        if not exported_path.is_file():
            raise RuntimeError(f"ONNX export returned a missing path: {exported_path}")
        target_onnx = out_dir / "aircraft-l1d-finetuned.onnx"
        shutil.copy2(exported_path, target_onnx)
        summary["onnx_model"] = str(target_onnx)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fine-tune the L1D-SR plane/helicopter YOLO-OBB model")
    parser.add_argument("--manifest", action="append", required=True, help="Review manifest; repeat for additional scenes")
    parser.add_argument("--validation-manifest", action="append", default=[], help="Held-out review manifest; repeat for additional validation scenes")
    parser.add_argument("--outdir", required=True, help="New, empty output directory")
    parser.add_argument("--model", default=str(_default_model()))
    parser.add_argument("--device", default="mps", help="mps, cuda, or cpu")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--imgsz", type=int, default=1024)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--allow-single-scene", action="store_true")
    parser.add_argument("--export-onnx", action="store_true", help="Export best.pt to an ONNX artifact")
    parser.add_argument("--prepare-only", action="store_true", help="Build the bundle without importing PyTorch/Ultralytics")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        bundle = build_training_bundle(
            [Path(path) for path in args.manifest],
            Path(args.outdir) / "dataset",
            validation_manifest_paths=[Path(path) for path in args.validation_manifest],
        )
        if not bundle.get("validation_ready") and not args.allow_single_scene:
            raise RuntimeError(
                "No independent held-out L1D-SR validation scene is present. Add --validation-manifest "
                "or pass --allow-single-scene to create an explicitly experimental fine-tune."
            )
        summary: dict[str, Any] = {"bundle": bundle, "prepare_only": bool(args.prepare_only)}
        if not args.prepare_only:
            summary["training"] = _train(args, bundle)
        summary_path = Path(args.outdir).expanduser().resolve() / "training_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"summary": str(summary_path), "bundle": bundle["counts"], "warnings": bundle["warnings"]}, indent=2))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
