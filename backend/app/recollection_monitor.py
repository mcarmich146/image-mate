from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _parse_iso(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _observation_from_item(item: dict[str, Any]) -> dict[str, Any]:
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    assets = item.get("assets") if isinstance(item.get("assets"), dict) else {}
    # Keep signed asset URLs out of persisted monitoring state. They are returned
    # to the UI only for the current refresh response.
    return {
        "scene_id": str(item.get("id") or ""),
        "outcome_id": str(item.get("outcome_id") or props.get("satl:outcome_id") or item.get("id") or ""),
        "datetime": item.get("datetime") or props.get("datetime"),
        "cloud_cover": item.get("cloud_cover", props.get("eo:cloud_cover")),
        "gsd": item.get("gsd", props.get("gsd")),
        "satellite_name": item.get("satellite_name") or props.get("platform"),
        "valid_pixel_percent": item.get("valid_pixel_percent", props.get("satl:valid_pixel")),
        "geometry": item.get("geometry"),
        "collection": item.get("collection"),
        "assets": {
            "thumbnail": assets.get("thumbnail") or "",
            "preview": assets.get("preview") or "",
        },
    }


def _row_status(row: dict[str, Any]) -> str:
    props = row.get("properties") if isinstance(row.get("properties"), dict) else row
    return str(props.get("status") or props.get("state") or "").strip().lower()


def _lifecycle_summary(lifecycle: dict[str, Any]) -> dict[str, Any]:
    captures = lifecycle.get("captures") if isinstance(lifecycle.get("captures"), list) else []
    deliverables = lifecycle.get("deliverables") if isinstance(lifecycle.get("deliverables"), list) else []
    capture_statuses = sorted({status for status in (_row_status(row) for row in captures) if status})
    deliverable_statuses = sorted({status for status in (_row_status(row) for row in deliverables) if status})
    order = lifecycle.get("order") if isinstance(lifecycle.get("order"), dict) else {}
    tasking_status = str(lifecycle.get("rollup_status") or order.get("status") or "unverified").strip().lower()
    if not tasking_status:
        tasking_status = "unverified"
    if not deliverable_statuses:
        deliverable_status = "checked_none"
    elif any(status in {"failed", "not_delivered", "not delivered", "rejected", "error"} for status in deliverable_statuses):
        deliverable_status = "failed"
    elif all(status in {"delivered", "complete", "completed"} for status in deliverable_statuses):
        deliverable_status = "delivered"
    elif any(status in {"processing", "queued"} for status in deliverable_statuses):
        deliverable_status = "processing"
    else:
        deliverable_status = deliverable_statuses[0]
    return {
        "order_id": lifecycle.get("order_id"),
        "tasking_status": tasking_status,
        "capture_status": capture_statuses[0] if len(capture_statuses) == 1 else ("mixed" if capture_statuses else "checked_none"),
        "capture_statuses": capture_statuses,
        "deliverable_status": deliverable_status,
        "deliverable_statuses": deliverable_statuses,
        "latest_event": (lifecycle.get("events") or [{}])[-1].get("type") if lifecycle.get("events") else None,
        "checked_at": lifecycle.get("checked_at"),
    }


def refresh_recollection_monitor(
    store: Any,
    sources: Any,
    monitor_id: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 300,
    tasking_lifecycle_fn: Any | None = None,
) -> dict[str, Any]:
    monitor = store.get_recollection_monitor(monitor_id)
    if not monitor:
        raise KeyError("Recollection monitor not found")
    if not monitor.get("enabled", True):
        raise ValueError("Recollection monitor is disabled")
    source_id = str(monitor.get("source_id") or "satellogic")
    if not sources.has_source(source_id):
        raise ValueError(f"Unknown source_id '{source_id}'")

    now = datetime.now(timezone.utc)
    filters = dict(monitor.get("filters") or {})
    expected_days = monitor.get("expected_revisit_days")
    previous = monitor.get("observations") or []
    seen_outcomes = {str(row.get("outcome_id")) for row in previous if row.get("outcome_id")}
    end_dt = _parse_iso(end_date) or now
    start_dt = _parse_iso(start_date)
    if not start_dt:
        last_dt = _parse_iso((monitor.get("summary") or {}).get("latest_capture_at"))
        lookback_days = max(float(expected_days or 90) * 2.0, 30.0)
        start_dt = last_dt - timedelta(days=lookback_days) if last_dt else end_dt - timedelta(days=lookback_days)

    items = sources.search(
        source_id=source_id,
        geometry=monitor.get("geometry") or {},
        start_date=_iso(start_dt),
        end_date=_iso(end_dt),
        collection_id=str(monitor.get("collection_id") or "quickview-visual-thumb"),
        contract_id=monitor.get("contract_id"),
        limit=max(1, min(int(limit), 1000)),
        max_cloud_cover=filters.get("max_cloud_cover"),
        satellite_name=filters.get("satellite_name"),
        min_gsd=filters.get("min_gsd"),
        max_gsd=filters.get("max_gsd"),
    )

    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        observation = _observation_from_item(item)
        key = observation["outcome_id"] or observation["scene_id"]
        if not key:
            continue
        current = deduped.get(key)
        if not current or str(observation.get("datetime") or "") < str(current.get("datetime") or ""):
            deduped[key] = observation
    for previous_row in previous:
        if not isinstance(previous_row, dict):
            continue
        key = str(previous_row.get("outcome_id") or previous_row.get("scene_id") or "")
        if key and key not in deduped:
            deduped[key] = previous_row
    observations = sorted(deduped.values(), key=lambda row: str(row.get("datetime") or ""), reverse=True)
    new_observations = [row for row in deduped.values() if row.get("outcome_id") not in seen_outcomes]
    latest = observations[0].get("datetime") if observations else (monitor.get("summary") or {}).get("latest_capture_at")
    latest_dt = _parse_iso(latest)
    overdue = bool(expected_days and latest_dt and (now - latest_dt).total_seconds() > float(expected_days) * 86400)
    lifecycle_info: dict[str, Any] | None = None
    tasking_status = "not_checked"
    capture_status = "not_checked"
    deliverable_status = "not_checked"
    tasking_error: str | None = None
    if monitor.get("linked_order_id"):
        if tasking_lifecycle_fn is None:
            tasking_status = "unverified"
            tasking_error = "No tasking lifecycle checker is configured"
        else:
            try:
                lifecycle_info = _lifecycle_summary(
                    tasking_lifecycle_fn(str(monitor["linked_order_id"]), monitor.get("contract_id"))
                )
                tasking_status = str(lifecycle_info.get("tasking_status") or "unverified")
                capture_status = str(lifecycle_info.get("capture_status") or "checked_none")
                deliverable_status = str(lifecycle_info.get("deliverable_status") or "checked_none")
            except Exception as exc:
                tasking_status = "unverified"
                tasking_error = str(exc)
    summary = {
        "archive_status": "overdue" if overdue else ("captured" if observations else "no_capture_found"),
        "tasking_status": tasking_status,
        "capture_status": capture_status,
        "deliverable_status": deliverable_status,
        "tasking_checked_at": (lifecycle_info or {}).get("checked_at"),
        "tasking_error": tasking_error,
        "observations_count": len(observations),
        "new_observations": len(new_observations),
        "latest_capture_at": latest,
        "last_refresh_at": _iso(now),
        "expected_revisit_days": expected_days,
        "health": "attention" if overdue else ("healthy" if observations else "unknown"),
        "search_window": {"start": _iso(start_dt), "end": _iso(end_dt)},
    }
    persisted = []
    for row in observations:
        saved = dict(row)
        saved["assets"] = {}
        persisted.append(saved)
    saved_monitor = store.save_recollection_refresh(monitor_id, persisted, summary)
    return {
        "monitor_id": monitor_id,
        "summary": summary,
        "observations": observations,
        "tasking_lifecycle": lifecycle_info,
        "monitor": saved_monitor,
    }
