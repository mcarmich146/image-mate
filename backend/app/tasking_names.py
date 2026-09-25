"""Canonical naming for provider-facing Satellogic tasking orders."""

from __future__ import annotations

import re


TASKING_NAME_PREFIX = "Mark - "
_PREFIX_RE = re.compile(r"^\s*mark\s*(?:-|—|:)\s*", re.IGNORECASE)


def normalize_tasking_name(value: str, *, max_length: int = 120) -> str:
    """Return the canonical, idempotently prefixed provider order name."""

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Tasking order name is required")
    # Remove any prior canonical or legacy Mark prefix before applying the
    # selected delimiter. This prevents Mark - Mark - ... on retries or
    # when a plan created under an older skill is submitted later.
    while True:
        normalized = _PREFIX_RE.sub("", raw, count=1).strip()
        if normalized == raw:
            break
        raw = normalized
    result = f"{TASKING_NAME_PREFIX}{raw}"
    if len(result) > max_length:
        raise ValueError(f"Tasking order name exceeds the {max_length}-character limit after Mark prefix")
    return result
