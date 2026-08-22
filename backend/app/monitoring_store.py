from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import copy
import json
import sqlite3
import threading
import uuid


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class MonitoringStore:
    def __init__(self, db_path):
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
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS recollection_monitors (
                        monitor_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        collection_id TEXT NOT NULL,
                        contract_id TEXT,
                        geometry_json TEXT NOT NULL,
                        filters_json TEXT NOT NULL,
                        expected_revisit_days REAL,
                        linked_order_id TEXT,
                        enabled INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_refresh_at TEXT,
                        summary_json TEXT NOT NULL,
                        observations_json TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS archive_watches (
                        watch_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        collection_id TEXT NOT NULL,
                        contract_id TEXT,
                        geometry_json TEXT NOT NULL,
                        filters_json TEXT NOT NULL,
                        email_to TEXT,
                        enabled INTEGER NOT NULL,
                        poll_interval_seconds INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_checked_at TEXT,
                        last_success_at TEXT,
                        last_error TEXT,
                        last_email_at TEXT,
                        last_new_count INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS archive_watch_items (
                        watch_id TEXT NOT NULL,
                        item_key TEXT NOT NULL,
                        item_id TEXT,
                        item_datetime TEXT,
                        payload_json TEXT NOT NULL,
                        notified_at TEXT,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (watch_id, item_key)
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_archive_watch_items_pending ON archive_watch_items (watch_id, notified_at, created_at)"
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS monitoring_projects (
                        project_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        geometry_json TEXT NOT NULL,
                        sources_json TEXT NOT NULL,
                        cadence_seconds INTEGER NOT NULL,
                        quality_filters_json TEXT NOT NULL,
                        analysis_recipe_id TEXT,
                        alert_policy_json TEXT NOT NULL,
                        actions_json TEXT NOT NULL,
                        enabled INTEGER NOT NULL,
                        owner TEXT,
                        health TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_ingest_at TEXT,
                        last_analysis_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS monitoring_project_items (
                        project_id TEXT NOT NULL,
                        item_key TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (project_id, item_key)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS monitoring_alerts (
                        alert_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        title TEXT NOT NULL,
                        geometry_json TEXT NOT NULL,
                        evidence_json TEXT NOT NULL,
                        recipe_id TEXT,
                        source_item_id TEXT,
                        confidence REAL,
                        disposition_note TEXT,
                        owner TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS proposed_actions (
                        action_id TEXT PRIMARY KEY,
                        project_id TEXT,
                        alert_id TEXT,
                        action_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        note TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        decided_at TEXT,
                        decided_by TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS monitoring_project_activity (
                        activity_id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
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
                        row["subscription_id"], row["source_id"], row["name"], row["collection_ids_json"],
                        row["geometry_json"], row["filters_json"], row["status"], row["external_subscription_id"],
                        row["cursor"], row["created_at"], row["updated_at"],
                    ),
                )
                conn.commit()
        return self._deserialize_subscription(row)

    def list_subscriptions(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM monitoring_subscriptions ORDER BY created_at DESC").fetchall()
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
                    "INSERT INTO monitoring_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    tuple(row.values()),
                )
                conn.commit()
        return self._deserialize_event(row)

    def list_events(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        limit_n = max(1, min(int(limit), 1000))
        with self._lock:
            with self._connect() as conn:
                if status:
                    rows = conn.execute("SELECT * FROM monitoring_events WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit_n)).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM monitoring_events ORDER BY created_at DESC LIMIT ?", (limit_n,)).fetchall()
        return [self._deserialize_event(dict(row)) for row in rows]

    def ack_event(self, event_id: str, status: str = "acked") -> dict[str, Any] | None:
        now = utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute("UPDATE monitoring_events SET status = ?, updated_at = ? WHERE event_id = ?", (status, now, event_id))
                row = conn.execute("SELECT * FROM monitoring_events WHERE event_id = ?", (event_id,)).fetchone()
                conn.commit()
        return self._deserialize_event(dict(row)) if row else None

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
                conn.execute("INSERT INTO cue_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", tuple(row.values()))
                conn.commit()
        return self._deserialize_cue(row)

    def list_cues(self, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        limit_n = max(1, min(int(limit), 1000))
        with self._lock:
            with self._connect() as conn:
                if status:
                    rows = conn.execute("SELECT * FROM cue_tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit_n)).fetchall()
                else:
                    rows = conn.execute("SELECT * FROM cue_tasks ORDER BY created_at DESC LIMIT ?", (limit_n,)).fetchall()
        return [self._deserialize_cue(dict(row)) for row in rows]

    def create_recollection_monitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        monitor_id = f"rmon.{uuid.uuid4()}"
        summary = {
            "archive_status": "not_checked",
            "tasking_status": "not_checked",
            "capture_status": "not_checked",
            "deliverable_status": "not_checked",
            "tasking_checked_at": None,
            "tasking_error": None,
            "observations_count": 0,
            "new_observations": 0,
            "latest_capture_at": None,
            "last_refresh_at": None,
            "health": "unknown",
        }
        row = {
            "monitor_id": monitor_id,
            "name": str(payload.get("name") or "AOI recollection monitor").strip(),
            "source_id": str(payload.get("source_id") or "satellogic").strip(),
            "collection_id": str(payload.get("collection_id") or "quickview-visual-thumb").strip(),
            "contract_id": payload.get("contract_id"),
            "geometry_json": json.dumps(payload.get("geometry") or {}, ensure_ascii=True),
            "filters_json": json.dumps(payload.get("filters") or {}, ensure_ascii=True),
            "expected_revisit_days": payload.get("expected_revisit_days"),
            "linked_order_id": payload.get("linked_order_id"),
            "enabled": 1 if bool(payload.get("enabled", True)) else 0,
            "created_at": now,
            "updated_at": now,
            "last_refresh_at": None,
            "summary_json": json.dumps(summary, ensure_ascii=True),
            "observations_json": "[]",
        }
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO recollection_monitors (
                        monitor_id, name, source_id, collection_id, contract_id, geometry_json, filters_json,
                        expected_revisit_days, linked_order_id, enabled, created_at, updated_at, last_refresh_at,
                        summary_json, observations_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    tuple(row.values()),
                )
                conn.commit()
        return self._deserialize_monitor(row)

    def get_recollection_monitor(self, monitor_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM recollection_monitors WHERE monitor_id = ?", (monitor_id,)).fetchone()
        return self._deserialize_monitor(dict(row)) if row else None

    def list_recollection_monitors(self) -> list[dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute("SELECT * FROM recollection_monitors ORDER BY updated_at DESC").fetchall()
        return [self._deserialize_monitor(dict(row)) for row in rows]

    def save_recollection_refresh(self, monitor_id: str, observations: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any] | None:
        now = utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM recollection_monitors WHERE monitor_id = ?", (monitor_id,)).fetchone()
                if not row:
                    return None
                conn.execute(
                    "UPDATE recollection_monitors SET updated_at = ?, last_refresh_at = ?, summary_json = ?, observations_json = ? WHERE monitor_id = ?",
                    (now, now, json.dumps(summary, ensure_ascii=True), json.dumps(observations, ensure_ascii=True), monitor_id),
                )
                row = conn.execute("SELECT * FROM recollection_monitors WHERE monitor_id = ?", (monitor_id,)).fetchone()
                conn.commit()
        return self._deserialize_monitor(dict(row)) if row else None

    def update_recollection_monitor(self, monitor_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "name": "name",
            "expected_revisit_days": "expected_revisit_days",
            "linked_order_id": "linked_order_id",
            "enabled": "enabled",
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, column in allowed.items():
            if key not in updates:
                continue
            assignments.append(f"{column} = ?")
            value = updates[key]
            if key == "enabled":
                value = 1 if bool(value) else 0
            values.append(value)
        if "filters" in updates:
            assignments.append("filters_json = ?")
            values.append(json.dumps(updates["filters"] or {}, ensure_ascii=True))
        if not assignments:
            return self.get_recollection_monitor(monitor_id)
        assignments.append("updated_at = ?")
        values.append(utc_now_iso())
        values.append(monitor_id)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE recollection_monitors SET {', '.join(assignments)} WHERE monitor_id = ?",
                    tuple(values),
                )
                row = conn.execute("SELECT * FROM recollection_monitors WHERE monitor_id = ?", (monitor_id,)).fetchone()
                conn.commit()
        return self._deserialize_monitor(dict(row)) if row else None

    def delete_recollection_monitor(self, monitor_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM recollection_monitors WHERE monitor_id = ?", (monitor_id,))
                conn.commit()
                return cur.rowcount > 0

    def create_archive_watch(self, payload: dict[str, Any], default_interval_seconds: int = 300) -> dict[str, Any]:
        now = utc_now_iso()
        watch_id = f"awatch.{uuid.uuid4()}"
        row = {
            "watch_id": watch_id,
            "name": str(payload.get("name") or "Archive watch").strip(),
            "source_id": str(payload.get("source_id") or "satellogic").strip(),
            "collection_id": str(payload.get("collection_id") or "quickview-visual-thumb").strip(),
            "contract_id": payload.get("contract_id"),
            "geometry_json": json.dumps(payload.get("geometry") or {}, ensure_ascii=True),
            "filters_json": json.dumps(payload.get("filters") or {}, ensure_ascii=True),
            "email_to": str(payload.get("email_to") or "").strip() or None,
            "enabled": 1 if bool(payload.get("enabled", True)) else 0,
            "poll_interval_seconds": max(15, int(payload.get("poll_interval_seconds") or default_interval_seconds)),
            "created_at": now,
            "updated_at": now,
            "last_checked_at": None,
            "last_success_at": None,
            "last_error": None,
            "last_email_at": None,
            "last_new_count": 0,
        }
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO archive_watches (
                        watch_id, name, source_id, collection_id, contract_id, geometry_json, filters_json,
                        email_to, enabled, poll_interval_seconds, created_at, updated_at, last_checked_at,
                        last_success_at, last_error, last_email_at, last_new_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    tuple(row.values()),
                )
                conn.commit()
        return self._deserialize_archive_watch(row)

    def get_archive_watch(self, watch_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM archive_watches WHERE watch_id = ?", (watch_id,)).fetchone()
        return self._deserialize_archive_watch(dict(row)) if row else None

    def list_archive_watches(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM archive_watches"
        params: tuple[Any, ...] = ()
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY updated_at DESC"
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
        return [self._deserialize_archive_watch(dict(row)) for row in rows]

    def update_archive_watch(self, watch_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "name": "name",
            "email_to": "email_to",
            "poll_interval_seconds": "poll_interval_seconds",
            "enabled": "enabled",
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, column in allowed.items():
            if key not in updates:
                continue
            value = updates[key]
            if key == "enabled":
                value = 1 if bool(value) else 0
            elif key == "poll_interval_seconds":
                value = max(15, int(value))
            elif key == "email_to":
                value = str(value or "").strip() or None
            elif key == "name":
                value = str(value or "").strip()
            assignments.append(f"{column} = ?")
            values.append(value)
        if "filters" in updates:
            assignments.append("filters_json = ?")
            values.append(json.dumps(updates["filters"] or {}, ensure_ascii=True))
        if not assignments:
            return self.get_archive_watch(watch_id)
        assignments.append("updated_at = ?")
        values.extend([utc_now_iso(), watch_id])
        with self._lock:
            with self._connect() as conn:
                conn.execute(f"UPDATE archive_watches SET {', '.join(assignments)} WHERE watch_id = ?", tuple(values))
                row = conn.execute("SELECT * FROM archive_watches WHERE watch_id = ?", (watch_id,)).fetchone()
                conn.commit()
        return self._deserialize_archive_watch(dict(row)) if row else None

    def delete_archive_watch(self, watch_id: str) -> bool:
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM archive_watch_items WHERE watch_id = ?", (watch_id,))
                cur = conn.execute("DELETE FROM archive_watches WHERE watch_id = ?", (watch_id,))
                conn.commit()
                return cur.rowcount > 0

    def record_archive_watch_items(self, watch_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert unseen item keys and return only the newly claimed rows."""
        created: list[dict[str, Any]] = []
        now = utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                for item in items:
                    item_key = str(item.get("item_key") or item.get("id") or "").strip()
                    if not item_key:
                        continue
                    payload = dict(item)
                    payload.pop("assets", None)
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO archive_watch_items (
                            watch_id, item_key, item_id, item_datetime, payload_json, notified_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, NULL, ?)""",
                        (
                            watch_id,
                            item_key,
                            item.get("item_id") or item.get("id"),
                            item.get("datetime"),
                            json.dumps(payload, ensure_ascii=True),
                            now,
                        ),
                    )
                    if cur.rowcount:
                        created.append({**payload, "item_key": item_key})
                conn.commit()
        return created

    def list_pending_archive_watch_items(self, watch_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        limit_n = max(1, min(int(limit), 5000))
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM archive_watch_items WHERE watch_id = ? AND notified_at IS NULL ORDER BY item_datetime DESC, created_at DESC LIMIT ?",
                    (watch_id, limit_n),
                ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"] or "{}")
            payload["item_key"] = row["item_key"]
            payload["item_id"] = row["item_id"] or payload.get("item_id") or payload.get("id")
            payload["datetime"] = row["item_datetime"] or payload.get("datetime")
            output.append(payload)
        return output

    def mark_archive_watch_items_notified(self, watch_id: str, item_keys: list[str], notified_at: str | None = None) -> int:
        keys = [str(value).strip() for value in item_keys if str(value).strip()]
        if not keys:
            return 0
        timestamp = notified_at or utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                cur = conn.executemany(
                    "UPDATE archive_watch_items SET notified_at = ? WHERE watch_id = ? AND item_key = ? AND notified_at IS NULL",
                    [(timestamp, watch_id, key) for key in keys],
                )
                conn.commit()
                return cur.rowcount

    def save_archive_watch_check(
        self,
        watch_id: str,
        *,
        checked_at: str,
        success: bool,
        error: str | None = None,
        email_at: str | None = None,
        new_count: int = 0,
    ) -> dict[str, Any] | None:
        now = utc_now_iso()
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """UPDATE archive_watches SET updated_at = ?, last_checked_at = ?,
                       last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END,
                       last_error = ?, last_email_at = COALESCE(?, last_email_at), last_new_count = ?
                       WHERE watch_id = ?""",
                    (now, checked_at, 1 if success else 0, checked_at if success else None, error, email_at, int(new_count), watch_id),
                )
                row = conn.execute("SELECT * FROM archive_watches WHERE watch_id = ?", (watch_id,)).fetchone()
                conn.commit()
        return self._deserialize_archive_watch(dict(row)) if row else None

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        project_id = str(payload.get("project_id") or f"mproj.{uuid.uuid4()}")
        row = {
            "project_id": project_id, "name": str(payload.get("name") or "Monitoring project").strip(),
            "geometry_json": json.dumps(payload.get("geometry") or {}, ensure_ascii=True),
            "sources_json": json.dumps(payload.get("sources") or [], ensure_ascii=True),
            "cadence_seconds": max(60, int(payload.get("cadence_seconds") or 3600)),
            "quality_filters_json": json.dumps(payload.get("quality_filters") or {}, ensure_ascii=True),
            "analysis_recipe_id": payload.get("analysis_recipe_id"),
            "alert_policy_json": json.dumps(payload.get("alert_policy") or {}, ensure_ascii=True),
            "actions_json": json.dumps(payload.get("actions") or {}, ensure_ascii=True),
            "enabled": 1 if bool(payload.get("enabled", True)) else 0,
            "owner": str(payload.get("owner") or "local-operator"), "health": "unknown",
            "created_at": now, "updated_at": now, "last_ingest_at": None, "last_analysis_at": None,
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO monitoring_projects (
                    project_id,name,geometry_json,sources_json,cadence_seconds,quality_filters_json,
                    analysis_recipe_id,alert_policy_json,actions_json,enabled,owner,health,created_at,
                    updated_at,last_ingest_at,last_analysis_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(row.values()),
            )
            conn.commit()
        self.add_project_activity(project_id, "project.created", {"name": row["name"]})
        return self.get_project(project_id) or {}

    @staticmethod
    def _decode_field(value: Any, default: Any) -> Any:
        try:
            return json.loads(value or "")
        except (TypeError, ValueError):
            return default

    def _deserialize_project(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "project_id": row.get("project_id"), "name": row.get("name"),
            "geometry": self._decode_field(row.get("geometry_json"), {}),
            "sources": self._decode_field(row.get("sources_json"), []),
            "cadence_seconds": int(row.get("cadence_seconds") or 3600),
            "quality_filters": self._decode_field(row.get("quality_filters_json"), {}),
            "analysis_recipe_id": row.get("analysis_recipe_id"),
            "alert_policy": self._decode_field(row.get("alert_policy_json"), {}),
            "actions": self._decode_field(row.get("actions_json"), {}),
            "enabled": bool(row.get("enabled")), "owner": row.get("owner"), "health": row.get("health"),
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
            "last_ingest_at": row.get("last_ingest_at"), "last_analysis_at": row.get("last_analysis_at"),
        }

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM monitoring_projects WHERE project_id = ?", (project_id,)).fetchone()
        return self._deserialize_project(dict(row)) if row else None

    def list_projects(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM monitoring_projects"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY updated_at DESC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._deserialize_project(dict(row)) for row in rows]

    def update_project(self, project_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        columns = {
            "name": "name", "cadence_seconds": "cadence_seconds", "analysis_recipe_id": "analysis_recipe_id",
            "enabled": "enabled", "health": "health", "last_ingest_at": "last_ingest_at",
            "last_analysis_at": "last_analysis_at", "sources": "sources_json", "quality_filters": "quality_filters_json",
            "alert_policy": "alert_policy_json", "actions": "actions_json",
        }
        json_keys = {"sources", "quality_filters", "alert_policy", "actions"}
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            if key not in columns or value is None:
                continue
            assignments.append(f"{columns[key]} = ?")
            values.append((json.dumps(value, ensure_ascii=True) if key in json_keys else 1 if key == "enabled" and value else 0 if key == "enabled" else value))
        if not assignments:
            return self.get_project(project_id)
        assignments.append("updated_at = ?")
        values.extend([utc_now_iso(), project_id])
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE monitoring_projects SET {', '.join(assignments)} WHERE project_id = ?", tuple(values))
            conn.commit()
        return self.get_project(project_id)

    def record_project_items(self, project_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = utc_now_iso()
        created: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            for item in items:
                key = str(item.get("item_key") or item.get("id") or item.get("item_id") or "").strip()
                if not key:
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO monitoring_project_items (project_id,item_key,payload_json,created_at) VALUES (?,?,?,?)",
                    (project_id, key, json.dumps(item, ensure_ascii=True), now),
                )
                if cur.rowcount:
                    created.append({**item, "item_key": key})
            conn.execute("UPDATE monitoring_projects SET last_ingest_at = ?, updated_at = ? WHERE project_id = ?", (now, now, project_id))
            conn.commit()
        return created

    def get_open_alert_for_item(self, project_id: str, source_item_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM monitoring_alerts WHERE project_id = ? AND source_item_id = ? AND status NOT IN ('Dismissed','Actioned') ORDER BY created_at DESC LIMIT 1",
                (project_id, source_item_id),
            ).fetchone()
        return self._deserialize_alert(dict(row)) if row else None

    def create_alert(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        alert_id = str(payload.get("alert_id") or f"alert.{uuid.uuid4()}")
        row = {
            "alert_id": alert_id, "project_id": payload["project_id"], "status": payload.get("status") or "New",
            "severity": payload.get("severity") or "medium", "title": payload.get("title") or "Analysis alert",
            "geometry_json": json.dumps(payload.get("geometry") or {}, ensure_ascii=True),
            "evidence_json": json.dumps(payload.get("evidence") or {}, ensure_ascii=True),
            "recipe_id": payload.get("recipe_id"), "source_item_id": payload.get("source_item_id"),
            "confidence": payload.get("confidence"), "disposition_note": payload.get("disposition_note"),
            "owner": payload.get("owner") or "local-operator", "created_at": now, "updated_at": now,
        }
        with self._lock, self._connect() as conn:
            conn.execute("""INSERT INTO monitoring_alerts (
                alert_id,project_id,status,severity,title,geometry_json,evidence_json,recipe_id,source_item_id,
                confidence,disposition_note,owner,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", tuple(row.values()))
            conn.commit()
        self.add_project_activity(row["project_id"], "alert.created", {"alert_id": alert_id, "severity": row["severity"]})
        return self.get_alert(alert_id) or {}

    def _deserialize_alert(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "alert_id": row.get("alert_id"), "project_id": row.get("project_id"), "status": row.get("status"),
            "severity": row.get("severity"), "title": row.get("title"),
            "geometry": self._decode_field(row.get("geometry_json"), {}),
            "evidence": self._decode_field(row.get("evidence_json"), {}), "recipe_id": row.get("recipe_id"),
            "source_item_id": row.get("source_item_id"), "confidence": row.get("confidence"),
            "disposition_note": row.get("disposition_note"), "owner": row.get("owner"),
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
        }

    def get_alert(self, alert_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM monitoring_alerts WHERE alert_id = ?", (alert_id,)).fetchone()
        return self._deserialize_alert(dict(row)) if row else None

    def list_alerts(self, project_id: str | None = None, limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if project_id:
            clauses.append("project_id = ?"); values.append(project_id)
        if status:
            clauses.append("status = ?"); values.append(status)
        query = "SELECT * FROM monitoring_alerts" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY created_at DESC LIMIT ?"
        values.append(max(1, min(int(limit), 1000)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, tuple(values)).fetchall()
        return [self._deserialize_alert(dict(row)) for row in rows]

    def dispose_alert(self, alert_id: str, status: str, note: str | None = None) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE monitoring_alerts SET status = ?, disposition_note = ?, updated_at = ? WHERE alert_id = ?", (status, note, utc_now_iso(), alert_id))
            row = conn.execute("SELECT * FROM monitoring_alerts WHERE alert_id = ?", (alert_id,)).fetchone()
            conn.commit()
        return self._deserialize_alert(dict(row)) if row else None

    def create_proposed_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso(); action_id = str(payload.get("action_id") or f"action.{uuid.uuid4()}")
        row = {
            "action_id": action_id, "project_id": payload.get("project_id"), "alert_id": payload.get("alert_id"),
            "action_type": payload.get("action_type") or "tasking", "status": payload.get("status") or "pending_approval",
            "payload_json": json.dumps(payload.get("payload") or {}, ensure_ascii=True), "note": payload.get("note"),
            "created_at": now, "updated_at": now, "decided_at": None, "decided_by": None,
        }
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO proposed_actions (action_id,project_id,alert_id,action_type,status,payload_json,note,created_at,updated_at,decided_at,decided_by) VALUES (?,?,?,?,?,?,?,?,?,?,?)", tuple(row.values()))
            conn.commit()
        return self.get_proposed_action(action_id) or {}

    def _deserialize_action(self, row: dict[str, Any]) -> dict[str, Any]:
        return {"action_id": row.get("action_id"), "project_id": row.get("project_id"), "alert_id": row.get("alert_id"), "action_type": row.get("action_type"), "status": row.get("status"), "payload": self._decode_field(row.get("payload_json"), {}), "note": row.get("note"), "created_at": row.get("created_at"), "updated_at": row.get("updated_at"), "decided_at": row.get("decided_at"), "decided_by": row.get("decided_by")}

    def get_proposed_action(self, action_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM proposed_actions WHERE action_id = ?", (action_id,)).fetchone()
        return self._deserialize_action(dict(row)) if row else None

    def list_proposed_actions(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute("SELECT * FROM proposed_actions WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, max(1, min(int(limit), 1000)))).fetchall()
            else:
                rows = conn.execute("SELECT * FROM proposed_actions ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
        return [self._deserialize_action(dict(row)) for row in rows]

    def decide_proposed_action(self, action_id: str, status: str, note: str | None = None, decided_by: str = "local-operator") -> dict[str, Any] | None:
        now = utc_now_iso()
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE proposed_actions SET status = ?, note = ?, updated_at = ?, decided_at = ?, decided_by = ? WHERE action_id = ?", (status, note, now, now, decided_by, action_id))
            row = conn.execute("SELECT * FROM proposed_actions WHERE action_id = ?", (action_id,)).fetchone()
            conn.commit()
        return self._deserialize_action(dict(row)) if row else None

    def add_project_activity(self, project_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        row = {"activity_id": f"mact.{uuid.uuid4()}", "project_id": project_id, "event_type": event_type, "payload_json": json.dumps(payload or {}, ensure_ascii=True), "created_at": utc_now_iso()}
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO monitoring_project_activity VALUES (?,?,?,?,?)", tuple(row.values()))
            conn.commit()
        return {"activity_id": row["activity_id"], "project_id": project_id, "event_type": event_type, "payload": payload or {}, "created_at": row["created_at"]}

    def list_project_activity(self, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM monitoring_project_activity WHERE project_id = ? ORDER BY created_at DESC LIMIT ?", (project_id, max(1, min(int(limit), 1000)))).fetchall()
        return [{"activity_id": row["activity_id"], "project_id": row["project_id"], "event_type": row["event_type"], "payload": self._decode_field(row["payload_json"], {}), "created_at": row["created_at"]} for row in rows]

    def _deserialize_subscription(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "subscription_id": row.get("subscription_id"), "source_id": row.get("source_id"), "name": row.get("name"),
            "collection_ids": json.loads(row.get("collection_ids_json") or "[]"), "geometry": json.loads(row.get("geometry_json") or "{}"),
            "filters": json.loads(row.get("filters_json") or "{}"), "status": row.get("status"),
            "external_subscription_id": row.get("external_subscription_id"), "cursor": row.get("cursor"),
            "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
        }

    def _deserialize_event(self, row: dict[str, Any]) -> dict[str, Any]:
        return {"event_id": row.get("event_id"), "subscription_id": row.get("subscription_id"), "source_id": row.get("source_id"), "scene_id": row.get("scene_id"), "event_type": row.get("event_type"), "status": row.get("status"), "payload": json.loads(row.get("payload_json") or "{}"), "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}

    def _deserialize_cue(self, row: dict[str, Any]) -> dict[str, Any]:
        return {"cue_id": row.get("cue_id"), "event_id": row.get("event_id"), "source_id": row.get("source_id"), "status": row.get("status"), "priority": row.get("priority"), "geometry": json.loads(row.get("geometry_json") or "{}"), "payload": json.loads(row.get("payload_json") or "{}"), "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}

    def _deserialize_monitor(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "monitor_id": row.get("monitor_id"), "name": row.get("name"), "source_id": row.get("source_id"),
            "collection_id": row.get("collection_id"), "contract_id": row.get("contract_id"),
            "geometry": json.loads(row.get("geometry_json") or "{}"), "filters": json.loads(row.get("filters_json") or "{}"),
            "expected_revisit_days": row.get("expected_revisit_days"), "linked_order_id": row.get("linked_order_id"),
            "enabled": bool(row.get("enabled")), "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
            "last_refresh_at": row.get("last_refresh_at"), "summary": json.loads(row.get("summary_json") or "{}"),
            "observations": json.loads(row.get("observations_json") or "[]"),
        }

    def _deserialize_archive_watch(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "watch_id": row.get("watch_id"),
            "name": row.get("name"),
            "source_id": row.get("source_id"),
            "collection_id": row.get("collection_id"),
            "contract_id": row.get("contract_id"),
            "geometry": json.loads(row.get("geometry_json") or "{}"),
            "filters": json.loads(row.get("filters_json") or "{}"),
            "email_to": row.get("email_to"),
            "enabled": bool(row.get("enabled")),
            "poll_interval_seconds": int(row.get("poll_interval_seconds") or 300),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "last_checked_at": row.get("last_checked_at"),
            "last_success_at": row.get("last_success_at"),
            "last_error": row.get("last_error"),
            "last_email_at": row.get("last_email_at"),
            "last_new_count": int(row.get("last_new_count") or 0),
            "pending_count": self._pending_archive_watch_count(str(row.get("watch_id") or "")),
        }

    def _pending_archive_watch_count(self, watch_id: str) -> int:
        if not watch_id:
            return 0
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM archive_watch_items WHERE watch_id = ? AND notified_at IS NULL",
                (watch_id,),
            ).fetchone()
        return int(row["count"] or 0) if row else 0
