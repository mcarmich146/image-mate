# -*- coding: utf-8 -*-
"""SQLite persistence for Mosaic project, tile, and attempt tracking."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .mosaic_contracts import (
    API_STATUS_NOT_SUBMITTED,
    DEFAULT_TILE_QA_STATUS,
    MOSAIC_SCHEMA_VERSION,
    MUTATION_SOURCE_ACCEPT,
    QA_STATUS_ACCEPTED,
    utc_now_iso,
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mosaic_project (
    project_id TEXT PRIMARY KEY,
    campaign_uid TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    aoi_source TEXT,
    aoi_geojson TEXT,
    estimated_price_usd REAL NOT NULL,
    tile_count INTEGER NOT NULL,
    shapefile_path TEXT,
    source_id TEXT,
    schema_version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS mosaic_tile (
    project_id TEXT NOT NULL,
    tile_id TEXT NOT NULL,
    geometry_wkt TEXT NOT NULL,
    clipped_area_km2 REAL NOT NULL,
    qa_status TEXT NOT NULL,
    api_status TEXT NOT NULL,
    latest_collection_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_sync_at TEXT,
    accepted_at TEXT,
    accepted_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    mutation_source TEXT NOT NULL,
    PRIMARY KEY(project_id, tile_id),
    FOREIGN KEY(project_id) REFERENCES mosaic_project(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mosaic_attempt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    tile_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    collection_id TEXT,
    attempt_status TEXT NOT NULL,
    api_status TEXT,
    request_payload_json TEXT,
    response_payload_json TEXT,
    error_text TEXT,
    requested_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, tile_id, attempt_no),
    FOREIGN KEY(project_id, tile_id) REFERENCES mosaic_tile(project_id, tile_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS mosaic_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    tile_id TEXT NOT NULL,
    from_qa_status TEXT,
    to_qa_status TEXT,
    from_api_status TEXT,
    to_api_status TEXT,
    mutation_source TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id, tile_id) REFERENCES mosaic_tile(project_id, tile_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mosaic_tile_project_status
    ON mosaic_tile(project_id, qa_status, api_status);

CREATE INDEX IF NOT EXISTS idx_mosaic_attempt_project_tile
    ON mosaic_attempt(project_id, tile_id, attempt_no DESC);

CREATE INDEX IF NOT EXISTS idx_mosaic_status_history_project_tile
    ON mosaic_status_history(project_id, tile_id, created_at DESC);
"""


