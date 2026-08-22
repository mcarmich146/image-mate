"""Durable analyst-facing analysis recipes.

Recipes are intentionally small records: the technical workflow graph remains
behind the Tools drawer while recipes carry the compatibility and alert policy
that an analyst needs to select safely.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class AnalysisRecipeStore:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_recipes (
                    recipe_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    description TEXT NOT NULL,
                    models_json TEXT NOT NULL,
                    compatibility_json TEXT NOT NULL,
                    thresholds_json TEXT NOT NULL,
                    classes_json TEXT NOT NULL,
                    alert_rules_json TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            count = conn.execute("SELECT COUNT(*) AS count FROM analysis_recipes").fetchone()["count"]
            if not count:
                self._insert_locked(conn, {
                    "recipe_id": "recipe.aircraft-surveillance",
                    "name": "Aircraft surveillance",
                    "version": "1.0.0",
                    "description": "High-resolution aircraft and helicopter detector for NewSat visual imagery.",
                    "models": [{"model_id": "configured-aircraft-detector", "version": "configured"}],
                    "compatibility": {"sources": ["satellogic"], "collections": ["l1d-sr"], "max_gsd_m": 5.0},
                    "thresholds": {"confidence": 0.25},
                    "classes": ["plane", "helicopter", "background"],
                    "alert_rules": {"default_severity": "medium"},
                    "actions": {},
                    "enabled": True,
                })
                self._insert_locked(conn, {
                    "recipe_id": "recipe.sentinel-change-watch",
                    "name": "Sentinel-2 change watch",
                    "version": "1.0.0",
                    "description": "Compatible baseline for Sentinel-2 monitoring projects and downstream workflows.",
                    "models": [],
                    "compatibility": {"sources": ["merlin-s2"], "collections": ["sentinel-2-l1c", "sentinel-2-l2a"]},
                    "thresholds": {},
                    "classes": ["change"],
                    "alert_rules": {"default_severity": "low"},
                    "actions": {},
                    "enabled": True,
                })
            conn.commit()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value if value is not None else {}, sort_keys=True)

    def _insert_locked(self, conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
        now = payload.get("created_at") or _now()
        conn.execute(
            """INSERT INTO analysis_recipes (
                recipe_id,name,version,description,models_json,compatibility_json,
                thresholds_json,classes_json,alert_rules_json,actions_json,enabled,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payload["recipe_id"], payload["name"], payload["version"], payload.get("description", ""),
                self._json(payload.get("models", [])), self._json(payload.get("compatibility", {})),
                self._json(payload.get("thresholds", {})), self._json(payload.get("classes", [])),
                self._json(payload.get("alert_rules", {})), self._json(payload.get("actions", {})),
                1 if payload.get("enabled", True) else 0, now, now,
            ),
        )

    @staticmethod
    def _decode(value: str | None, default: Any) -> Any:
        try:
            return json.loads(value or "")
        except (TypeError, ValueError):
            return default

    def _row(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        get = row.get if isinstance(row, dict) else row.__getitem__
        return {
            "recipe_id": get("recipe_id"), "name": get("name"), "version": get("version"),
            "description": get("description"), "models": self._decode(get("models_json"), []),
            "compatibility": self._decode(get("compatibility_json"), {}),
            "thresholds": self._decode(get("thresholds_json"), {}),
            "classes": self._decode(get("classes_json"), []),
            "alert_rules": self._decode(get("alert_rules_json"), {}),
            "actions": self._decode(get("actions_json"), {}), "enabled": bool(get("enabled")),
            "created_at": get("created_at"), "updated_at": get("updated_at"),
        }

    def list(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM analysis_recipes"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY name, version"
        with self._lock, self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._row(row) for row in rows]

    def get(self, recipe_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM analysis_recipes WHERE recipe_id = ?", (recipe_id,)).fetchone()
        return self._row(row) if row else None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        data["recipe_id"] = str(data.get("recipe_id") or f"recipe.{uuid.uuid4()}")
        with self._lock, self._connect() as conn:
            self._insert_locked(conn, data)
            conn.commit()
        return self.get(data["recipe_id"]) or {}

    def update(self, recipe_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        columns = {
            "name": "name", "version": "version", "description": "description", "enabled": "enabled",
            "models": "models_json", "compatibility": "compatibility_json", "thresholds": "thresholds_json",
            "classes": "classes_json", "alert_rules": "alert_rules_json", "actions": "actions_json",
        }
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            if key not in columns or value is None:
                continue
            assignments.append(f"{columns[key]} = ?")
            values.append(1 if key == "enabled" and value else 0 if key == "enabled" else self._json(value) if key in {"models", "compatibility", "thresholds", "classes", "alert_rules", "actions"} else value)
        if not assignments:
            return self.get(recipe_id)
        assignments.append("updated_at = ?")
        values.extend([_now(), recipe_id])
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE analysis_recipes SET {', '.join(assignments)} WHERE recipe_id = ?", values)
            conn.commit()
        return self.get(recipe_id)

    def compatibility(self, recipe: dict[str, Any], item: dict[str, Any]) -> tuple[bool, str]:
        compatibility = recipe.get("compatibility") if isinstance(recipe.get("compatibility"), dict) else {}
        source = str(item.get("source_id") or "").strip()
        collection = str(item.get("collection") or item.get("collection_id") or "").strip()
        sources = {str(value) for value in compatibility.get("sources") or []}
        collections = {str(value) for value in compatibility.get("collections") or []}
        if sources and source not in sources:
            return False, f"Recipe is not compatible with source {source or 'unknown'}"
        if collections and collection not in collections:
            return False, f"Recipe is not compatible with collection {collection or 'unknown'}"
        max_gsd = compatibility.get("max_gsd_m")
        if max_gsd is not None and item.get("gsd") is not None and float(item["gsd"]) > float(max_gsd):
            return False, f"Recipe requires imagery at or better than {max_gsd} m GSD"
        return True, "compatible"
