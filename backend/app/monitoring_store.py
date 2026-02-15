from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import sqlite3
import threading
import uuid


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class MonitoringStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS monitoring_subscriptions (
                        subscription_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        name TEXT,
                        collection_ids_json TEXT NOT NULL,
                        geometry_json TEXT NOT NULL,
                        filters_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        external_subscription_id TEXT,
                        cursor TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS monitoring_events (
                        event_id TEXT PRIMARY KEY,
                        subscription_id TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        scene_id TEXT,
                        event_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cue_tasks (
                        cue_id TEXT PRIMARY KEY,
                        event_id TEXT,
                        source_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        priority TEXT NOT NULL,
                        geometry_json TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()

    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        subscription_id = f"msub.{uuid.uuid4()}"
        row = {
            "subscription_id": subscription_id,
            "source_id": str(payload.get("source_id") or "merlin-s2"),
            "name": str(payload.get("name") or "").strip() or None,
            "collection_ids_json": json.dumps(payload.get("collection_ids") or [], ensure_ascii=True),
            "geometry_json": json.dumps(payload.get("geometry") or {}, ensure_ascii=True),
            "filters_json": json.dumps(payload.get("filters") or {}, ensure_ascii=True),
            "status": "ACTIVE" if bool(payload.get("enabled", True)) else "PAUSED",
            "external_subscription_id": payload.get("external_subscription_id"),
            "cursor": payload.get("cursor"),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO monitoring_subscriptions (
                        subscription_id, source_id, name, collection_ids_json, geometry_json, filters_json,
                        status, external_subscription_id, cursor, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["subscription_id"],
                        row["source_id"],
                        row["name"],
                        row["collection_ids_json"],
                        row["geometry_json"],
                        row["filters_json"],
                        row["status"],
                        row["external_subscription_id"],
                        row["cursor"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )
                conn.commit()
        return self._deserialize_subscription(row)

    def list_subscriptions(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM monitoring_subscriptions
                    ORDER BY created_at DESC
                    """
                ).fetchall()
        return [self._deserialize_subscription(dict(row)) for row in rows]

    def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        event_id = f"mev.{uuid.uuid4()}"
        row = {
            "event_id": event_id,
            "subscription_id": str(payload.get("subscription_id") or ""),
            "source_id": str(payload.get("source_id") or "merlin-s2"),
            "scene_id": payload.get("scene_id"),
            "event_type": str(payload.get("event_type") or "change.candidate"),
            "status": str(payload.get("status") or "open"),
            "payload_json": json.dumps(payload.get("payload") or {}, ensure_ascii=True),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO monitoring_events (
                        event_id, subscription_id, source_id, scene_id, event_type, status, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["event_id"],
                        row["subscription_id"],
                        row["source_id"],
                        row["scene_id"],
                        row["event_type"],
                        row["status"],
                        row["payload_json"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )
                conn.commit()
        return self._deserialize_event(row)

    def list_events(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        limit_n = max(1, min(int(limit), 1000))
        with self._lock:
            with self._connect() as conn:
                if status:
                    rows = conn.execute(
                        """
                        SELECT *
                        FROM monitoring_events
                        WHERE status = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (status, limit_n),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT *
                        FROM monitoring_events
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (limit_n,),
                    ).fetchall()
        return [self._deserialize_event(dict(row)) for row in rows]

    def ack_event(self, event_id: str, status: str = "acked") -> dict[str, Any] | None:
        now = utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE monitoring_events
                    SET status = ?, updated_at = ?
                    WHERE event_id = ?
                    """,
                    (status, now, event_id),
                )
                row = conn.execute("SELECT * FROM monitoring_events WHERE event_id = ?", (event_id,)).fetchone()
                conn.commit()
        if not row:
            return None
        return self._deserialize_event(dict(row))

    def create_cue(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        cue_id = f"cue.{uuid.uuid4()}"
        row = {
            "cue_id": cue_id,
            "event_id": payload.get("event_id"),
            "source_id": str(payload.get("source_id") or "merlin-s2"),
            "status": str(payload.get("status") or "queued_review"),
            "priority": str(payload.get("priority") or "medium"),
            "geometry_json": json.dumps(payload.get("geometry") or {}, ensure_ascii=True),
            "payload_json": json.dumps(payload.get("payload") or {}, ensure_ascii=True),
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO cue_tasks (
                        cue_id, event_id, source_id, status, priority, geometry_json, payload_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["cue_id"],
                        row["event_id"],
                        row["source_id"],
                        row["status"],
                        row["priority"],
                        row["geometry_json"],
                        row["payload_json"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )
                conn.commit()
        return self._deserialize_cue(row)

    def list_cues(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        limit_n = max(1, min(int(limit), 1000))
        with self._lock:
            with self._connect() as conn:
                if status:
                    rows = conn.execute(
                        """
                        SELECT *
                        FROM cue_tasks
                        WHERE status = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (status, limit_n),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT *
                        FROM cue_tasks
                        ORDER BY created_at DESC
                        LIMIT ?
                        """,
                        (limit_n,),
                    ).fetchall()
        return [self._deserialize_cue(dict(row)) for row in rows]

    def _deserialize_subscription(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "subscription_id": row.get("subscription_id"),
            "source_id": row.get("source_id"),
            "name": row.get("name"),
            "collection_ids": json.loads(row.get("collection_ids_json") or "[]"),
            "geometry": json.loads(row.get("geometry_json") or "{}"),
            "filters": json.loads(row.get("filters_json") or "{}"),
            "status": row.get("status"),
            "external_subscription_id": row.get("external_subscription_id"),
            "cursor": row.get("cursor"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _deserialize_event(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": row.get("event_id"),
            "subscription_id": row.get("subscription_id"),
            "source_id": row.get("source_id"),
            "scene_id": row.get("scene_id"),
            "event_type": row.get("event_type"),
            "status": row.get("status"),
            "payload": json.loads(row.get("payload_json") or "{}"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _deserialize_cue(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "cue_id": row.get("cue_id"),
            "event_id": row.get("event_id"),
            "source_id": row.get("source_id"),
            "status": row.get("status"),
            "priority": row.get("priority"),
            "geometry": json.loads(row.get("geometry_json") or "{}"),
            "payload": json.loads(row.get("payload_json") or "{}"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
