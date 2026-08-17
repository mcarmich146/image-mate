"""Few-shot aircraft/ helicopter review through the Hermes Luna route.

The Luna lane is deliberately a reviewer, not a label authority.  Human labels
stored in an aircraft review manifest are the only labels exported to training.
This module turns those confirmed examples into a deterministic few-shot prompt,
records Luna's independent assessment, and keeps all model access outside the
Image Mate container's GPU-bound inference path.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterable


LUNA_LABELS = ("plane", "helicopter", "background", "unsure")
_LABEL_ALIASES = {
    "aircraft": "plane",
    "fixed-wing": "plane",
    "fixed_wing": "plane",
    "none": "background",
    "no-detection": "background",
    "no_detection": "background",
    "unknown": "unsure",
    "skip": "unsure",
}


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the outermost JSON object from a model response."""

    cleaned = str(text or "").strip()
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    sources = fenced or [cleaned]
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for source in sources:
        for match in re.finditer(r"\{", source):
            start = match.start()
            try:
                value, end = decoder.raw_decode(source[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                candidates.append((start, start + end, value))
    outer = [
        value
        for start, end, value in candidates
        if not any(other_start < start and end <= other_end for other_start, other_end, _ in candidates)
    ]
    if not outer:
        raise ValueError("Luna output did not contain a JSON object")
    return outer[-1]


def normalize_luna_label(value: Any) -> str:
    token = str(value or "").strip().lower().replace(" ", "-")
    token = _LABEL_ALIASES.get(token, token)
    return token if token in LUNA_LABELS else "unsure"


def _safe_confidence(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return max(0.0, min(1.0, number))


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _safe_example_id(manifest_path: Path, candidate: dict[str, Any]) -> str:
    source = str(candidate.get("source_item_id") or candidate.get("item_id") or manifest_path.stem)
    candidate_id = str(candidate.get("candidate_id") or "candidate")
    raw = f"{source}:{candidate_id}"
    return re.sub(r"[^A-Za-z0-9_.:-]+", "-", raw).strip("-")


def build_luna_examples(
    manifest_paths: Iterable[Path],
    *,
    max_per_label: int = 12,
    labels: Iterable[str] = ("plane", "helicopter", "background"),
) -> dict[str, Any]:
    """Build a reusable, human-confirmed few-shot example manifest."""

    paths = [Path(path).expanduser().resolve() for path in manifest_paths]
    if not paths:
        raise ValueError("At least one review manifest is required")
    allowed = {normalize_luna_label(label) for label in labels}
    allowed.discard("unsure")
    limit = max(1, min(100, int(max_per_label)))
    counts = {label: 0 for label in sorted(allowed)}
    examples: list[dict[str, Any]] = []
    for manifest_path in paths:
        manifest = _load_json(manifest_path)
        source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        item_id = str(source.get("item_id") or "").strip()
        if not item_id:
            raise ValueError(f"Example manifest has no source item_id: {manifest_path}")
        if str(source.get("collection_id") or "").strip().lower().replace("_", "-") != "l1d-sr":
            raise ValueError("Luna aircraft examples accept only Satellogic l1d-sr manifests")
        candidates = manifest.get("candidates") if isinstance(manifest.get("candidates"), list) else []
        for candidate in sorted(candidates, key=lambda row: str(row.get("candidate_id") or "")):
            label = normalize_luna_label(candidate.get("label"))
            if label not in allowed or counts.get(label, 0) >= limit:
                continue
            chip_path = manifest_path.parent / str(candidate.get("chip_path") or "")
            if not chip_path.is_file():
                raise ValueError(f"Confirmed Luna example chip is missing: {chip_path}")
            counts[label] = counts.get(label, 0) + 1
            examples.append(
                {
                    "example_id": _safe_example_id(manifest_path, {**candidate, "source_item_id": item_id}),
                    "label": label,
                    "candidate_id": str(candidate.get("candidate_id") or ""),
                    "source_item_id": item_id,
                    "chip_path": str(chip_path),
                    "proposed_class": candidate.get("proposed_class"),
                }
            )
    if not examples:
        raise ValueError("No confirmed plane, helicopter, or background examples were found")
    return {
        "schema_version": "aircraft-luna-examples.v1",
        "purpose": "human-confirmed-few-shot-aircraft-review",
        "labels": sorted(allowed),
        "max_per_label": limit,
        "counts": counts,
        "examples": examples,
    }


def build_aircraft_prompt(*, target: dict[str, Any], examples: list[dict[str, Any]], model: str) -> str:
    example_lines = []
    for index, example in enumerate(examples, start=1):
        example_lines.append(
            f"Example {index}: confirmed_label={example.get('label')} "
            f"source_scene={example.get('source_item_id')}"
        )
    return f"""You are reviewing one high-resolution Satellogic L1D-SR image chip for an aircraft detector.

MODEL
{model}

TASK
Classify only the object centered in the target chip as one of: plane, helicopter, background, unsure.
Use the confirmed examples as visual calibration, not as a reason to force a match.

RULES
- A plane means a fixed-wing aircraft silhouette. A helicopter means a rotorcraft silhouette.
- Use background when the proposed object is not a visible aircraft or helicopter.
- Use unsure when the chip is too small, occluded, shadowed, blurred, or otherwise ambiguous.
- Do not identify a specific aircraft, unit, base, activity, intent, or operational status.
- Do not treat the detector's proposed class or confidence as ground truth.
- Return JSON only. Do not include markdown fences.

CONFIRMED FEW-SHOT EXAMPLES (attached before the target image)
{chr(10).join(example_lines) or "No examples supplied."}

TARGET METADATA
{json.dumps(target, indent=2, sort_keys=True)}

RETURN EXACTLY THIS SHAPE
{{"label":"plane|helicopter|background|unsure","confidence":0.0,"rationale":"short visible-evidence explanation","edge_case":true,"needs_human_review":true}}
"""


def _data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/tiff"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


@dataclass
class LunaAircraftEvaluator:
    """Call Luna through Hermes by default, with an explicit API fallback."""

    model: str | None = None
    transport: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    hermes_bin: str | None = None
    timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        self.model = self.model or os.getenv("IMAGE_MATE_LUNA_MODEL", "gpt-5.6-luna")
        self.transport = (self.transport or os.getenv("IMAGE_MATE_LUNA_TRANSPORT", "hermes")).strip().lower()
        self.api_key = self.api_key or os.getenv("IMAGE_MATE_LUNA_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = self.base_url or os.getenv("IMAGE_MATE_LUNA_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        self.hermes_bin = self.hermes_bin or os.getenv("IMAGE_MATE_LUNA_HERMES_BIN", "/Users/mark/.hermes/bin/hermes")
        self.timeout_seconds = int(self.timeout_seconds or os.getenv("IMAGE_MATE_LUNA_TIMEOUT", "900"))
        self._client: Any = None

    @property
    def configured(self) -> bool:
        if self.transport == "hermes":
            return Path(str(self.hermes_bin)).expanduser().is_file()
        return bool(self.api_key)

    def _complete_hermes(self, prompt: str, image_paths: list[Path]) -> dict[str, Any]:
        command = [
            str(Path(str(self.hermes_bin)).expanduser()),
            "chat",
            "-q",
            prompt,
            "-m",
            str(self.model),
            "--reasoning",
            "none",
            "-Q",
            "--source",
            "image-mate-aircraft",
        ]
        for image_path in image_paths:
            command.extend(["--image", str(image_path)])
        env = os.environ.copy()
        env.setdefault("HERMES_HOME", "/Users/mark/.hermes")
        completed = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            timeout=max(30, int(self.timeout_seconds or 900)),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("Hermes Luna invocation failed")
        return extract_json_object(completed.stdout)

    def _client_or_raise(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise RuntimeError("Luna API transport is not configured")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional import guard
            raise RuntimeError("OpenAI SDK is required for API-based Luna review") from exc
        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = OpenAI(**kwargs)
        return self._client

    def _complete_api(self, prompt: str, image_paths: list[Path]) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend({"type": "image_url", "image_url": {"url": _data_url(path)}} for path in image_paths)
        response = self._client_or_raise().chat.completions.create(
            model=str(self.model),
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
        )
        return extract_json_object(response.choices[0].message.content or "{}")

    def evaluate(self, *, target: dict[str, Any], target_path: Path, examples: list[dict[str, Any]]) -> dict[str, Any]:
        example_paths = [Path(str(example["chip_path"])).expanduser().resolve() for example in examples]
        prompt = build_aircraft_prompt(target=target, examples=examples, model=str(self.model))
        raw = self._complete_hermes(prompt, example_paths + [target_path]) if self.transport == "hermes" else self._complete_api(prompt, example_paths + [target_path])
        return {
            "status": "complete",
            "model": str(self.model),
            "transport": str(self.transport),
            "label": normalize_luna_label(raw.get("label")),
            "confidence": _safe_confidence(raw.get("confidence")),
            "rationale": str(raw.get("rationale") or "").strip()[:1000],
            "edge_case": bool(raw.get("edge_case")),
            "needs_human_review": bool(raw.get("needs_human_review", True)),
            "example_ids": [str(example.get("example_id") or "") for example in examples],
            "raw_fields": {
                "label": raw.get("label"),
                "confidence": raw.get("confidence"),
            },
        }


def run_luna_evaluations(
    manifest_path: Path,
    examples: dict[str, Any],
    *,
    candidate_ids: Iterable[str] | None = None,
    limit: int | None = None,
    evaluator: LunaAircraftEvaluator | None = None,
) -> dict[str, Any]:
    """Evaluate candidates and append auditable Luna events to the manifest."""

    manifest_path = Path(manifest_path).expanduser().resolve()
    manifest = _load_json(manifest_path)
    candidates = manifest.get("candidates") if isinstance(manifest.get("candidates"), list) else []
    requested = {str(value).strip() for value in (candidate_ids or []) if str(value).strip()}
    selected = [candidate for candidate in candidates if not requested or str(candidate.get("candidate_id")) in requested]
    if not requested:
        selected = [candidate for candidate in selected if candidate.get("label") is None]
    if limit is not None:
        selected = selected[: max(1, int(limit))]
    example_rows = examples.get("examples") if isinstance(examples.get("examples"), list) else []
    if not example_rows:
        raise ValueError("Luna evaluation requires at least one confirmed example")
    evaluator = evaluator or LunaAircraftEvaluator()
    events_path = manifest_path.parent / "luna_evaluations.jsonl"
    results: list[dict[str, Any]] = []
    for candidate in selected:
        candidate_id = str(candidate.get("candidate_id") or "")
        # Luna sees the clean chip; the human-facing review overlay would leak
        # the proposal geometry and can bias a class judgment.
        target_path = manifest_path.parent / str(candidate.get("chip_path") or candidate.get("review_chip_path") or "")
        event: dict[str, Any] = {
            "schema_version": "aircraft-luna-evaluation.v1",
            "candidate_id": candidate_id,
            "source_item_id": str((manifest.get("source") or {}).get("item_id") or ""),
            "model": str(evaluator.model),
            "transport": str(evaluator.transport),
            "target_path": str(target_path),
        }
        try:
            if not target_path.is_file():
                raise ValueError(f"Luna target chip is missing: {target_path}")
            evaluation = evaluator.evaluate(
                target={
                    "candidate_id": candidate_id,
                    "proposed_class": candidate.get("proposed_class"),
                    "detector_confidence": candidate.get("confidence"),
                    "source_item_id": event["source_item_id"],
                },
                target_path=target_path,
                examples=[example for example in example_rows if str(example.get("candidate_id")) != candidate_id],
            )
            event.update(evaluation)
            candidate["luna_evaluation"] = evaluation
        except Exception as exc:
            event.update({"status": "error", "error": str(exc)[:400]})
            candidate["luna_evaluation"] = {"status": "error", "error": str(exc)[:400]}
        results.append(event)
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    manifest["luna"] = {
        "model": str(evaluator.model),
        "transport": str(evaluator.transport),
        "example_manifest": examples.get("schema_version"),
        "evaluated_count": len(results),
    }
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(manifest_path)
    return {
        "manifest": str(manifest_path),
        "events": str(events_path),
        "evaluated": len(results),
        "complete": sum(1 for row in results if row.get("status") == "complete"),
        "errors": sum(1 for row in results if row.get("status") == "error"),
        "results": results,
    }
