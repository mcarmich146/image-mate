# -*- coding: utf-8 -*-
"""Helpers for resolving Mosaic tracking preview candidates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


DEFAULT_PREVIEW_COLLECTION_CANDIDATES = (
    "l1d-sr",
    "quickview-visual",
    "quickview-visual-thumb",
)

_ITEM_ID_HINT_KEYS = {
    "item_id",
    "itemid",
    "scene_id",
    "sceneid",
    "image_id",
    "imageid",
    "stac_item_id",
    "stacitemid",
    "result_item_id",
    "resultitemid",
    "acquisition_id",
    "acquisitionid",
    "delivery_item_id",
    "deliveryitemid",
}

_COLLECTION_HINT_KEYS = {
    "collection",
    "collection_id",
    "collectionid",
    "collections",
    "stac_collection",
    "stac_collection_id",
}

_DATETIME_HINT_KEYS = {
    "start",
    "end",
    "start_date",
    "end_date",
    "created",
    "created_at",
    "updated",
    "updated_at",
    "completed_at",
    "acquired_at",
    "datetime",
}


def is_completed_status(api_status: str | None) -> bool:
    """Return True when API status allows operator preview."""
    return str(api_status or "").strip().lower() == "completed"


def should_enable_preview(*, api_status: str | None, latest_collection_id: str | None) -> bool:
    """Enable preview only for completed rows with an order/collection id."""
    if not is_completed_status(api_status):
        return False
    return bool(str(latest_collection_id or "").strip())


def preview_item_id_candidates(tasking_detail: dict[str, Any] | None) -> list[str]:
    """Extract likely STAC item ids from tasking order payloads."""
    payload = tasking_detail if isinstance(tasking_detail, dict) else {}
    order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}

    out: list[str] = []
    seen: set[str] = set()

    def add_value(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    def walk(node: Any, *, parent_key: str = "", depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                key_norm = str(key or "").strip().lower()
                if key_norm in _ITEM_ID_HINT_KEYS:
                    add_value(value)
                elif key_norm == "id" and any(
                    token in parent_key for token in ("item", "scene", "result", "acquisition", "delivery", "feature")
                ):
                    add_value(value)
                walk(value, parent_key=key_norm, depth=depth + 1)
            return
        if isinstance(node, list):
            for row in node[:100]:
                walk(row, parent_key=parent_key, depth=depth + 1)

    walk(raw)
    walk(order)
    # Some APIs expose item ids directly under normalized order-level fields.
    for key in ("item_id", "scene_id", "stac_item_id", "result_item_id"):
        add_value(order.get(key))
    return out


def preview_collection_candidates(tasking_detail: dict[str, Any] | None) -> list[str]:
    """Resolve collection ids to query when item-id resolution is unavailable."""
    payload = tasking_detail if isinstance(tasking_detail, dict) else {}
    order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}

    out: list[str] = []
    seen: set[str] = set()

    def add_collection(value: Any) -> None:
        normalized = normalize_collection_id(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        out.append(normalized)

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                key_norm = str(key or "").strip().lower()
                if key_norm in _COLLECTION_HINT_KEYS:
                    if isinstance(value, list):
                        for row in value:
                            add_collection(row)
                    else:
                        add_collection(value)
                walk(value, depth + 1)
            return
        if isinstance(node, list):
            for row in node[:80]:
                walk(row, depth + 1)

    walk(raw)
    walk(order)
    for value in DEFAULT_PREVIEW_COLLECTION_CANDIDATES:
        add_collection(value)
    return out


def preview_search_window(
    tasking_detail: dict[str, Any] | None,
    *,
    now_utc: datetime | None = None,
) -> tuple[str, str]:
    """Build a pragmatic STAC datetime window for completed tasking previews."""
    payload = tasking_detail if isinstance(tasking_detail, dict) else {}
    order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}

    datetimes: list[datetime] = []

    def add_datetime(value: Any) -> None:
        parsed = parse_iso_datetime(value)
        if parsed is not None:
            datetimes.append(parsed)

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 4:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                key_norm = str(key or "").strip().lower()
                if key_norm in _DATETIME_HINT_KEYS:
                    add_datetime(value)
                walk(value, depth + 1)
            return
        if isinstance(node, list):
            for row in node[:80]:
                walk(row, depth + 1)

    walk(order)
    walk(raw)

    if datetimes:
        start_dt = min(datetimes) - timedelta(hours=12)
        end_dt = max(datetimes) + timedelta(days=7)
    else:
        reference = now_utc if isinstance(now_utc, datetime) else datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        else:
            reference = reference.astimezone(timezone.utc)
        start_dt = reference - timedelta(days=30)
        end_dt = reference + timedelta(days=1)

    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt
    return to_utc_iso(start_dt), to_utc_iso(end_dt)


def extract_order_geometry(tasking_detail: dict[str, Any] | None) -> dict[str, Any]:
    """Extract tasking geometry for STAC search intersects."""
    payload = tasking_detail if isinstance(tasking_detail, dict) else {}
    order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
    raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}

    for candidate in (
        order.get("geometry"),
        raw.get("geometry"),
        order.get("target_geometry"),
        raw.get("target_geometry"),
    ):
        if isinstance(candidate, dict) and str(candidate.get("type") or "").strip():
            return candidate

    params = order.get("parameters") if isinstance(order.get("parameters"), dict) else {}
    for key in ("geometry", "target_geometry", "target", "intersects"):
        candidate = params.get(key)
        if isinstance(candidate, dict) and str(candidate.get("type") or "").strip():
            return candidate
    return {}


def normalize_collection_id(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if not raw:
        return ""
    if raw in {"l1d", "l1d-sr", "l1dsr"}:
        return "l1d-sr"
    if "quickview" in raw and "thumb" in raw:
        return "quickview-visual-thumb"
    if "quickview" in raw:
        return "quickview-visual"
    if raw.startswith("tsk"):
        return ""
    return raw


def parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            parsed = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            parsed = datetime.fromisoformat(text)
    except Exception:
        if len(text) == 10:
            try:
                parsed = datetime.fromisoformat(text + "T00:00:00+00:00")
            except Exception:
                return None
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_utc_iso(value: datetime) -> str:
    dt = value if isinstance(value, datetime) else datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")
