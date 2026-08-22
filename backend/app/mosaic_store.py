"""Small durable store for Mosaic Workbench sessions and jobs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any
import uuid


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class MosaicStore:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mosaic_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    preflight_json TEXT,
                    result_json TEXT,
                    error TEXT,
                    progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    dependency_json TEXT,
                    last_checked_at TEXT,
                    next_check_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            job_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(mosaic_jobs)").fetchall()
            }
            for column, definition in {
                "dependency_json": "TEXT",
                "last_checked_at": "TEXT",
                "next_check_at": "TEXT",
                "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                if column not in job_columns:
                    connection.execute(f"ALTER TABLE mosaic_jobs ADD COLUMN {column} {definition}")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mosaic_projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_item_ids_json TEXT NOT NULL,
                    output_bands TEXT NOT NULL,
                    output_resolution_m REAL,
                    sensor_generation TEXT NOT NULL,
                    geometry_json TEXT,
                    status TEXT NOT NULL,
                    active_job_id TEXT,
                    qc_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mosaic_repairs (
                    repair_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES mosaic_jobs(job_id)
                )
                """
            )

    @staticmethod
    def _decode_list(value: str | None) -> list[Any]:
        try:
            parsed = json.loads(value or "[]")
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = str(payload.get("project_id") or f"mosaic.{uuid.uuid4()}")
        now = _now()
        row = {
            "project_id": project_id, "name": str(payload.get("name") or "Mosaic project").strip(),
            "source_item_ids_json": json.dumps(payload.get("source_item_ids") or [], sort_keys=True),
            "output_bands": str(payload.get("output_bands") or "rgb"),
            "output_resolution_m": payload.get("output_resolution_m"),
            "sensor_generation": str(payload.get("sensor_generation") or "unknown"),
            "geometry_json": json.dumps(payload.get("geometry") or {}, sort_keys=True) if payload.get("geometry") else None,
            "status": str(payload.get("status") or "Draft"), "active_job_id": None, "qc_state": "not_started",
            "created_at": now, "updated_at": now,
        }
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO mosaic_projects (
                    project_id,name,source_item_ids_json,output_bands,output_resolution_m,sensor_generation,
                    geometry_json,status,active_job_id,qc_state,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", tuple(row.values())
            )
        return self.get_project(project_id) or {}

    def _row_to_project(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            geometry = json.loads(row["geometry_json"] or "{}")
        except (TypeError, ValueError):
            geometry = {}
        return {
            "project_id": row["project_id"], "name": row["name"], "source_item_ids": self._decode_list(row["source_item_ids_json"]),
            "output_bands": row["output_bands"], "output_resolution_m": row["output_resolution_m"],
            "sensor_generation": row["sensor_generation"], "geometry": geometry,
            "status": row["status"], "active_job_id": row["active_job_id"], "qc_state": row["qc_state"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        }

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM mosaic_projects WHERE project_id = ?", (str(project_id),)).fetchone()
        return self._row_to_project(row) if row else None

    def list_projects(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            if status:
                rows = connection.execute("SELECT * FROM mosaic_projects WHERE status = ? ORDER BY updated_at DESC LIMIT ?", (status, max(1, min(int(limit), 500)))).fetchall()
            else:
                rows = connection.execute("SELECT * FROM mosaic_projects ORDER BY updated_at DESC LIMIT ?", (max(1, min(int(limit), 500)),)).fetchall()
        return [self._row_to_project(row) for row in rows]

    def update_project(self, project_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        columns = {"name": "name", "output_bands": "output_bands", "output_resolution_m": "output_resolution_m", "status": "status", "geometry": "geometry_json", "active_job_id": "active_job_id", "qc_state": "qc_state", "source_item_ids": "source_item_ids_json", "sensor_generation": "sensor_generation"}
        assignments: list[str] = []; values: list[Any] = []
        for key, value in updates.items():
            if key not in columns or value is None:
                continue
            assignments.append(f"{columns[key]} = ?")
            values.append(json.dumps(value, sort_keys=True) if key in {"geometry", "source_item_ids"} else value)
        if not assignments:
            return self.get_project(project_id)
        assignments.append("updated_at = ?"); values.extend([_now(), str(project_id)])
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE mosaic_projects SET {', '.join(assignments)} WHERE project_id = ?", tuple(values))
        return self.get_project(project_id)

    @staticmethod
    def _decode(value: str | None) -> dict[str, Any]:
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def create_job(
        self,
        *,
        mode: str,
        payload: dict[str, Any],
        preflight: dict[str, Any],
        status: str = "queued",
        message: str = "",
        dependency: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO mosaic_jobs (
                    job_id,status,mode,payload_json,preflight_json,message,dependency_json,
                    created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    str(status),
                    str(mode),
                    json.dumps(payload, sort_keys=True),
                    json.dumps(preflight, sort_keys=True),
                    str(message),
                    json.dumps(dependency or {}, sort_keys=True),
                    now,
                    now,
                ),
            )
        return self.get_job(job_id) or {}

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM mosaic_jobs WHERE job_id = ?", (str(job_id),)).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM mosaic_jobs ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def list_jobs_by_status(self, statuses: list[str], limit: int = 200) -> list[dict[str, Any]]:
        normalized = [str(value).strip() for value in statuses if str(value).strip()]
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM mosaic_jobs WHERE status IN ({placeholders}) ORDER BY updated_at ASC LIMIT ?",
                (*normalized, max(1, min(int(limit), 500))),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def update_job(self, job_id: str, **updates: Any) -> dict[str, Any] | None:
        allowed = {
            "status", "payload_json", "preflight_json", "result_json", "error", "progress",
            "message", "dependency_json", "last_checked_at", "next_check_at", "attempt_count",
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = ?")
            values.append(value)
        if not assignments:
            return self.get_job(job_id)
        assignments.append("updated_at = ?")
        values.append(_now())
        values.append(str(job_id))
        with self._lock, self._connect() as connection:
            connection.execute(f"UPDATE mosaic_jobs SET {', '.join(assignments)} WHERE job_id = ?", values)
        return self.get_job(job_id)

    def claim_job(self, job_id: str, *, message: str = "Claimed by host worker") -> dict[str, Any] | None:
        """Atomically claim a queued job so two host workers cannot run it."""

        now = _now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE mosaic_jobs SET status = ?, message = ?, progress = ?, updated_at = ? "
                "WHERE job_id = ? AND status = ?",
                ("running", str(message), 1.0, now, str(job_id), "queued"),
            )
            if cursor.rowcount != 1:
                return self.get_job(job_id)
        return self.get_job(job_id)

    def create_repair(self, *, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        repair_id = str(uuid.uuid4())
        now = _now()
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO mosaic_repairs (repair_id,job_id,status,payload_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (repair_id, str(job_id), "queued", json.dumps(payload, sort_keys=True), now, now),
            )
        return self.get_repair(repair_id) or {}

    def get_repair(self, repair_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM mosaic_repairs WHERE repair_id = ?", (str(repair_id),)).fetchone()
        if row is None:
            return None
        return {
            "repair_id": row["repair_id"],
            "job_id": row["job_id"],
            "status": row["status"],
            "payload": self._decode(row["payload_json"]),
            "result": self._decode(row["result_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_job(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "status": row["status"],
            "mode": row["mode"],
            "payload": self._decode(row["payload_json"]),
            "preflight": self._decode(row["preflight_json"]),
            "result": self._decode(row["result_json"]),
            "error": row["error"] or "",
            "progress": float(row["progress"] or 0),
            "message": row["message"] or "",
            "dependency": self._decode(row["dependency_json"]),
            "last_checked_at": row["last_checked_at"],
            "next_check_at": row["next_check_at"],
            "attempt_count": int(row["attempt_count"] or 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