class MosaicTrackingStore:
    """Persist and query Mosaic tracking state in project-local SQLite."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(str(db_path)).expanduser()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def create_project_with_tiles(
        self,
        *,
        project_id: str,
        campaign_uid: str,
        source_id: str,
        aoi_source: str,
        aoi_geojson: dict[str, Any],
        estimated_price_usd: float,
        shapefile_path: str,
        tile_rows: list[dict[str, Any]],
        mutation_source: str = "create",
    ) -> None:
        now = utc_now_iso()
        aoi_json_text = json.dumps(aoi_geojson or {}, sort_keys=True)
        rows = [row for row in (tile_rows or []) if isinstance(row, dict)]
        with self._connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO mosaic_project (
                    project_id, campaign_uid, created_at, updated_at,
                    aoi_source, aoi_geojson, estimated_price_usd, tile_count,
                    shapefile_path, source_id, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(project_id),
                    str(campaign_uid),
                    now,
                    now,
                    str(aoi_source or ""),
                    aoi_json_text,
                    float(estimated_price_usd or 0.0),
                    int(len(rows)),
                    str(shapefile_path or ""),
                    str(source_id or ""),
                    int(MOSAIC_SCHEMA_VERSION),
                ),
            )

            for row in rows:
                tile_id = str(row.get("tile_id") or "").strip()
                geom_wkt = str(row.get("geometry_wkt") or "").strip()
                area_km2 = float(row.get("clipped_area_km2") or 0.0)
                if not tile_id or not geom_wkt:
                    continue
                conn.execute(
                    """
                    INSERT INTO mosaic_tile (
                        project_id, tile_id, geometry_wkt, clipped_area_km2,
                        qa_status, api_status, latest_collection_id, attempt_count,
                        last_sync_at, accepted_at, accepted_by,
                        created_at, updated_at, mutation_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(project_id),
                        tile_id,
                        geom_wkt,
                        float(area_km2),
                        DEFAULT_TILE_QA_STATUS,
                        API_STATUS_NOT_SUBMITTED,
                        None,
                        0,
                        None,
                        None,
                        None,
                        now,
                        now,
                        str(mutation_source or "create"),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO mosaic_status_history (
                        project_id, tile_id, from_qa_status, to_qa_status,
                        from_api_status, to_api_status, mutation_source, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(project_id),
                        tile_id,
                        None,
                        DEFAULT_TILE_QA_STATUS,
                        None,
                        API_STATUS_NOT_SUBMITTED,
                        str(mutation_source or "create"),
                        "tile_created",
                        now,
                    ),
                )
            conn.commit()

    def project_exists(self, project_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM mosaic_project WHERE project_id = ? LIMIT 1",
                (str(project_id or ""),),
            ).fetchone()
        return row is not None

    def load_project(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mosaic_project WHERE project_id = ? LIMIT 1",
                (str(project_id or ""),),
            ).fetchone()
        return self._row_to_dict(row)

    def load_tiles(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    project_id,
                    tile_id,
                    clipped_area_km2,
                    qa_status,
                    api_status,
                    latest_collection_id,
                    attempt_count,
                    last_sync_at,
                    accepted_at,
                    accepted_by,
                    created_at,
                    updated_at,
                    mutation_source
                FROM mosaic_tile
                WHERE project_id = ?
                ORDER BY tile_id ASC
                """,
                (str(project_id or ""),),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def load_tile(self, *, project_id: str, tile_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM mosaic_tile WHERE project_id = ? AND tile_id = ? LIMIT 1",
                (str(project_id or ""), str(tile_id or "")),
            ).fetchone()
        return self._row_to_dict(row)

    def non_accepted_tiles(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM mosaic_tile
                WHERE project_id = ?
                  AND qa_status != ?
                ORDER BY tile_id ASC
                """,
                (str(project_id or ""), QA_STATUS_ACCEPTED),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def next_attempt_no(self, *, project_id: str, tile_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(attempt_no), 0) AS max_attempt_no
                FROM mosaic_attempt
                WHERE project_id = ? AND tile_id = ?
                """,
                (str(project_id or ""), str(tile_id or "")),
            ).fetchone()
        max_attempt_no = int((row[0] if row else 0) or 0)
        return max_attempt_no + 1

    def append_attempt(
        self,
        *,
        project_id: str,
        tile_id: str,
        attempt_no: int,
        collection_id: str | None,
        attempt_status: str,
        api_status: str | None,
        request_payload: dict[str, Any] | None,
        response_payload: dict[str, Any] | None,
        error_text: str,
        mutation_source: str,
    ) -> None:
        now = utc_now_iso()
        request_json = json.dumps(request_payload or {}, sort_keys=True)
        response_json = json.dumps(response_payload or {}, sort_keys=True)
        collection_value = str(collection_id or "").strip() or None
        api_status_value = str(api_status or "").strip() or API_STATUS_NOT_SUBMITTED
        with self._connect() as conn:
            conn.execute("BEGIN")
            prior_row = conn.execute(
                """
                SELECT qa_status, api_status, attempt_count
                FROM mosaic_tile
                WHERE project_id = ? AND tile_id = ?
                LIMIT 1
                """,
                (str(project_id or ""), str(tile_id or "")),
            ).fetchone()
            if prior_row is None:
                raise RuntimeError(f"Tile not found for attempt append: {project_id}/{tile_id}")

            from_qa = str(prior_row[0] or "")
            from_api = str(prior_row[1] or "")
            prev_attempt_count = int(prior_row[2] or 0)

            conn.execute(
                """
                INSERT INTO mosaic_attempt (
                    project_id, tile_id, attempt_no, collection_id,
                    attempt_status, api_status,
                    request_payload_json, response_payload_json,
                    error_text, requested_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(project_id or ""),
                    str(tile_id or ""),
                    int(attempt_no),
                    collection_value,
                    str(attempt_status or ""),
                    api_status_value,
                    request_json,
                    response_json,
                    str(error_text or ""),
                    now,
                    now,
                ),
            )

            conn.execute(
                """
                UPDATE mosaic_tile
                SET
                    latest_collection_id = CASE
                        WHEN ? IS NULL OR ? = '' THEN latest_collection_id
                        ELSE ?
                    END,
                    attempt_count = ?,
                    api_status = ?,
                    last_sync_at = ?,
                    updated_at = ?,
                    mutation_source = ?
                WHERE project_id = ? AND tile_id = ?
                """,
                (
                    collection_value,
                    collection_value,
                    collection_value,
                    max(prev_attempt_count, int(attempt_no)),
                    api_status_value,
                    now,
                    now,
                    str(mutation_source or ""),
                    str(project_id or ""),
                    str(tile_id or ""),
                ),
            )

            if from_api != api_status_value:
                conn.execute(
                    """
                    INSERT INTO mosaic_status_history (
                        project_id, tile_id,
                        from_qa_status, to_qa_status,
                        from_api_status, to_api_status,
                        mutation_source, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(project_id or ""),
                        str(tile_id or ""),
                        from_qa,
                        from_qa,
                        from_api,
                        api_status_value,
                        str(mutation_source or ""),
                        str(attempt_status or ""),
                        now,
                    ),
                )
            conn.commit()

    def update_tile_api_status(
        self,
        *,
        project_id: str,
        tile_id: str,
        api_status: str,
        mutation_source: str,
        note: str = "",
    ) -> bool:
        api_status_value = str(api_status or "").strip() or API_STATUS_NOT_SUBMITTED
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN")
            prior = conn.execute(
                """
                SELECT qa_status, api_status
                FROM mosaic_tile
                WHERE project_id = ? AND tile_id = ?
                LIMIT 1
                """,
                (str(project_id or ""), str(tile_id or "")),
            ).fetchone()
            if prior is None:
                raise RuntimeError(f"Tile not found: {project_id}/{tile_id}")
            from_qa = str(prior[0] or "")
            from_api = str(prior[1] or "")
            changed = from_api != api_status_value

            conn.execute(
                """
                UPDATE mosaic_tile
                SET api_status = ?, last_sync_at = ?, updated_at = ?, mutation_source = ?
                WHERE project_id = ? AND tile_id = ?
                """,
                (
                    api_status_value,
                    now,
                    now,
                    str(mutation_source or ""),
                    str(project_id or ""),
                    str(tile_id or ""),
                ),
            )

            if changed:
                conn.execute(
                    """
                    INSERT INTO mosaic_status_history (
                        project_id, tile_id,
                        from_qa_status, to_qa_status,
                        from_api_status, to_api_status,
                        mutation_source, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(project_id or ""),
                        str(tile_id or ""),
                        from_qa,
                        from_qa,
                        from_api,
                        api_status_value,
                        str(mutation_source or ""),
                        str(note or "status_refresh"),
                        now,
                    ),
                )
            conn.commit()
            return changed

    def mark_tile_accepted(
        self,
        *,
        project_id: str,
        tile_id: str,
        accepted_by: str,
        mutation_source: str = MUTATION_SOURCE_ACCEPT,
        note: str = "manual_accept",
    ) -> bool:
        now = utc_now_iso()
        accepted_by_value = str(accepted_by or "").strip()
        with self._connect() as conn:
            conn.execute("BEGIN")
            prior = conn.execute(
                """
                SELECT qa_status, api_status
                FROM mosaic_tile
                WHERE project_id = ? AND tile_id = ?
                LIMIT 1
                """,
                (str(project_id or ""), str(tile_id or "")),
            ).fetchone()
            if prior is None:
                raise RuntimeError(f"Tile not found: {project_id}/{tile_id}")
            from_qa = str(prior[0] or "")
            from_api = str(prior[1] or "")
            if from_qa == QA_STATUS_ACCEPTED:
                conn.commit()
                return False

            conn.execute(
                """
                UPDATE mosaic_tile
                SET qa_status = ?, accepted_at = ?, accepted_by = ?, updated_at = ?, mutation_source = ?
                WHERE project_id = ? AND tile_id = ?
                """,
                (
                    QA_STATUS_ACCEPTED,
                    now,
                    accepted_by_value,
                    now,
                    str(mutation_source or ""),
                    str(project_id or ""),
                    str(tile_id or ""),
                ),
            )
            conn.execute(
                """
                INSERT INTO mosaic_status_history (
                    project_id, tile_id,
                    from_qa_status, to_qa_status,
                    from_api_status, to_api_status,
                    mutation_source, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(project_id or ""),
                    str(tile_id or ""),
                    from_qa,
                    QA_STATUS_ACCEPTED,
                    from_api,
                    from_api,
                    str(mutation_source or ""),
                    str(note or "manual_accept"),
                    now,
                ),
            )
            conn.commit()
            return True

    def list_attempts(self, *, project_id: str, tile_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM mosaic_attempt
                WHERE project_id = ? AND tile_id = ?
                ORDER BY attempt_no ASC
                """,
                (str(project_id or ""), str(tile_id or "")),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        if row is None:
            return {}
        if isinstance(row, sqlite3.Row):
            return {key: row[key] for key in row.keys()}
        if isinstance(row, dict):
            return dict(row)
        return {}
