from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import threading
from typing import Any, Callable
from urllib.parse import urlencode

from .notifications import send_archive_watch_email


logger = logging.getLogger("image_mate.archive_watch")


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def validate_watch_geometry(geometry: dict[str, Any]) -> None:
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise ValueError("Archive watches require a Polygon or MultiPolygon geometry")
    coordinates = geometry.get("coordinates")
    if not coordinates:
        raise ValueError("Archive watch geometry must contain coordinates")
    try:
        from shapely.geometry import shape

        candidate = shape(geometry)
        if candidate.is_empty or not candidate.is_valid:
            raise ValueError("Archive watch polygon is empty or invalid")
    except ImportError:
        # Shapely is a project dependency, but retain a light fallback so the
        # API can still reject obviously empty input in minimal installations.
        if not isinstance(coordinates, list) or len(coordinates) < 1:
            raise ValueError("Archive watch geometry must contain coordinates")


def _item_key(item: dict[str, Any], watch: dict[str, Any]) -> str:
    source = str(item.get("source_id") or watch.get("source_id") or "source").strip()
    collection = str(item.get("collection") or watch.get("collection_id") or "collection").strip()
    identity = str(item.get("outcome_id") or item.get("id") or "").strip()
    return f"{source}|{collection}|{identity}" if identity else ""


def _item_summary(item: dict[str, Any], watch: dict[str, Any], public_base_url: str) -> dict[str, Any]:
    source_id = str(item.get("source_id") or watch.get("source_id") or "satellogic")
    collection_id = str(item.get("collection") or watch.get("collection_id") or "")
    item_id = str(item.get("id") or item.get("item_id") or "")
    query = {
        "item_id": item_id,
        "asset_key": "thumbnail",
        "source_id": source_id,
        "collection_id": collection_id,
    }
    contract_id = str(watch.get("contract_id") or "").strip()
    if contract_id:
        query["contract_id"] = contract_id
    preview_url = f"{str(public_base_url or 'http://127.0.0.1:8000').rstrip('/')}/api/archive/preview?{urlencode(query)}"
    return {
        "item_key": _item_key(item, watch),
        "item_id": item_id,
        "id": item_id,
        "source_id": source_id,
        "collection": collection_id,
        "datetime": item.get("datetime"),
        "outcome_id": item.get("outcome_id"),
        "satellite_name": item.get("satellite_name"),
        "sensor_generation": item.get("sensor_generation"),
        "gsd": item.get("gsd"),
        "cloud_cover": item.get("cloud_cover"),
        "geometry": item.get("geometry") or {},
        "preview_url": preview_url,
        "image_url": preview_url,
    }


class ArchiveWatchService:
    def __init__(self, store: Any, sources: Any, settings: Any, email_sender: Callable[..., dict[str, Any]] = send_archive_watch_email):
        self.store = store
        self.sources = sources
        self.settings = settings
        self.email_sender = email_sender

    def check_watch(
        self,
        watch_id: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 300,
    ) -> dict[str, Any]:
        watch = self.store.get_archive_watch(watch_id)
        if not watch:
            raise KeyError("Archive watch not found")
        now = utc_now()
        end = parse_datetime(end_date) or now
        previous = parse_datetime(watch.get("last_checked_at"))
        # A small overlap accounts for provider indexing lag between polls;
        # the item table makes that overlap idempotent.
        start = parse_datetime(start_date) or (
            (previous - timedelta(hours=6)) if previous else now - timedelta(hours=int(self.settings.archive_watch_default_lookback_hours))
        )
        if start >= end:
            start = end - timedelta(hours=1)

        filters = dict(watch.get("filters") or {})
        items = self.sources.search(
            source_id=watch.get("source_id"),
            geometry=watch.get("geometry") or {},
            start_date=iso_z(start),
            end_date=iso_z(end),
            collection_id=str(watch.get("collection_id") or ""),
            contract_id=watch.get("contract_id"),
            limit=max(1, min(int(limit), 1000)),
            max_cloud_cover=filters.get("max_cloud_cover"),
            satellite_name=filters.get("satellite_name"),
            min_gsd=filters.get("min_gsd"),
            max_gsd=filters.get("max_gsd"),
            sensor_generation=filters.get("sensor_generation"),
        )
        summaries = [_item_summary(item, watch, self.settings.public_base_url) for item in (items or []) if isinstance(item, dict)]
        summaries = [item for item in summaries if item.get("item_key")]
        newly_seen = self.store.record_archive_watch_items(watch_id, summaries)
        pending = self.store.list_pending_archive_watch_items(watch_id, limit=5000)
        pending_summaries = [_item_summary(item, watch, self.settings.public_base_url) for item in pending]
        pending_summaries = [item for item in pending_summaries if item.get("item_key")]

        email_result: dict[str, Any] = {"status": "none", "count": 0, "recipients": []}
        email_error: str | None = None
        email_at: str | None = None
        if pending_summaries:
            try:
                email_result = self.email_sender(watch, pending_summaries, self.settings)
                if email_result.get("status") == "sent":
                    self.store.mark_archive_watch_items_notified(
                        watch_id,
                        [str(item.get("item_key")) for item in pending_summaries],
                        notified_at=iso_z(now),
                    )
                    email_at = iso_z(now)
            except Exception as exc:  # SMTP failure should not discard pending items.
                email_error = str(exc)
                email_result = {"status": "failed", "count": len(pending_summaries), "recipients": []}
                logger.warning("archive watch email failed watch=%s error=%s", watch_id, exc)

        status = str(email_result.get("status") or "none")
        error = email_error or ("Email delivery is not configured" if status == "not_configured" else None)
        saved = self.store.save_archive_watch_check(
            watch_id,
            checked_at=iso_z(now),
            success=True,
            error=error,
            email_at=email_at,
            new_count=len(newly_seen),
        )
        if newly_seen or email_error:
            self.store.create_event(
                {
                    "subscription_id": watch_id,
                    "source_id": watch.get("source_id"),
                    "event_type": "archive.imagery_arrived",
                    "status": "email_failed" if email_error else status,
                    "payload": {
                        "watch_id": watch_id,
                        "watch_name": watch.get("name"),
                        "new_count": len(newly_seen),
                        "pending_count": len(pending_summaries),
                        "email": email_result,
                        "items": pending_summaries[:100],
                    },
                }
            )
        return {
            "watch": saved or watch,
            "checked_at": iso_z(now),
            "window": {"start_date": iso_z(start), "end_date": iso_z(end)},
            "searched_count": len(summaries),
            "new_count": len(newly_seen),
            "new_items": [_item_summary(item, watch, self.settings.public_base_url) for item in newly_seen],
            "pending_count": len(pending_summaries) if status != "sent" else 0,
            "email": email_result,
            "error": error,
        }


class ArchiveWatchPoller:
    def __init__(self, service: ArchiveWatchService, interval_seconds: int = 300):
        self.service = service
        self.interval_seconds = max(15, int(interval_seconds or 300))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="image-mate-archive-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        # Do not hit external archive APIs during application startup. The
        # first pass occurs after the configured interval or via the UI/API.
        while not self._stop.wait(self.interval_seconds):
            for watch in self.service.store.list_archive_watches(enabled_only=True):
                last_checked = parse_datetime(watch.get("last_checked_at"))
                if last_checked and (utc_now() - last_checked).total_seconds() < float(watch.get("poll_interval_seconds") or self.interval_seconds):
                    continue
                try:
                    self.service.check_watch(watch["watch_id"])
                except Exception as exc:
                    logger.warning("archive watch poll failed watch=%s error=%s", watch.get("watch_id"), exc)
