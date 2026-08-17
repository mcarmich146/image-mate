from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class GridPlanStore:
    """Small durable SQLite store for read-only grid plans and submissions."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS grid_plans (
                    plan_id TEXT PRIMARY KEY,
                    campaign_name TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    order_prefix TEXT NOT NULL,
                    contract_id TEXT,
                    geometry_json TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    grid_geojson TEXT NOT NULL,
                    order_payloads_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    submissions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _decode(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        get = row.get if isinstance(row, dict) else row.__getitem__
        return {
            "plan_id": get("plan_id"),
            "campaign_name": get("campaign_name"),
            "project_name": get("project_name"),
            "order_prefix": get("order_prefix"),
            "contract_id": get("contract_id"),
            "geometry": json.loads(get("geometry_json") or "{}"),
            "parameters": json.loads(get("parameters_json") or "{}"),
            "summary": json.loads(get("summary_json") or "{}"),
            "grid_geojson": json.loads(get("grid_geojson") or "{}"),
            "order_payloads": json.loads(get("order_payloads_json") or "[]"),
            "status": get("status"),
            "submissions": json.loads(get("submissions_json") or "[]"),
            "created_at": get("created_at"),
            "updated_at": get("updated_at"),
        }

    def create(
        self,
        *,
        campaign_name: str,
        project_name: str,
        order_prefix: str,
        contract_id: str | None,
        geometry: dict[str, Any],
        parameters: dict[str, Any],
        summary: dict[str, Any],
        grid_geojson: dict[str, Any],
        order_payloads: list[dict[str, Any]],
    ) -> dict[str, Any]:
        now = _now()
        plan_id = f"gplan.{uuid.uuid4()}"
        values = (
            plan_id,
            campaign_name,
            project_name,
            order_prefix,
            contract_id,
            json.dumps(geometry, ensure_ascii=True),
            json.dumps(parameters, ensure_ascii=True),
            json.dumps(summary, ensure_ascii=True),
            json.dumps(grid_geojson, ensure_ascii=True),
            json.dumps(order_payloads, ensure_ascii=True),
            "draft",
            "[]",
            now,
            now,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO grid_plans (
                    plan_id, campaign_name, project_name, order_prefix, contract_id,
                    geometry_json, parameters_json, summary_json, grid_geojson,
                    order_payloads_json, status, submissions_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            conn.commit()
        return self.get(plan_id) or {}

    def get(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM grid_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        return self._decode(row) if row else None

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        limit_n = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM grid_plans ORDER BY updated_at DESC LIMIT ?", (limit_n,)
            ).fetchall()
        return [self._decode(row) for row in rows]

    def save_submissions(self, plan_id: str, submissions: list[dict[str, Any]], status: str) -> dict[str, Any] | None:
        now = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE grid_plans SET submissions_json = ?, status = ?, updated_at = ? WHERE plan_id = ?",
                (json.dumps(submissions, ensure_ascii=True), status, now, plan_id),
            )
            row = conn.execute("SELECT * FROM grid_plans WHERE plan_id = ?", (plan_id,)).fetchone()
            conn.commit()
        return self._decode(row) if row else None
