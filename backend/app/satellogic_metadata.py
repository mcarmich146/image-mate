"""Provider metadata normalization used by archive and mosaic workflows."""

from __future__ import annotations

import re
from typing import Any, Mapping


SENSOR_GENERATIONS = ("mark-iv", "mark-v", "unknown")


def normalize_sensor_generation(value: Any) -> str:
    """Return the stable UI/API spelling for a NewSat generation."""

    token = str(value or "").strip().lower().replace("_", "-")
    token = re.sub(r"\s+", "-", token)
    if token in {"mark-iv", "mark4", "mark-4", "iv", "4", "m4"}:
        return "mark-iv"
    if token in {"mark-v", "mark5", "mark-5", "v", "5", "m5"}:
        return "mark-v"
    if "mark-v" in token or "mark5" in token or "mark-5" in token:
        return "mark-v"
    if "mark-iv" in token or "mark4" in token or "mark-4" in token:
        return "mark-iv"
    return "unknown"


def infer_sensor_generation(
    properties: Mapping[str, Any] | None,
    item_id: str | None = None,
    satellite_name: str | None = None,
    configured_map: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Infer generation only from explicit provider/configured metadata.

    GSD is intentionally not used as a generation signal.  Off-nadir angle and
    altitude make that inference unsafe for a mosaic compatibility gate.
    """

    props = properties if isinstance(properties, Mapping) else {}
    explicit_keys = (
        "satl:sensor_generation",
        "sensor_generation",
        "satl:satellite_generation",
        "satellite_generation",
        "satellite_model",
        "satl:satellite_model",
        "platform_model",
    )
    for key in explicit_keys:
        value = normalize_sensor_generation(props.get(key))
        if value != "unknown":
            return value, f"property:{key}"

    for key in ("platform", "constellation"):
        value = normalize_sensor_generation(props.get(key))
        if value != "unknown":
            return value, f"property:{key}"

    lookup = configured_map or {}
    candidates = [satellite_name, props.get("satl:satellite_name"), props.get("platform"), item_id]
    for candidate in candidates:
        token = str(candidate or "").strip()
        if not token:
            continue
        direct = normalize_sensor_generation(lookup.get(token))
        if direct != "unknown":
            return direct, f"configured:{token}"
        lowered = token.lower()
        for configured_key, configured_value in lookup.items():
            if str(configured_key).strip().lower() == lowered:
                mapped = normalize_sensor_generation(configured_value)
                if mapped != "unknown":
                    return mapped, f"configured:{configured_key}"

    return "unknown", "unresolved"


def nominal_resolution_m(collection_id: str | None, sensor_generation: str | None) -> float | None:
    """Return the documented nominal output grid for a product profile."""

    collection = str(collection_id or "").strip().lower().replace("_", "-")
    generation = normalize_sensor_generation(sensor_generation)
    if generation == "unknown":
        return None
    if collection in {"quickview-visual", "quickview-visual-thumb", "l1b", "l1b-visual"}:
        return 1.0 if generation == "mark-iv" else 0.7
    if collection in {"l1d", "l1d-toa"}:
        return 1.0 if generation == "mark-iv" else 0.7
    if collection == "l1d-sr":
        return 0.7 if generation == "mark-iv" else 0.5
    return None
