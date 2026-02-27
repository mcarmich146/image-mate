#!/usr/bin/env python3
"""Apply conservative promotion gate and update model registry."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _as_float(row: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except Exception:
        return float(default)


def _passes_conservative_gate(candidate: dict, production: dict) -> tuple[bool, list[str]]:
    reasons = []
    c_map50 = _as_float(candidate, "map50")
    p_map50 = _as_float(production, "map50")
    if c_map50 < (p_map50 - 0.01):
        reasons.append("map50 regression beyond 0.01")

    c_map5095 = _as_float(candidate, "map50_95")
    p_map5095 = _as_float(production, "map50_95")
    if c_map5095 < p_map5095:
        reasons.append("map50_95 regression")

    c_len = _as_float(candidate, "length_mae_m")
    p_len = _as_float(production, "length_mae_m")
    if c_len > (p_len + 0.5):
        reasons.append("length_mae_m regression beyond +0.5")

    c_wid = _as_float(candidate, "width_mae_m")
    p_wid = _as_float(production, "width_mae_m")
    if c_wid > (p_wid + 0.3):
        reasons.append("width_mae_m regression beyond +0.3")

    c_sanity = _as_float(candidate, "sanity_pass_rate")
    p_sanity = _as_float(production, "sanity_pass_rate")
    if c_sanity < p_sanity:
        reasons.append("sanity_pass_rate regression")

    return len(reasons) == 0, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote a candidate vessel model using conservative gate.")
    parser.add_argument("--registry-path", required=True, help="Path to models registry JSON.")
    parser.add_argument("--candidate-model-id", required=True, help="Candidate model id to evaluate for promotion.")
    parser.add_argument("--candidate-metrics-path", required=True, help="Path to candidate evaluation JSON.")
    parser.add_argument("--candidate-onnx-path", required=True, help="Path to candidate ONNX model.")
    parser.add_argument("--train-dataset-id", default="", help="Source train dataset identifier.")
    parser.add_argument("--notes", default="", help="Promotion notes.")
    args = parser.parse_args()

    registry_path = Path(str(args.registry_path)).expanduser().resolve()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_metrics_doc = _load_json(Path(str(args.candidate_metrics_path)).expanduser().resolve())
    candidate_metrics = candidate_metrics_doc.get("metrics") if isinstance(candidate_metrics_doc.get("metrics"), dict) else {}

    registry = _load_json(registry_path)
    models = registry.get("models") if isinstance(registry.get("models"), list) else []
    active_prod = str(registry.get("active_production_model_id") or "").strip()
    production_entry = None
    for row in models:
        if not isinstance(row, dict):
            continue
        if str(row.get("model_id") or "").strip() == active_prod and str(row.get("status") or "").strip() == "production":
            production_entry = row
            break

    production_metrics = production_entry.get("metrics") if isinstance(production_entry, dict) and isinstance(production_entry.get("metrics"), dict) else {}
    passes, reasons = _passes_conservative_gate(candidate_metrics, production_metrics if production_entry else {})

    model_id = str(args.candidate_model_id).strip()
    existing_candidate = None
    for row in models:
        if isinstance(row, dict) and str(row.get("model_id") or "").strip() == model_id:
            existing_candidate = row
            break
    if existing_candidate is None:
        existing_candidate = {"model_id": model_id}
        models.append(existing_candidate)

    existing_candidate["created_utc"] = str(existing_candidate.get("created_utc") or _utc_now())
    existing_candidate["train_dataset_id"] = str(args.train_dataset_id or existing_candidate.get("train_dataset_id") or "").strip()
    existing_candidate["metrics"] = dict(candidate_metrics)
    existing_candidate["onnx_path"] = str(Path(str(args.candidate_onnx_path)).expanduser().resolve())
    existing_candidate["notes"] = str(args.notes or "").strip()
    existing_candidate["updated_utc"] = _utc_now()

    if passes:
        prior_prod_id = str(registry.get("active_production_model_id") or "").strip()
        for row in models:
            if not isinstance(row, dict):
                continue
            if str(row.get("model_id") or "").strip() == prior_prod_id and str(row.get("status") or "").strip() == "production":
                row["status"] = "archived"
        existing_candidate["status"] = "production"
        existing_candidate["promoted_from"] = prior_prod_id
        registry["active_production_model_id"] = model_id
        decision = {"promoted": True, "reason": "candidate passed conservative gate"}
    else:
        existing_candidate["status"] = "candidate"
        decision = {"promoted": False, "reason": "; ".join(reasons) if reasons else "candidate did not pass gate"}

    registry["schema_version"] = int(registry.get("schema_version") or 1)
    registry["models"] = models
    registry["last_decision"] = {
        "candidate_model_id": model_id,
        "timestamp_utc": _utc_now(),
        **decision,
    }
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    print(json.dumps(registry["last_decision"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
