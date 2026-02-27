# -*- coding: utf-8 -*-
"""Asset Intel SQLite service."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re
import sqlite3
import uuid
from typing import Any


MANUAL_BATCH_SOURCE = "manual://asset-intel"
BASE_REQUIRED_TABLES = {
    "import_batch",
    "asset",
    "asset_taxonomy",
    "section_instance",
    "asset_attribute_value",
    "asset_text_block",
    "asset_source_link",
}

APP_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS asset_profile (
    asset_id TEXT PRIMARY KEY,
    type TEXT,
    origin TEXT,
    proliferation TEXT,
    domain TEXT,
    builder TEXT,
    alt_designation TEXT,
    crew TEXT,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS asset_dimension (
    asset_id TEXT PRIMARY KEY,
    length_raw TEXT,
    width_raw TEXT,
    draft_raw TEXT,
    tonnage_raw TEXT,
    length_m REAL,
    width_m REAL,
    draft_m REAL,
    tonnage_mt REAL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS asset_system (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    section_instance_id INTEGER,
    system_name TEXT NOT NULL,
    system_category TEXT,
    description TEXT,
    page_start INTEGER,
    page_end INTEGER,
    display_order INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'parser',
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE,
    FOREIGN KEY(section_instance_id) REFERENCES section_instance(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_system_section_unique
    ON asset_system(section_instance_id);
CREATE INDEX IF NOT EXISTS idx_asset_system_asset ON asset_system(asset_id);

CREATE TABLE IF NOT EXISTS asset_system_attribute (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    system_id INTEGER NOT NULL,
    attr_key TEXT NOT NULL,
    attr_value TEXT NOT NULL,
    value_type TEXT,
    num_value REAL,
    unit TEXT,
    bool_value INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(system_id) REFERENCES asset_system(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asset_system_attr_system ON asset_system_attribute(system_id);

CREATE TABLE IF NOT EXISTS fleet_unit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    display_name TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    source TEXT NOT NULL DEFAULT 'parser',
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fleet_unit_asset ON fleet_unit(asset_id);

CREATE TABLE IF NOT EXISTS fleet_unit_identifier (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL,
    identifier_type TEXT NOT NULL,
    identifier_raw TEXT NOT NULL,
    identifier_norm TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    confidence REAL,
    source_system_id INTEGER,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(unit_id) REFERENCES fleet_unit(id) ON DELETE CASCADE,
    FOREIGN KEY(source_system_id) REFERENCES asset_system(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_fleet_unit_identifier_unit ON fleet_unit_identifier(unit_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fleet_unit_identifier_type_norm
    ON fleet_unit_identifier(identifier_type, identifier_norm);

CREATE TABLE IF NOT EXISTS fleet_unit_system_fit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL,
    system_id INTEGER NOT NULL,
    fit_status TEXT NOT NULL DEFAULT 'unknown',
    quantity REAL,
    effective_from TEXT,
    effective_to TEXT,
    source TEXT NOT NULL DEFAULT 'parser',
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(unit_id) REFERENCES fleet_unit(id) ON DELETE CASCADE,
    FOREIGN KEY(system_id) REFERENCES asset_system(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fleet_unit_fit_unit ON fleet_unit_system_fit(unit_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fleet_unit_fit_unit_system
    ON fleet_unit_system_fit(unit_id, system_id);

CREATE TABLE IF NOT EXISTS analyst_note (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    system_id INTEGER,
    fleet_unit_id INTEGER,
    analyst_name TEXT NOT NULL,
    note_title TEXT,
    note_text TEXT NOT NULL,
    note_type TEXT NOT NULL DEFAULT 'observation',
    priority TEXT NOT NULL DEFAULT 'medium',
    confidence TEXT,
    source_reliability TEXT,
    information_credibility TEXT,
    event_time_utc TEXT,
    reported_time_utc TEXT,
    location_text TEXT,
    tags_csv TEXT,
    source_ref TEXT,
    is_ai_generated INTEGER NOT NULL DEFAULT 0,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE,
    FOREIGN KEY(system_id) REFERENCES asset_system(id) ON DELETE SET NULL,
    FOREIGN KEY(fleet_unit_id) REFERENCES fleet_unit(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_analyst_note_asset ON analyst_note(asset_id);
CREATE INDEX IF NOT EXISTS idx_analyst_note_system ON analyst_note(system_id);
CREATE INDEX IF NOT EXISTS idx_analyst_note_event ON analyst_note(event_time_utc);

CREATE INDEX IF NOT EXISTS idx_asset_profile_domain ON asset_profile(domain);
CREATE INDEX IF NOT EXISTS idx_asset_profile_type ON asset_profile(type);
CREATE INDEX IF NOT EXISTS idx_asset_profile_origin ON asset_profile(origin);
CREATE INDEX IF NOT EXISTS idx_asset_profile_builder ON asset_profile(builder);
"""


SYSTEM_SECTION_KEYWORDS = (
    "system",
    "systems",
    "weapon",
    "propulsion",
    "protection",
    "radar",
    "sonar",
    "communications",
    "aviation",
    "aircraft",
    "torpedo",
    "missile",
    "gun",
    "fire control",
    "launcher",
    "mine",
    "armament",
)

SYSTEM_SECTION_EXACT_EXCLUDE = {
    "",
    "root",
    "tiers",
    "notes",
    "image sources",
    "variants",
    "dimensions",
    "unknown",
    "name",
    "type",
    "quantity",
    "basic load",
    "caliber",
    "length",
    "diameter",
    "weight",
}

IDENTIFIER_KEY_TYPE_MAP = {
    "pennant": "pennant",
    "pennantno": "pennant",
    "pennantnumber": "pennant",
    "pendent": "pennant",
    "hullno": "hull",
    "hullnumber": "hull",
    "imo": "imo",
    "imonumber": "imo",
    "mmsi": "mmsi",
    "callsign": "callsign",
}

NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
UNITED_NUMBER_RE = re.compile(
    r"([-+]?\d[\d,]*(?:\.\d+)?)\s*(m|meter|meters|metre|metres|ft|feet|foot|in|inch|inches|cm|mm|km)\\b",
    re.IGNORECASE,
)
TONNAGE_RE = re.compile(
    r"([-+]?\d[\d,]*(?:\.\d+)?)\s*(long tons?|short tons?|metric tons?|tonnes?|tons?|t|kg)\\b",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(value: Any, max_len: int = 4000) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text.strip())
    if max_len > 0 and len(text) > max_len:
        return text[:max_len]
    return text


def _dedupe_tokens_case_insensitive(tokens: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        value = _clean_text(token, max_len=240)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def split_domain_tokens(raw_domain: Any) -> list[str]:
    text = _clean_text(raw_domain, max_len=1200)
    if not text:
        return []
    parts = [_clean_text(part, max_len=240) for part in text.split(",")]
    return _dedupe_tokens_case_insensitive(parts)


def normalize_domain_hierarchy(
    domain: Any = None,
    sub_domain_1: Any = None,
    sub_domain_2: Any = None,
    *,
    fallback_domain: Any = "",
) -> dict[str, Any]:
    main_value = _clean_text(domain, max_len=240) if domain is not None else ""
    sub_1_value = _clean_text(sub_domain_1, max_len=240) if sub_domain_1 is not None else ""
    sub_2_value = _clean_text(sub_domain_2, max_len=240) if sub_domain_2 is not None else ""
    has_explicit_inputs = any(value is not None for value in (domain, sub_domain_1, sub_domain_2))

    if has_explicit_inputs:
        if main_value and not sub_1_value and not sub_2_value:
            tokens = split_domain_tokens(main_value)
        else:
            tokens = _dedupe_tokens_case_insensitive([main_value, sub_1_value, sub_2_value])
    else:
        tokens = split_domain_tokens(fallback_domain)

    return {
        "domain": ", ".join(tokens),
        "main_domain": tokens[0] if len(tokens) > 0 else "",
        "sub_domain_1": tokens[1] if len(tokens) > 1 else "",
        "sub_domain_2": tokens[2] if len(tokens) > 2 else "",
        "tokens": tokens,
    }


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean_text(value)
    if not text:
        return None
    m = NUMBER_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except Exception:
        return None


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    text = _clean_text(value, max_len=120)
    if not text:
        return None
    return _to_float(text)


def _normalize_key_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _clean_text(value, max_len=200).lower())


def _infer_identifier_type(raw_key: str) -> str:
    token = _normalize_key_token(raw_key)
    if not token:
        return ""
    mapped = IDENTIFIER_KEY_TYPE_MAP.get(token)
    if mapped:
        return mapped
    if "pennant" in token or token == "pendent":
        return "pennant"
    if token in {"imo", "imonumber"}:
        return "imo"
    if token == "mmsi":
        return "mmsi"
    if "callsign" in token:
        return "callsign"
    return ""


def _normalize_identifier_value(raw_value: str) -> str:
    text = _clean_text(raw_value, max_len=240).upper()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _parse_dimension_meters(raw_value: str) -> float | None:
    text = _clean_text(raw_value).lower()
    if not text:
        return None
    unit_match = UNITED_NUMBER_RE.search(text)
    if unit_match:
        number = _to_float(unit_match.group(1))
        if number is None:
            return None
        unit = unit_match.group(2).lower()
        if unit in {"m", "meter", "meters", "metre", "metres"}:
            return number
        if unit == "km":
            return number * 1000.0
        if unit == "cm":
            return number * 0.01
        if unit == "mm":
            return number * 0.001
        if unit in {"ft", "feet", "foot"}:
            return number * 0.3048
        if unit in {"in", "inch", "inches"}:
            return number * 0.0254
    number = _to_float(text)
    if number is None:
        return None
    return number


def _parse_tonnage_metric_tons(raw_value: str) -> float | None:
    text = _clean_text(raw_value).lower()
    if not text:
        return None
    match = TONNAGE_RE.search(text)
    if match:
        number = _to_float(match.group(1))
        if number is None:
            return None
        unit = match.group(2).lower()
        if "long ton" in unit:
            return number * 1.0160469088
        if "short ton" in unit:
            return number * 0.90718474
        if unit == "kg":
            return number / 1000.0
        return number
    return _to_float(text)


class AssetIntelService:
    def __init__(self, db_path: str = ""):
        self.db_path = ""
        self._ready = False
        self._last_message = "Asset Intel DB path not configured."
        self.set_db_path(db_path)

    def set_db_path(self, db_path: str) -> None:
        self.db_path = _clean_text(db_path, max_len=2048)
        self._ready = False
        self._last_message = "Asset Intel DB path not configured."

    def is_ready(self) -> bool:
        if self._ready:
            return True
        return bool(self.validate().get("ok"))

    def validate(self) -> dict[str, Any]:
        db_path = _clean_text(self.db_path, max_len=2048)
        if not db_path:
            self._ready = False
            self._last_message = "Asset Intel DB path not configured."
            return {"ok": False, "message": self._last_message}
        if not os.path.exists(db_path):
            self._ready = False
            self._last_message = f"Asset Intel DB not found: {db_path}"
            return {"ok": False, "message": self._last_message}

        try:
            with self._connect() as conn:
                missing = [name for name in BASE_REQUIRED_TABLES if not self._table_exists(conn, name)]
                if missing:
                    self._ready = False
                    self._last_message = "Asset Intel DB schema missing tables: " + ", ".join(sorted(missing))
                    return {"ok": False, "message": self._last_message}

                self._ensure_app_schema(conn)
                self._sync_asset_profiles(conn)
                self._sync_asset_dimensions(conn)
                self._sync_asset_systems(conn)
                self._sync_fleet_units(conn)
                asset_count = _to_int(conn.execute("SELECT COUNT(*) FROM asset").fetchone()[0], default=0)
                note_count = _to_int(conn.execute("SELECT COUNT(*) FROM analyst_note").fetchone()[0], default=0)
                fleet_unit_count = _to_int(conn.execute("SELECT COUNT(*) FROM fleet_unit").fetchone()[0], default=0)
                conn.commit()

            self._ready = True
            self._last_message = (
                f"Asset Intel DB ready ({asset_count} assets, {fleet_unit_count} units, {note_count} analyst notes)."
            )
            return {"ok": True, "message": self._last_message}
        except Exception as exc:
            self._ready = False
            self._last_message = f"Asset Intel DB validation failed: {exc}"
            return {"ok": False, "message": self._last_message}

    def list_facets(self) -> dict[str, Any]:
        self._require_ready()
        with self._connect() as conn:
            return {
                "domain": self._facet_rows(conn, "domain"),
                "domain_main": self._taxonomy_token_facet_rows(conn, token_order=1),
                "sub_domain_1": self._taxonomy_token_facet_rows(conn, token_order=2),
                "sub_domain_2": self._taxonomy_token_facet_rows(conn, token_order=3),
                "type": self._facet_rows(conn, "type"),
                "type_by_sub_domain_2": self._type_rows_by_sub_domain_2(conn),
                "origin": self._facet_rows(conn, "origin"),
                "proliferation": self._facet_rows(conn, "proliferation"),
                "builder": self._facet_rows(conn, "builder"),
            }

    def search_assets(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        self._require_ready()
        request = payload if isinstance(payload, dict) else {}
        query_text = _clean_text(request.get("query_text"), max_len=400)
        domain = _clean_text(request.get("domain"), max_len=200)
        main_domain = _clean_text(request.get("main_domain"), max_len=200)
        sub_domain_1 = _clean_text(request.get("sub_domain_1"), max_len=200)
        sub_domain_2 = _clean_text(request.get("sub_domain_2"), max_len=200)
        type_value = _clean_text(request.get("type"), max_len=200)
        origin = _clean_text(request.get("origin"), max_len=200)
        proliferation = _clean_text(request.get("proliferation"), max_len=200)
        builder = _clean_text(request.get("builder"), max_len=200)
        length_min_m = _to_float(request.get("length_min_m"))
        length_max_m = _to_float(request.get("length_max_m"))
        width_min_m = _to_float(request.get("width_min_m"))
        width_max_m = _to_float(request.get("width_max_m"))
        if length_min_m is not None and length_min_m < 0:
            length_min_m = None
        if length_max_m is not None and length_max_m < 0:
            length_max_m = None
        if width_min_m is not None and width_min_m < 0:
            width_min_m = None
        if width_max_m is not None and width_max_m < 0:
            width_max_m = None
        limit = _to_int(request.get("limit"), default=250)
        limit = max(1, min(limit, 2000))
        if length_min_m is not None and length_max_m is not None and length_min_m > length_max_m:
            length_min_m, length_max_m = length_max_m, length_min_m
        if width_min_m is not None and width_max_m is not None and width_min_m > width_max_m:
            width_min_m, width_max_m = width_max_m, width_min_m

        sql = """
            SELECT
                a.asset_id,
                COALESCE(NULLIF(a.title, ''), a.asset_id) AS title,
                a.weg_url,
                a.start_page,
                a.end_page,
                p.type,
                p.origin,
                p.proliferation,
                p.domain,
                p.builder,
                d.length_m,
                d.width_m,
                d.draft_m,
                d.tonnage_mt
            FROM asset a
            LEFT JOIN asset_profile p ON p.asset_id = a.asset_id
            LEFT JOIN asset_dimension d ON d.asset_id = a.asset_id
        """

        conditions: list[str] = []
        params: list[Any] = []

        if query_text:
            like_value = f"%{query_text.lower()}%"
            conditions.append(
                """
                (
                    lower(coalesce(a.title, '')) LIKE ?
                    OR lower(a.asset_id) LIKE ?
                    OR lower(coalesce(p.type, '')) LIKE ?
                    OR lower(coalesce(p.origin, '')) LIKE ?
                    OR lower(coalesce(p.proliferation, '')) LIKE ?
                    OR lower(coalesce(p.domain, '')) LIKE ?
                    OR lower(coalesce(p.builder, '')) LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM asset_attribute_value av
                        WHERE av.asset_id = a.asset_id
                          AND lower(coalesce(av.raw_value, '')) LIKE ?
                    )
                    OR EXISTS (
                        SELECT 1 FROM asset_system s
                        WHERE s.asset_id = a.asset_id
                          AND (
                            lower(coalesce(s.system_name, '')) LIKE ?
                            OR lower(coalesce(s.description, '')) LIKE ?
                            OR EXISTS (
                                SELECT 1 FROM asset_system_attribute sa
                                WHERE sa.system_id = s.id
                                  AND (
                                    lower(coalesce(sa.attr_key, '')) LIKE ?
                                    OR lower(coalesce(sa.attr_value, '')) LIKE ?
                                  )
                            )
                          )
                    )
                    OR EXISTS (
                        SELECT 1 FROM analyst_note n
                        WHERE n.asset_id = a.asset_id
                          AND (
                            lower(coalesce(n.note_title, '')) LIKE ?
                            OR lower(coalesce(n.note_text, '')) LIKE ?
                            OR lower(coalesce(n.tags_csv, '')) LIKE ?
                          )
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM fleet_unit fu
                        LEFT JOIN fleet_unit_identifier fui ON fui.unit_id = fu.id
                        WHERE fu.asset_id = a.asset_id
                          AND (
                            lower(coalesce(fu.display_name, '')) LIKE ?
                            OR lower(coalesce(fui.identifier_raw, '')) LIKE ?
                            OR lower(coalesce(fui.identifier_norm, '')) LIKE ?
                          )
                    )
                )
                """
            )
            params.extend([like_value] * 18)

        if main_domain:
            conditions.append(
                """
                (
                    EXISTS (
                        SELECT 1
                        FROM asset_taxonomy tx
                        WHERE tx.asset_id = a.asset_id
                          AND tx.kind = 'domain'
                          AND tx.token_order = 1
                          AND lower(coalesce(tx.token_value, '')) = ?
                    )
                    OR lower(
                        trim(
                            CASE
                                WHEN instr(coalesce(p.domain, ''), ',') > 0
                                    THEN substr(coalesce(p.domain, ''), 1, instr(coalesce(p.domain, ''), ',') - 1)
                                ELSE coalesce(p.domain, '')
                            END
                        )
                    ) = ?
                )
                """
            )
            params.append(main_domain.lower())
            params.append(main_domain.lower())
        elif domain:
            conditions.append("lower(coalesce(p.domain, '')) = ?")
            params.append(domain.lower())
        if sub_domain_1:
            conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM asset_taxonomy tx
                    WHERE tx.asset_id = a.asset_id
                      AND tx.kind = 'domain'
                      AND tx.token_order = 2
                      AND lower(coalesce(tx.token_value, '')) = ?
                )
                """
            )
            params.append(sub_domain_1.lower())
        if sub_domain_2:
            conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM asset_taxonomy tx
                    WHERE tx.asset_id = a.asset_id
                      AND tx.kind = 'domain'
                      AND tx.token_order = 3
                      AND lower(coalesce(tx.token_value, '')) = ?
                )
                """
            )
            params.append(sub_domain_2.lower())
        if type_value:
            conditions.append("lower(coalesce(p.type, '')) = ?")
            params.append(type_value.lower())
        if origin:
            conditions.append("lower(coalesce(p.origin, '')) = ?")
            params.append(origin.lower())
        if proliferation:
            conditions.append("lower(coalesce(p.proliferation, '')) = ?")
            params.append(proliferation.lower())
        if builder:
            conditions.append("lower(coalesce(p.builder, '')) = ?")
            params.append(builder.lower())
        if length_min_m is not None:
            conditions.append("d.length_m >= ?")
            params.append(length_min_m)
        if length_max_m is not None:
            conditions.append("d.length_m <= ?")
            params.append(length_max_m)
        if width_min_m is not None:
            conditions.append("d.width_m >= ?")
            params.append(width_min_m)
        if width_max_m is not None:
            conditions.append("d.width_m <= ?")
            params.append(width_max_m)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += """
            ORDER BY
                CASE WHEN a.start_page > 0 THEN a.start_page ELSE 2147483647 END,
                lower(coalesce(a.title, a.asset_id)),
                a.asset_id
            LIMIT ?
        """
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "asset_id": _clean_text(row["asset_id"], max_len=64),
                    "title": _clean_text(row["title"], max_len=600),
                    "weg_url": _clean_text(row["weg_url"], max_len=2048),
                    "start_page": _to_int(row["start_page"], default=0),
                    "end_page": _to_int(row["end_page"], default=0),
                    "type": _clean_text(row["type"], max_len=240),
                    "origin": _clean_text(row["origin"], max_len=240),
                    "proliferation": _clean_text(row["proliferation"], max_len=240),
                    "domain": _clean_text(row["domain"], max_len=240),
                    "builder": _clean_text(row["builder"], max_len=240),
                    "length_m": self._rounded(row["length_m"]),
                    "width_m": self._rounded(row["width_m"]),
                    "draft_m": self._rounded(row["draft_m"]),
                    "tonnage_mt": self._rounded(row["tonnage_mt"]),
                }
                for row in rows
            ]

    def get_asset_detail(self, asset_id: str) -> dict[str, Any] | None:
        selected_asset_id = _clean_text(asset_id, max_len=80).lower()
        if not selected_asset_id:
            return None
        self._require_ready()

        with self._connect() as conn:
            asset_row = conn.execute(
                """
                SELECT
                    a.asset_id,
                    a.title,
                    a.weg_url,
                    a.start_page,
                    a.end_page,
                    p.type,
                    p.origin,
                    p.proliferation,
                    p.domain,
                    p.builder,
                    p.alt_designation,
                    p.crew,
                    d.length_raw,
                    d.width_raw,
                    d.draft_raw,
                    d.tonnage_raw,
                    d.length_m,
                    d.width_m,
                    d.draft_m,
                    d.tonnage_mt
                FROM asset a
                LEFT JOIN asset_profile p ON p.asset_id = a.asset_id
                LEFT JOIN asset_dimension d ON d.asset_id = a.asset_id
                WHERE lower(a.asset_id) = ?
                LIMIT 1
                """,
                (selected_asset_id,),
            ).fetchone()
            if asset_row is None:
                return None

            asset_payload = {
                "asset_id": _clean_text(asset_row["asset_id"], max_len=80),
                "title": _clean_text(asset_row["title"], max_len=800),
                "weg_url": _clean_text(asset_row["weg_url"], max_len=2048),
                "start_page": _to_int(asset_row["start_page"], default=0),
                "end_page": _to_int(asset_row["end_page"], default=0),
                "type": _clean_text(asset_row["type"], max_len=240),
                "origin": _clean_text(asset_row["origin"], max_len=240),
                "proliferation": _clean_text(asset_row["proliferation"], max_len=240),
                "domain": _clean_text(asset_row["domain"], max_len=240),
                "builder": _clean_text(asset_row["builder"], max_len=240),
                "alt_designation": _clean_text(asset_row["alt_designation"], max_len=240),
                "crew": _clean_text(asset_row["crew"], max_len=120),
                "length_raw": _clean_text(asset_row["length_raw"], max_len=120),
                "width_raw": _clean_text(asset_row["width_raw"], max_len=120),
                "draft_raw": _clean_text(asset_row["draft_raw"], max_len=120),
                "tonnage_raw": _clean_text(asset_row["tonnage_raw"], max_len=120),
                "length_m": self._rounded(asset_row["length_m"]),
                "width_m": self._rounded(asset_row["width_m"]),
                "draft_m": self._rounded(asset_row["draft_m"]),
                "tonnage_mt": self._rounded(asset_row["tonnage_mt"]),
            }
            domain_token_rows = conn.execute(
                """
                SELECT token_order, token_value
                FROM asset_taxonomy
                WHERE asset_id = ?
                  AND kind = 'domain'
                  AND token_order > 0
                ORDER BY token_order ASC, id ASC
                """,
                (asset_payload["asset_id"],),
            ).fetchall()
            domain_tokens = [
                _clean_text(row["token_value"], max_len=240)
                for row in domain_token_rows
                if _clean_text(row["token_value"], max_len=240)
            ]
            if not domain_tokens:
                domain_tokens = split_domain_tokens(asset_payload.get("domain"))
            normalized_domain = normalize_domain_hierarchy(
                domain_tokens[0] if len(domain_tokens) > 0 else None,
                domain_tokens[1] if len(domain_tokens) > 1 else None,
                domain_tokens[2] if len(domain_tokens) > 2 else None,
            )
            if not asset_payload.get("domain") and normalized_domain.get("domain"):
                asset_payload["domain"] = normalized_domain.get("domain")
            asset_payload["sub_domain_1"] = normalized_domain.get("sub_domain_1") or ""
            asset_payload["sub_domain_2"] = normalized_domain.get("sub_domain_2") or ""

            overview: list[dict[str, str]] = []
            for key, label in (
                ("type", "Type"),
                ("domain", "Domain"),
                ("sub_domain_1", "Sub Domain 1"),
                ("sub_domain_2", "Sub Domain 2"),
                ("origin", "Origin"),
                ("proliferation", "Proliferation"),
                ("builder", "Builder"),
                ("alt_designation", "Alternative Designation"),
                ("crew", "Crew"),
                ("length_raw", "Length"),
                ("width_raw", "Width / Beam"),
                ("draft_raw", "Draft"),
                ("tonnage_raw", "Tonnage / Displacement"),
            ):
                value = _clean_text(asset_payload.get(key))
                if value:
                    overview.append({"key": label, "value": value})

            note_counts_by_system: dict[int, int] = {}
            for row in conn.execute(
                """
                SELECT system_id, COUNT(*) AS count_value
                FROM analyst_note
                WHERE asset_id = ?
                  AND system_id IS NOT NULL
                GROUP BY system_id
                """,
                (asset_payload["asset_id"],),
            ).fetchall():
                sid = _to_int(row["system_id"], default=0)
                if sid > 0:
                    note_counts_by_system[sid] = _to_int(row["count_value"], default=0)

            note_counts_by_unit: dict[int, int] = {}
            for row in conn.execute(
                """
                SELECT fleet_unit_id, COUNT(*) AS count_value
                FROM analyst_note
                WHERE asset_id = ?
                  AND fleet_unit_id IS NOT NULL
                GROUP BY fleet_unit_id
                """,
                (asset_payload["asset_id"],),
            ).fetchall():
                unit_id = _to_int(row["fleet_unit_id"], default=0)
                if unit_id > 0:
                    note_counts_by_unit[unit_id] = _to_int(row["count_value"], default=0)

            systems: list[dict[str, Any]] = []
            system_rows = conn.execute(
                """
                SELECT
                    id,
                    system_name,
                    system_category,
                    description,
                    page_start,
                    page_end,
                    source
                FROM asset_system
                WHERE asset_id = ?
                ORDER BY display_order, id
                """,
                (asset_payload["asset_id"],),
            ).fetchall()
            for row in system_rows:
                system_id = _to_int(row["id"], default=0)
                attr_rows = conn.execute(
                    """
                    SELECT
                        id,
                        attr_key,
                        attr_value,
                        value_type,
                        num_value,
                        unit,
                        bool_value
                    FROM asset_system_attribute
                    WHERE system_id = ?
                    ORDER BY sort_order, id
                    """,
                    (system_id,),
                ).fetchall()
                attrs = [
                    {
                        "id": _to_int(attr["id"], default=0),
                        "key": _clean_text(attr["attr_key"], max_len=180),
                        "value": _clean_text(attr["attr_value"], max_len=1600),
                        "value_type": _clean_text(attr["value_type"], max_len=20),
                        "num_value": self._rounded(attr["num_value"]),
                        "unit": _clean_text(attr["unit"], max_len=80),
                        "bool_value": _to_int(attr["bool_value"], default=0)
                        if attr["bool_value"] is not None
                        else None,
                    }
                    for attr in attr_rows
                ]
                systems.append(
                    {
                        "system_id": system_id,
                        "name": _clean_text(row["system_name"], max_len=300),
                        "category": _clean_text(row["system_category"], max_len=200),
                        "description": _clean_text(row["description"], max_len=1600),
                        "page_start": _to_int(row["page_start"], default=0),
                        "page_end": _to_int(row["page_end"], default=0),
                        "source": _clean_text(row["source"], max_len=80),
                        "note_count": note_counts_by_system.get(system_id, 0),
                        "attributes": attrs,
                    }
                )

            fielded_units: list[dict[str, Any]] = []
            unit_rows = conn.execute(
                """
                SELECT
                    id,
                    display_name,
                    status,
                    source
                FROM fleet_unit
                WHERE asset_id = ?
                ORDER BY lower(coalesce(display_name, '')), id
                """,
                (asset_payload["asset_id"],),
            ).fetchall()
            for row in unit_rows:
                unit_id = _to_int(row["id"], default=0)
                if unit_id <= 0:
                    continue

                identifier_rows = conn.execute(
                    """
                    SELECT
                        id,
                        identifier_type,
                        identifier_raw,
                        identifier_norm,
                        is_primary,
                        confidence
                    FROM fleet_unit_identifier
                    WHERE unit_id = ?
                    ORDER BY is_primary DESC, id
                    """,
                    (unit_id,),
                ).fetchall()
                identifiers = [
                    {
                        "id": _to_int(identifier["id"], default=0),
                        "identifier_type": _clean_text(identifier["identifier_type"], max_len=80),
                        "identifier_raw": _clean_text(identifier["identifier_raw"], max_len=240),
                        "identifier_norm": _clean_text(identifier["identifier_norm"], max_len=240),
                        "is_primary": bool(_to_int(identifier["is_primary"], default=0)),
                        "confidence": self._rounded(identifier["confidence"]),
                    }
                    for identifier in identifier_rows
                ]

                primary_identifier = ""
                primary_identifier_type = ""
                for identifier in identifiers:
                    if bool(identifier.get("is_primary")):
                        primary_identifier = _clean_text(identifier.get("identifier_raw"), max_len=240)
                        primary_identifier_type = _clean_text(identifier.get("identifier_type"), max_len=80)
                        break
                if not primary_identifier and identifiers:
                    primary_identifier = _clean_text(identifiers[0].get("identifier_raw"), max_len=240)
                    primary_identifier_type = _clean_text(identifiers[0].get("identifier_type"), max_len=80)

                fit_rows = conn.execute(
                    """
                    SELECT
                        f.id AS fit_id,
                        f.system_id,
                        f.fit_status,
                        f.quantity,
                        s.system_name,
                        s.system_category
                    FROM fleet_unit_system_fit f
                    LEFT JOIN asset_system s ON s.id = f.system_id
                    WHERE f.unit_id = ?
                    ORDER BY s.display_order, s.id
                    """,
                    (unit_id,),
                ).fetchall()
                linked_systems: list[dict[str, Any]] = []
                linked_system_ids: list[int] = []
                for fit_row in fit_rows:
                    fit_id = _to_int(fit_row["fit_id"], default=0)
                    system_id = _to_int(fit_row["system_id"], default=0)
                    if system_id > 0:
                        linked_system_ids.append(system_id)
                    linked_systems.append(
                        {
                            "fit_id": fit_id,
                            "system_id": system_id,
                            "fit_status": _clean_text(fit_row["fit_status"], max_len=80),
                            "quantity": self._rounded(fit_row["quantity"]),
                            "system_name": _clean_text(fit_row["system_name"], max_len=300),
                            "system_category": _clean_text(fit_row["system_category"], max_len=200),
                        }
                    )

                display_name = _clean_text(row["display_name"], max_len=300)
                if not display_name:
                    display_name = primary_identifier or f"Unit {unit_id}"

                fielded_units.append(
                    {
                        "unit_id": unit_id,
                        "display_name": display_name,
                        "status": _clean_text(row["status"], max_len=80),
                        "source": _clean_text(row["source"], max_len=80),
                        "primary_identifier": primary_identifier,
                        "primary_identifier_type": primary_identifier_type,
                        "identifiers": identifiers,
                        "linked_system_count": len(linked_systems),
                        "linked_system_ids": linked_system_ids,
                        "linked_systems": linked_systems,
                        "note_count": note_counts_by_unit.get(unit_id, 0),
                    }
                )

            source_rows = conn.execute(
                """
                SELECT url, source_context, page_no, line_no
                FROM asset_source_link
                WHERE asset_id = ?
                ORDER BY page_no, line_no, id
                """,
                (asset_payload["asset_id"],),
            ).fetchall()
            seen_source_keys: set[tuple[str, str, int]] = set()
            sources: list[dict[str, Any]] = []
            for row in source_rows:
                url = _clean_text(row["url"], max_len=2048)
                if not url:
                    continue
                source_context = _clean_text(row["source_context"], max_len=240)
                page_no = _to_int(row["page_no"], default=0)
                dedupe_key = (url, source_context, page_no)
                if dedupe_key in seen_source_keys:
                    continue
                seen_source_keys.add(dedupe_key)
                sources.append(
                    {
                        "url": url,
                        "source_context": source_context,
                        "page_no": page_no,
                        "line_no": _to_int(row["line_no"], default=0),
                    }
                )

            raw_rows = conn.execute(
                """
                SELECT block_type, text, page_no, line_no
                FROM asset_text_block
                WHERE asset_id = ?
                ORDER BY block_order, id
                """,
                (asset_payload["asset_id"],),
            ).fetchall()
            raw_text = [
                {
                    "block_type": _clean_text(row["block_type"], max_len=80),
                    "text": _clean_text(row["text"], max_len=4000),
                    "page_no": _to_int(row["page_no"], default=0),
                    "line_no": _to_int(row["line_no"], default=0),
                }
                for row in raw_rows
            ]

            note_rows = conn.execute(
                """
                SELECT
                    n.id,
                    n.asset_id,
                    n.system_id,
                    s.system_name,
                    n.fleet_unit_id,
                    fu.display_name AS fleet_unit_name,
                    (
                        SELECT fui.identifier_raw
                        FROM fleet_unit_identifier fui
                        WHERE fui.unit_id = n.fleet_unit_id
                        ORDER BY fui.is_primary DESC, fui.id
                        LIMIT 1
                    ) AS fleet_unit_identifier,
                    n.analyst_name,
                    n.note_title,
                    n.note_text,
                    n.note_type,
                    n.priority,
                    n.confidence,
                    n.source_reliability,
                    n.information_credibility,
                    n.event_time_utc,
                    n.reported_time_utc,
                    n.location_text,
                    n.tags_csv,
                    n.source_ref,
                    n.is_ai_generated,
                    n.created_utc,
                    n.updated_utc
                FROM analyst_note n
                LEFT JOIN asset_system s ON s.id = n.system_id
                LEFT JOIN fleet_unit fu ON fu.id = n.fleet_unit_id
                WHERE n.asset_id = ?
                ORDER BY COALESCE(n.event_time_utc, n.created_utc) DESC, n.id DESC
                """,
                (asset_payload["asset_id"],),
            ).fetchall()
            notes = [
                {
                    "note_id": _to_int(row["id"], default=0),
                    "asset_id": _clean_text(row["asset_id"], max_len=80),
                    "system_id": _to_int(row["system_id"], default=0)
                    if row["system_id"] is not None
                    else None,
                    "system_name": _clean_text(row["system_name"], max_len=300),
                    "fleet_unit_id": _to_int(row["fleet_unit_id"], default=0)
                    if row["fleet_unit_id"] is not None
                    else None,
                    "fleet_unit_name": _clean_text(row["fleet_unit_name"], max_len=300),
                    "fleet_unit_identifier": _clean_text(row["fleet_unit_identifier"], max_len=240),
                    "analyst_name": _clean_text(row["analyst_name"], max_len=200),
                    "note_title": _clean_text(row["note_title"], max_len=500),
                    "note_text": _clean_text(row["note_text"], max_len=4000),
                    "note_type": _clean_text(row["note_type"], max_len=80),
                    "priority": _clean_text(row["priority"], max_len=80),
                    "confidence": _clean_text(row["confidence"], max_len=80),
                    "source_reliability": _clean_text(row["source_reliability"], max_len=80),
                    "information_credibility": _clean_text(row["information_credibility"], max_len=80),
                    "event_time_utc": _clean_text(row["event_time_utc"], max_len=80),
                    "reported_time_utc": _clean_text(row["reported_time_utc"], max_len=80),
                    "location_text": _clean_text(row["location_text"], max_len=240),
                    "tags_csv": _clean_text(row["tags_csv"], max_len=500),
                    "source_ref": _clean_text(row["source_ref"], max_len=500),
                    "is_ai_generated": bool(_to_int(row["is_ai_generated"], default=0)),
                    "created_utc": _clean_text(row["created_utc"], max_len=80),
                    "updated_utc": _clean_text(row["updated_utc"], max_len=80),
                }
                for row in note_rows
            ]

            return {
                "asset": asset_payload,
                "overview": overview,
                "systems": systems,
                "fielded_units": fielded_units,
                "sources": sources,
                "raw_text": raw_text,
                "analyst_notes": notes,
            }

    def create_asset(self, payload: dict[str, Any]) -> str:
        self._require_ready()
        request = payload if isinstance(payload, dict) else {}
        asset_id = _clean_text(request.get("asset_id"), max_len=80).lower() or uuid.uuid4().hex
        title = _clean_text(request.get("title"), max_len=800)
        if not title:
            raise ValueError("Asset title is required.")
        weg_url = _clean_text(request.get("weg_url"), max_len=2048)
        start_page = _to_int(request.get("start_page"), default=0)
        end_page = _to_int(request.get("end_page"), default=start_page)
        if end_page < start_page:
            end_page = start_page

        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM asset WHERE lower(asset_id) = ? LIMIT 1",
                (asset_id,),
            ).fetchone()
            if exists is not None:
                raise ValueError(f"Asset already exists: {asset_id}")
            batch_id = self._ensure_manual_batch(conn)
            conn.execute(
                """
                INSERT INTO asset (
                    asset_id,
                    batch_id,
                    title,
                    weg_url,
                    start_page,
                    end_page
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (asset_id, batch_id, title, weg_url, start_page, end_page),
            )
            self._upsert_asset_profile(conn, asset_id, request)
            self._upsert_asset_dimensions(conn, asset_id, request)
            self._replace_taxonomy(conn, asset_id, request)
            conn.commit()
        self._ready = True
        return asset_id

    def update_asset(self, asset_id: str, payload: dict[str, Any]) -> str:
        self._require_ready()
        selected_asset_id = _clean_text(asset_id, max_len=80).lower()
        if not selected_asset_id:
            raise ValueError("Asset ID is required.")
        request = payload if isinstance(payload, dict) else {}

        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT asset_id, title, weg_url, start_page, end_page
                FROM asset
                WHERE lower(asset_id) = ?
                LIMIT 1
                """,
                (selected_asset_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"Asset not found: {selected_asset_id}")

            title = _clean_text(request.get("title", current["title"]), max_len=800)
            if not title:
                raise ValueError("Asset title is required.")
            weg_url = _clean_text(request.get("weg_url", current["weg_url"]), max_len=2048)
            start_page = _to_int(request.get("start_page", current["start_page"]), default=0)
            end_page = _to_int(request.get("end_page", current["end_page"]), default=start_page)
            if end_page < start_page:
                end_page = start_page

            conn.execute(
                """
                UPDATE asset
                SET title = ?, weg_url = ?, start_page = ?, end_page = ?
                WHERE lower(asset_id) = ?
                """,
                (title, weg_url, start_page, end_page, selected_asset_id),
            )
            final_asset_id = _clean_text(current["asset_id"], max_len=80)
            self._upsert_asset_profile(conn, final_asset_id, request)
            self._upsert_asset_dimensions(conn, final_asset_id, request)
            self._replace_taxonomy(conn, final_asset_id, request)
            conn.commit()
            return final_asset_id

    def create_system(self, payload: dict[str, Any]) -> int:
        self._require_ready()
        request = payload if isinstance(payload, dict) else {}
        asset_id = _clean_text(request.get("asset_id"), max_len=80).lower()
        system_name = _clean_text(request.get("name") or request.get("system_name"), max_len=300)
        if not asset_id:
            raise ValueError("Asset ID is required.")
        if not system_name:
            raise ValueError("System name is required.")
        category = _clean_text(request.get("category") or request.get("system_category"), max_len=200)
        description = _clean_text(request.get("description"), max_len=1600)
        source = _clean_text(request.get("source"), max_len=80) or "manual"
        now_utc = _utc_now()

        with self._connect() as conn:
            asset_row = conn.execute(
                "SELECT asset_id FROM asset WHERE lower(asset_id) = ? LIMIT 1",
                (asset_id,),
            ).fetchone()
            if asset_row is None:
                raise ValueError(f"Asset not found: {asset_id}")
            final_asset_id = _clean_text(asset_row["asset_id"], max_len=80)
            display_order_row = conn.execute(
                """
                SELECT COALESCE(MAX(display_order), 0) + 1 AS next_order
                FROM asset_system
                WHERE asset_id = ?
                """,
                (final_asset_id,),
            ).fetchone()
            display_order = _to_int(display_order_row["next_order"] if display_order_row is not None else 1, default=1)
            cur = conn.execute(
                """
                INSERT INTO asset_system (
                    asset_id,
                    section_instance_id,
                    system_name,
                    system_category,
                    description,
                    page_start,
                    page_end,
                    display_order,
                    source,
                    created_utc,
                    updated_utc
                ) VALUES (?, NULL, ?, ?, ?, 0, 0, ?, ?, ?, ?)
                """,
                (
                    final_asset_id,
                    system_name,
                    category,
                    description,
                    display_order,
                    source,
                    now_utc,
                    now_utc,
                ),
            )
            conn.commit()
            return _to_int(cur.lastrowid, default=0)

    def update_system(self, system_id: int, payload: dict[str, Any]) -> int:
        self._require_ready()
        selected_system_id = _to_int(system_id, default=0)
        if selected_system_id <= 0:
            raise ValueError("System ID is required.")
        request = payload if isinstance(payload, dict) else {}

        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT id, system_name, system_category, description, source
                FROM asset_system
                WHERE id = ?
                LIMIT 1
                """,
                (selected_system_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"System not found: {selected_system_id}")

            system_name = _clean_text(
                request.get("name", request.get("system_name", current["system_name"])),
                max_len=300,
            )
            if not system_name:
                raise ValueError("System name is required.")
            category = _clean_text(
                request.get("category", request.get("system_category", current["system_category"])),
                max_len=200,
            )
            description = _clean_text(request.get("description", current["description"]), max_len=1600)
            source = _clean_text(request.get("source", current["source"]), max_len=80) or "manual"
            now_utc = _utc_now()
            conn.execute(
                """
                UPDATE asset_system
                SET
                    system_name = ?,
                    system_category = ?,
                    description = ?,
                    source = ?,
                    updated_utc = ?
                WHERE id = ?
                """,
                (
                    system_name,
                    category,
                    description,
                    source,
                    now_utc,
                    selected_system_id,
                ),
            )
            conn.commit()
            return selected_system_id

    def create_unit(self, payload: dict[str, Any]) -> int:
        self._require_ready()
        request = payload if isinstance(payload, dict) else {}
        asset_id = _clean_text(request.get("asset_id"), max_len=80).lower()
        if not asset_id:
            raise ValueError("Asset ID is required.")
        display_name = _clean_text(request.get("display_name"), max_len=300)
        status = _clean_text(request.get("status"), max_len=80) or "unknown"
        source = _clean_text(request.get("source"), max_len=80) or "manual"
        now_utc = _utc_now()

        with self._connect() as conn:
            asset_row = conn.execute(
                "SELECT asset_id FROM asset WHERE lower(asset_id) = ? LIMIT 1",
                (asset_id,),
            ).fetchone()
            if asset_row is None:
                raise ValueError(f"Asset not found: {asset_id}")
            final_asset_id = _clean_text(asset_row["asset_id"], max_len=80)
            cur = conn.execute(
                """
                INSERT INTO fleet_unit (
                    asset_id,
                    display_name,
                    status,
                    source,
                    created_utc,
                    updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    final_asset_id,
                    display_name or "",
                    status,
                    source,
                    now_utc,
                    now_utc,
                ),
            )
            unit_id = _to_int(cur.lastrowid, default=0)
            if unit_id > 0 and not display_name:
                conn.execute(
                    "UPDATE fleet_unit SET display_name = ?, updated_utc = ? WHERE id = ?",
                    (f"Unit {unit_id}", now_utc, unit_id),
                )
            conn.commit()
            return unit_id

    def update_unit(self, unit_id: int, payload: dict[str, Any]) -> int:
        self._require_ready()
        selected_unit_id = _to_int(unit_id, default=0)
        if selected_unit_id <= 0:
            raise ValueError("Unit ID is required.")
        request = payload if isinstance(payload, dict) else {}

        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT id, display_name, status, source
                FROM fleet_unit
                WHERE id = ?
                LIMIT 1
                """,
                (selected_unit_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"Unit not found: {selected_unit_id}")

            display_name = _clean_text(request.get("display_name", current["display_name"]), max_len=300)
            if not display_name:
                display_name = f"Unit {selected_unit_id}"
            status = _clean_text(request.get("status", current["status"]), max_len=80) or "unknown"
            source = _clean_text(request.get("source", current["source"]), max_len=80) or "manual"
            now_utc = _utc_now()
            conn.execute(
                """
                UPDATE fleet_unit
                SET display_name = ?, status = ?, source = ?, updated_utc = ?
                WHERE id = ?
                """,
                (
                    display_name,
                    status,
                    source,
                    now_utc,
                    selected_unit_id,
                ),
            )
            conn.commit()
            return selected_unit_id

    def create_unit_identifier(self, payload: dict[str, Any]) -> int:
        self._require_ready()
        request = payload if isinstance(payload, dict) else {}
        unit_id = _to_int(request.get("unit_id"), default=0)
        if unit_id <= 0:
            raise ValueError("Unit ID is required.")
        identifier_type = _clean_text(request.get("identifier_type"), max_len=80).lower()
        identifier_raw = _clean_text(request.get("identifier_raw"), max_len=240)
        if not identifier_type:
            raise ValueError("Identifier type is required.")
        if not identifier_raw:
            raise ValueError("Identifier value is required.")
        identifier_norm = _normalize_identifier_value(identifier_raw)
        if not identifier_norm:
            raise ValueError("Identifier value is invalid.")
        is_primary = bool(request.get("is_primary"))
        source_system_id = _to_int(request.get("source_system_id"), default=0)
        now_utc = _utc_now()

        with self._connect() as conn:
            unit_row = conn.execute(
                "SELECT id FROM fleet_unit WHERE id = ? LIMIT 1",
                (unit_id,),
            ).fetchone()
            if unit_row is None:
                raise ValueError(f"Unit not found: {unit_id}")

            if source_system_id > 0:
                system_row = conn.execute(
                    "SELECT id FROM asset_system WHERE id = ? LIMIT 1",
                    (source_system_id,),
                ).fetchone()
                if system_row is None:
                    raise ValueError(f"System not found: {source_system_id}")

            existing = conn.execute(
                """
                SELECT id, unit_id, is_primary, source_system_id
                FROM fleet_unit_identifier
                WHERE identifier_type = ?
                  AND identifier_norm = ?
                LIMIT 1
                """,
                (identifier_type, identifier_norm),
            ).fetchone()

            if existing is not None and _to_int(existing["unit_id"], default=0) != unit_id:
                raise ValueError(
                    "Identifier already belongs to another unit "
                    f"({identifier_type}:{identifier_norm})."
                )

            if is_primary:
                conn.execute(
                    "UPDATE fleet_unit_identifier SET is_primary = 0, updated_utc = ? WHERE unit_id = ?",
                    (now_utc, unit_id),
                )

            if existing is not None:
                identifier_id = _to_int(existing["id"], default=0)
                conn.execute(
                    """
                    UPDATE fleet_unit_identifier
                    SET
                        identifier_type = ?,
                        identifier_raw = ?,
                        identifier_norm = ?,
                        is_primary = ?,
                        source_system_id = ?,
                        updated_utc = ?
                    WHERE id = ?
                    """,
                    (
                        identifier_type,
                        identifier_raw,
                        identifier_norm,
                        1 if is_primary else _to_int(existing["is_primary"], default=0),
                        source_system_id if source_system_id > 0 else _to_int(existing["source_system_id"], default=0) or None,
                        now_utc,
                        identifier_id,
                    ),
                )
            else:
                if not is_primary:
                    has_primary = conn.execute(
                        "SELECT 1 FROM fleet_unit_identifier WHERE unit_id = ? AND is_primary = 1 LIMIT 1",
                        (unit_id,),
                    ).fetchone()
                    if has_primary is None:
                        is_primary = True
                cur = conn.execute(
                    """
                    INSERT INTO fleet_unit_identifier (
                        unit_id,
                        identifier_type,
                        identifier_raw,
                        identifier_norm,
                        is_primary,
                        confidence,
                        source_system_id,
                        created_utc,
                        updated_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        unit_id,
                        identifier_type,
                        identifier_raw,
                        identifier_norm,
                        1 if is_primary else 0,
                        1.0,
                        source_system_id if source_system_id > 0 else None,
                        now_utc,
                        now_utc,
                    ),
                )
                identifier_id = _to_int(cur.lastrowid, default=0)

            if not is_primary:
                still_primary = conn.execute(
                    "SELECT 1 FROM fleet_unit_identifier WHERE unit_id = ? AND is_primary = 1 LIMIT 1",
                    (unit_id,),
                ).fetchone()
                if still_primary is None and identifier_id > 0:
                    conn.execute(
                        "UPDATE fleet_unit_identifier SET is_primary = 1, updated_utc = ? WHERE id = ?",
                        (now_utc, identifier_id),
                    )
            conn.commit()
            return identifier_id

    def update_unit_identifier(self, identifier_id: int, payload: dict[str, Any]) -> int:
        self._require_ready()
        selected_identifier_id = _to_int(identifier_id, default=0)
        if selected_identifier_id <= 0:
            raise ValueError("Identifier ID is required.")
        request = payload if isinstance(payload, dict) else {}

        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT
                    id,
                    unit_id,
                    identifier_type,
                    identifier_raw,
                    identifier_norm,
                    is_primary,
                    source_system_id
                FROM fleet_unit_identifier
                WHERE id = ?
                LIMIT 1
                """,
                (selected_identifier_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"Identifier not found: {selected_identifier_id}")

            unit_id = _to_int(current["unit_id"], default=0)
            identifier_type = _clean_text(
                request.get("identifier_type", current["identifier_type"]),
                max_len=80,
            ).lower()
            identifier_raw = _clean_text(
                request.get("identifier_raw", current["identifier_raw"]),
                max_len=240,
            )
            if not identifier_type:
                raise ValueError("Identifier type is required.")
            if not identifier_raw:
                raise ValueError("Identifier value is required.")
            identifier_norm = _normalize_identifier_value(identifier_raw)
            if not identifier_norm:
                raise ValueError("Identifier value is invalid.")
            if "is_primary" in request:
                is_primary = bool(request.get("is_primary"))
            else:
                is_primary = bool(_to_int(current["is_primary"], default=0))
            if "source_system_id" in request:
                source_system_id = _to_int(request.get("source_system_id"), default=0)
            else:
                source_system_id = _to_int(current["source_system_id"], default=0)
            if source_system_id > 0:
                system_row = conn.execute(
                    "SELECT id FROM asset_system WHERE id = ? LIMIT 1",
                    (source_system_id,),
                ).fetchone()
                if system_row is None:
                    raise ValueError(f"System not found: {source_system_id}")

            conflict = conn.execute(
                """
                SELECT id, unit_id
                FROM fleet_unit_identifier
                WHERE identifier_type = ?
                  AND identifier_norm = ?
                  AND id != ?
                LIMIT 1
                """,
                (identifier_type, identifier_norm, selected_identifier_id),
            ).fetchone()
            if conflict is not None:
                conflict_unit_id = _to_int(conflict["unit_id"], default=0)
                if conflict_unit_id != unit_id:
                    raise ValueError(
                        "Identifier already belongs to another unit "
                        f"({identifier_type}:{identifier_norm})."
                    )

            now_utc = _utc_now()
            if is_primary:
                conn.execute(
                    "UPDATE fleet_unit_identifier SET is_primary = 0, updated_utc = ? WHERE unit_id = ?",
                    (now_utc, unit_id),
                )

            conn.execute(
                """
                UPDATE fleet_unit_identifier
                SET
                    identifier_type = ?,
                    identifier_raw = ?,
                    identifier_norm = ?,
                    is_primary = ?,
                    source_system_id = ?,
                    updated_utc = ?
                WHERE id = ?
                """,
                (
                    identifier_type,
                    identifier_raw,
                    identifier_norm,
                    1 if is_primary else 0,
                    source_system_id if source_system_id > 0 else None,
                    now_utc,
                    selected_identifier_id,
                ),
            )
            if not is_primary:
                has_primary = conn.execute(
                    "SELECT 1 FROM fleet_unit_identifier WHERE unit_id = ? AND is_primary = 1 LIMIT 1",
                    (unit_id,),
                ).fetchone()
                if has_primary is None:
                    conn.execute(
                        "UPDATE fleet_unit_identifier SET is_primary = 1, updated_utc = ? WHERE id = ?",
                        (now_utc, selected_identifier_id),
                    )
            conn.commit()
            return selected_identifier_id

    def create_unit_system_fit(self, payload: dict[str, Any]) -> int:
        self._require_ready()
        request = payload if isinstance(payload, dict) else {}
        unit_id = _to_int(request.get("unit_id"), default=0)
        system_id = _to_int(request.get("system_id"), default=0)
        if unit_id <= 0:
            raise ValueError("Unit ID is required.")
        if system_id <= 0:
            raise ValueError("System ID is required.")
        fit_status = _clean_text(request.get("fit_status"), max_len=80) or "unknown"
        quantity = _to_optional_float(request.get("quantity"))
        source = _clean_text(request.get("source"), max_len=80) or "manual"
        now_utc = _utc_now()

        with self._connect() as conn:
            unit_row = conn.execute(
                "SELECT id, asset_id FROM fleet_unit WHERE id = ? LIMIT 1",
                (unit_id,),
            ).fetchone()
            if unit_row is None:
                raise ValueError(f"Unit not found: {unit_id}")
            system_row = conn.execute(
                "SELECT id, asset_id FROM asset_system WHERE id = ? LIMIT 1",
                (system_id,),
            ).fetchone()
            if system_row is None:
                raise ValueError(f"System not found: {system_id}")
            if _clean_text(unit_row["asset_id"], max_len=80).lower() != _clean_text(system_row["asset_id"], max_len=80).lower():
                raise ValueError("Unit and system must belong to the same asset.")

            existing = conn.execute(
                """
                SELECT id
                FROM fleet_unit_system_fit
                WHERE unit_id = ? AND system_id = ?
                LIMIT 1
                """,
                (unit_id, system_id),
            ).fetchone()
            if existing is not None:
                fit_id = _to_int(existing["id"], default=0)
                conn.execute(
                    """
                    UPDATE fleet_unit_system_fit
                    SET fit_status = ?, quantity = ?, source = ?, updated_utc = ?
                    WHERE id = ?
                    """,
                    (fit_status, quantity, source, now_utc, fit_id),
                )
                conn.commit()
                return fit_id

            cur = conn.execute(
                """
                INSERT INTO fleet_unit_system_fit (
                    unit_id,
                    system_id,
                    fit_status,
                    quantity,
                    effective_from,
                    effective_to,
                    source,
                    created_utc,
                    updated_utc
                ) VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                """,
                (
                    unit_id,
                    system_id,
                    fit_status,
                    quantity,
                    source,
                    now_utc,
                    now_utc,
                ),
            )
            conn.commit()
            return _to_int(cur.lastrowid, default=0)

    def update_unit_system_fit(self, fit_id: int, payload: dict[str, Any]) -> int:
        self._require_ready()
        selected_fit_id = _to_int(fit_id, default=0)
        if selected_fit_id <= 0:
            raise ValueError("Fit ID is required.")
        request = payload if isinstance(payload, dict) else {}

        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT id, unit_id, system_id, fit_status, quantity, source
                FROM fleet_unit_system_fit
                WHERE id = ?
                LIMIT 1
                """,
                (selected_fit_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"Unit-system fit not found: {selected_fit_id}")

            unit_id = _to_int(current["unit_id"], default=0)
            system_id = _to_int(request.get("system_id", current["system_id"]), default=0)
            if system_id <= 0:
                raise ValueError("System ID is required.")
            fit_status = _clean_text(request.get("fit_status", current["fit_status"]), max_len=80) or "unknown"
            if "quantity" in request:
                quantity = _to_optional_float(request.get("quantity"))
            else:
                quantity = _to_optional_float(current["quantity"])
            source = _clean_text(request.get("source", current["source"]), max_len=80) or "manual"

            unit_row = conn.execute(
                "SELECT id, asset_id FROM fleet_unit WHERE id = ? LIMIT 1",
                (unit_id,),
            ).fetchone()
            system_row = conn.execute(
                "SELECT id, asset_id FROM asset_system WHERE id = ? LIMIT 1",
                (system_id,),
            ).fetchone()
            if unit_row is None:
                raise ValueError(f"Unit not found: {unit_id}")
            if system_row is None:
                raise ValueError(f"System not found: {system_id}")
            if _clean_text(unit_row["asset_id"], max_len=80).lower() != _clean_text(system_row["asset_id"], max_len=80).lower():
                raise ValueError("Unit and system must belong to the same asset.")

            duplicate = conn.execute(
                """
                SELECT id
                FROM fleet_unit_system_fit
                WHERE unit_id = ? AND system_id = ? AND id != ?
                LIMIT 1
                """,
                (unit_id, system_id, selected_fit_id),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("Unit already has a fit entry for the selected system.")

            now_utc = _utc_now()
            conn.execute(
                """
                UPDATE fleet_unit_system_fit
                SET
                    system_id = ?,
                    fit_status = ?,
                    quantity = ?,
                    source = ?,
                    updated_utc = ?
                WHERE id = ?
                """,
                (
                    system_id,
                    fit_status,
                    quantity,
                    source,
                    now_utc,
                    selected_fit_id,
                ),
            )
            conn.commit()
            return selected_fit_id

    def delete_asset(self, asset_id: str) -> None:
        self._require_ready()
        selected_asset_id = _clean_text(asset_id, max_len=80).lower()
        if not selected_asset_id:
            raise ValueError("Asset ID is required.")
        with self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM asset WHERE lower(asset_id) = ?",
                (selected_asset_id,),
            ).rowcount
            if deleted <= 0:
                raise ValueError(f"Asset not found: {selected_asset_id}")
            conn.commit()

    def create_analyst_note(self, payload: dict[str, Any]) -> int:
        self._require_ready()
        request = payload if isinstance(payload, dict) else {}
        asset_id = _clean_text(request.get("asset_id"), max_len=80).lower()
        if not asset_id:
            raise ValueError("Asset ID is required for analyst notes.")
        analyst_name = _clean_text(request.get("analyst_name"), max_len=200)
        if not analyst_name:
            raise ValueError("Analyst name is required.")
        note_text = _clean_text(request.get("note_text"), max_len=4000)
        if not note_text:
            raise ValueError("Note text is required.")

        note_title = _clean_text(request.get("note_title"), max_len=500)
        note_type = _clean_text(request.get("note_type"), max_len=80) or "observation"
        priority = _clean_text(request.get("priority"), max_len=80) or "medium"
        confidence = _clean_text(request.get("confidence"), max_len=80)
        source_reliability = _clean_text(request.get("source_reliability"), max_len=80)
        information_credibility = _clean_text(request.get("information_credibility"), max_len=80)
        event_time_utc = _clean_text(request.get("event_time_utc"), max_len=80)
        reported_time_utc = _clean_text(request.get("reported_time_utc"), max_len=80)
        location_text = _clean_text(request.get("location_text"), max_len=240)
        tags_csv = _clean_text(request.get("tags_csv"), max_len=500)
        source_ref = _clean_text(request.get("source_ref"), max_len=500)
        is_ai_generated = 1 if bool(request.get("is_ai_generated")) else 0
        system_id = _to_int(request.get("system_id"), default=0)
        fleet_unit_id = _to_int(request.get("fleet_unit_id"), default=0)
        if system_id > 0 and fleet_unit_id > 0:
            raise ValueError("Note target is ambiguous. Select either a system or a fielded unit.")
        now_utc = _utc_now()

        with self._connect() as conn:
            asset_exists = conn.execute(
                "SELECT asset_id FROM asset WHERE lower(asset_id) = ? LIMIT 1",
                (asset_id,),
            ).fetchone()
            if asset_exists is None:
                raise ValueError(f"Asset not found: {asset_id}")
            final_asset_id = _clean_text(asset_exists["asset_id"], max_len=80)

            system_fk: int | None = None
            if system_id > 0:
                row = conn.execute(
                    """
                    SELECT id
                    FROM asset_system
                    WHERE id = ? AND asset_id = ?
                    LIMIT 1
                    """,
                    (system_id, final_asset_id),
                ).fetchone()
                if row is None:
                    raise ValueError(
                        f"System {system_id} is not associated with asset {final_asset_id}."
                    )
                system_fk = _to_int(row["id"], default=0)

            fleet_unit_fk: int | None = None
            if fleet_unit_id > 0:
                row = conn.execute(
                    """
                    SELECT id
                    FROM fleet_unit
                    WHERE id = ? AND asset_id = ?
                    LIMIT 1
                    """,
                    (fleet_unit_id, final_asset_id),
                ).fetchone()
                if row is None:
                    raise ValueError(
                        f"Fielded unit {fleet_unit_id} is not associated with asset {final_asset_id}."
                    )
                fleet_unit_fk = _to_int(row["id"], default=0)

            cur = conn.execute(
                """
                INSERT INTO analyst_note (
                    asset_id,
                    system_id,
                    fleet_unit_id,
                    analyst_name,
                    note_title,
                    note_text,
                    note_type,
                    priority,
                    confidence,
                    source_reliability,
                    information_credibility,
                    event_time_utc,
                    reported_time_utc,
                    location_text,
                    tags_csv,
                    source_ref,
                    is_ai_generated,
                    created_utc,
                    updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    final_asset_id,
                    system_fk,
                    fleet_unit_fk,
                    analyst_name,
                    note_title,
                    note_text,
                    note_type,
                    priority,
                    confidence,
                    source_reliability,
                    information_credibility,
                    event_time_utc,
                    reported_time_utc,
                    location_text,
                    tags_csv,
                    source_ref,
                    is_ai_generated,
                    now_utc,
                    now_utc,
                ),
            )
            conn.commit()
            return _to_int(cur.lastrowid, default=0)

    def update_analyst_note(self, note_id: int, payload: dict[str, Any]) -> int:
        self._require_ready()
        selected_note_id = _to_int(note_id, default=0)
        if selected_note_id <= 0:
            raise ValueError("Valid note ID is required.")
        request = payload if isinstance(payload, dict) else {}

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analyst_note WHERE id = ? LIMIT 1",
                (selected_note_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Analyst note not found: {selected_note_id}")

            asset_id = _clean_text(request.get("asset_id", row["asset_id"]), max_len=80).lower()
            if not asset_id:
                raise ValueError("Asset ID is required for analyst notes.")
            asset_exists = conn.execute(
                "SELECT asset_id FROM asset WHERE lower(asset_id) = ? LIMIT 1",
                (asset_id,),
            ).fetchone()
            if asset_exists is None:
                raise ValueError(f"Asset not found: {asset_id}")
            final_asset_id = _clean_text(asset_exists["asset_id"], max_len=80)

            system_id = request.get("system_id", row["system_id"])
            system_fk: int | None = None
            system_id_int = _to_int(system_id, default=0)
            fleet_unit_id = request.get("fleet_unit_id", row["fleet_unit_id"])
            fleet_unit_fk: int | None = None
            fleet_unit_id_int = _to_int(fleet_unit_id, default=0)
            if system_id_int > 0 and fleet_unit_id_int > 0:
                raise ValueError("Note target is ambiguous. Select either a system or a fielded unit.")

            if system_id_int > 0:
                sys_row = conn.execute(
                    """
                    SELECT id
                    FROM asset_system
                    WHERE id = ? AND asset_id = ?
                    LIMIT 1
                    """,
                    (system_id_int, final_asset_id),
                ).fetchone()
                if sys_row is None:
                    raise ValueError(
                        f"System {system_id_int} is not associated with asset {final_asset_id}."
                    )
                system_fk = _to_int(sys_row["id"], default=0)

            if fleet_unit_id_int > 0:
                unit_row = conn.execute(
                    """
                    SELECT id
                    FROM fleet_unit
                    WHERE id = ? AND asset_id = ?
                    LIMIT 1
                    """,
                    (fleet_unit_id_int, final_asset_id),
                ).fetchone()
                if unit_row is None:
                    raise ValueError(
                        f"Fielded unit {fleet_unit_id_int} is not associated with asset {final_asset_id}."
                    )
                fleet_unit_fk = _to_int(unit_row["id"], default=0)

            analyst_name = _clean_text(request.get("analyst_name", row["analyst_name"]), max_len=200)
            note_text = _clean_text(request.get("note_text", row["note_text"]), max_len=4000)
            if not analyst_name:
                raise ValueError("Analyst name is required.")
            if not note_text:
                raise ValueError("Note text is required.")

            note_title = _clean_text(request.get("note_title", row["note_title"]), max_len=500)
            note_type = _clean_text(request.get("note_type", row["note_type"]), max_len=80) or "observation"
            priority = _clean_text(request.get("priority", row["priority"]), max_len=80) or "medium"
            confidence = _clean_text(request.get("confidence", row["confidence"]), max_len=80)
            source_reliability = _clean_text(
                request.get("source_reliability", row["source_reliability"]),
                max_len=80,
            )
            information_credibility = _clean_text(
                request.get("information_credibility", row["information_credibility"]),
                max_len=80,
            )
            event_time_utc = _clean_text(request.get("event_time_utc", row["event_time_utc"]), max_len=80)
            reported_time_utc = _clean_text(
                request.get("reported_time_utc", row["reported_time_utc"]),
                max_len=80,
            )
            location_text = _clean_text(request.get("location_text", row["location_text"]), max_len=240)
            tags_csv = _clean_text(request.get("tags_csv", row["tags_csv"]), max_len=500)
            source_ref = _clean_text(request.get("source_ref", row["source_ref"]), max_len=500)
            is_ai_generated = (
                1
                if bool(request.get("is_ai_generated", bool(_to_int(row["is_ai_generated"], default=0))))
                else 0
            )

            conn.execute(
                """
                UPDATE analyst_note
                SET
                    asset_id = ?,
                    system_id = ?,
                    fleet_unit_id = ?,
                    analyst_name = ?,
                    note_title = ?,
                    note_text = ?,
                    note_type = ?,
                    priority = ?,
                    confidence = ?,
                    source_reliability = ?,
                    information_credibility = ?,
                    event_time_utc = ?,
                    reported_time_utc = ?,
                    location_text = ?,
                    tags_csv = ?,
                    source_ref = ?,
                    is_ai_generated = ?,
                    updated_utc = ?
                WHERE id = ?
                """,
                (
                    final_asset_id,
                    system_fk,
                    fleet_unit_fk,
                    analyst_name,
                    note_title,
                    note_text,
                    note_type,
                    priority,
                    confidence,
                    source_reliability,
                    information_credibility,
                    event_time_utc,
                    reported_time_utc,
                    location_text,
                    tags_csv,
                    source_ref,
                    is_ai_generated,
                    _utc_now(),
                    selected_note_id,
                ),
            )
            conn.commit()
        return selected_note_id

    def delete_analyst_note(self, note_id: int) -> None:
        self._require_ready()
        selected_note_id = _to_int(note_id, default=0)
        if selected_note_id <= 0:
            raise ValueError("Valid note ID is required.")
        with self._connect() as conn:
            deleted = conn.execute(
                "DELETE FROM analyst_note WHERE id = ?",
                (selected_note_id,),
            ).rowcount
            if deleted <= 0:
                raise ValueError(f"Analyst note not found: {selected_note_id}")
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _require_ready(self) -> None:
        state = self.validate()
        if not bool(state.get("ok")):
            raise RuntimeError(str(state.get("message") or "Asset Intel DB unavailable."))

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = ?
            LIMIT 1
            """,
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
        try:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        except Exception:
            return False
        for row in rows:
            if _clean_text(row[1], max_len=120).lower() == _clean_text(column_name, max_len=120).lower():
                return True
        return False

    def _ensure_app_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(APP_SCHEMA_SQL)
        if self._table_exists(conn, "analyst_note") and not self._column_exists(conn, "analyst_note", "fleet_unit_id"):
            conn.execute("ALTER TABLE analyst_note ADD COLUMN fleet_unit_id INTEGER")
        if self._table_exists(conn, "analyst_note") and self._column_exists(conn, "analyst_note", "fleet_unit_id"):
            conn.execute("CREATE INDEX IF NOT EXISTS idx_analyst_note_fleet_unit ON analyst_note(fleet_unit_id)")

    def _facet_rows(self, conn: sqlite3.Connection, column_name: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            f"""
            SELECT
                trim({column_name}) AS value,
                COUNT(*) AS count_value
            FROM asset_profile
            WHERE trim(coalesce({column_name}, '')) <> ''
            GROUP BY trim({column_name})
            ORDER BY count_value DESC, value ASC
            """
        ).fetchall()
        return [
            {
                "value": _clean_text(row["value"], max_len=240),
                "count": _to_int(row["count_value"], default=0),
            }
            for row in rows
            if _clean_text(row["value"], max_len=240)
        ]

    @staticmethod
    def _taxonomy_token_facet_rows(
        conn: sqlite3.Connection,
        token_order: int,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
                trim(coalesce(token_value, '')) AS value,
                COUNT(DISTINCT asset_id) AS count_value
            FROM asset_taxonomy
            WHERE kind = 'domain'
              AND token_order = ?
              AND trim(coalesce(token_value, '')) <> ''
            GROUP BY trim(coalesce(token_value, ''))
            ORDER BY count_value DESC, lower(value)
            """,
            (int(token_order),),
        ).fetchall()
        return [
            {
                "value": _clean_text(row["value"], max_len=240),
                "count": _to_int(row["count_value"], default=0),
            }
            for row in rows
            if _clean_text(row["value"], max_len=240)
        ]

    @staticmethod
    def _type_rows_by_sub_domain_2(
        conn: sqlite3.Connection,
    ) -> dict[str, list[dict[str, Any]]]:
        rows = conn.execute(
            """
            SELECT
                trim(coalesce(tx.token_value, '')) AS sub_domain_2,
                trim(coalesce(p.type, '')) AS type_value,
                COUNT(DISTINCT a.asset_id) AS count_value
            FROM asset a
            JOIN asset_profile p ON p.asset_id = a.asset_id
            JOIN asset_taxonomy tx
              ON tx.asset_id = a.asset_id
             AND tx.kind = 'domain'
             AND tx.token_order = 3
            WHERE trim(coalesce(tx.token_value, '')) <> ''
              AND trim(coalesce(p.type, '')) <> ''
            GROUP BY trim(coalesce(tx.token_value, '')), trim(coalesce(p.type, ''))
            ORDER BY lower(sub_domain_2), count_value DESC, lower(type_value)
            """
        ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            sub_domain_2 = _clean_text(row["sub_domain_2"], max_len=240)
            type_value = _clean_text(row["type_value"], max_len=240)
            if not sub_domain_2 or not type_value:
                continue
            grouped.setdefault(sub_domain_2, []).append(
                {
                    "value": type_value,
                    "count": _to_int(row["count_value"], default=0),
                }
            )
        return grouped

    def _sync_asset_profiles(self, conn: sqlite3.Connection) -> None:
        missing_rows = conn.execute(
            """
            SELECT a.asset_id
            FROM asset a
            LEFT JOIN asset_profile p ON p.asset_id = a.asset_id
            WHERE p.asset_id IS NULL
            """
        ).fetchall()
        for row in missing_rows:
            asset_id = _clean_text(row["asset_id"], max_len=80)
            if not asset_id:
                continue
            profile = self._derive_profile_from_raw(conn, asset_id)
            self._upsert_asset_profile(conn, asset_id, profile)

    def _derive_profile_from_raw(self, conn: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
        domain = self._first_taxonomy_value(conn, asset_id, "domain")
        proliferation = self._first_taxonomy_value(conn, asset_id, "proliferation")
        origin = self._first_taxonomy_value(conn, asset_id, "origin")
        if not domain:
            domain = self._first_attr_value(conn, asset_id, {"Domain"}, preferred_section="tiers")
        if not proliferation:
            proliferation = self._first_attr_value(
                conn,
                asset_id,
                {"Proliferation"},
                preferred_section="tiers",
            )
        if not origin:
            origin = self._first_attr_value(conn, asset_id, {"Origin"}, preferred_section="tiers")
        return {
            "domain": domain,
            "proliferation": proliferation,
            "origin": origin,
            "type": self._first_attr_value(conn, asset_id, {"Type"}, preferred_section="system"),
            "builder": self._first_attr_value(conn, asset_id, {"Builder"}, preferred_section="system"),
            "alt_designation": self._first_attr_value(
                conn,
                asset_id,
                {"Alternative Designation", "Alternative Name"},
                preferred_section="system",
            ),
            "crew": self._first_attr_value(conn, asset_id, {"Crew"}, preferred_section="system"),
        }

    def _upsert_asset_profile(self, conn: sqlite3.Connection, asset_id: str, payload: dict[str, Any]) -> None:
        selected_asset_id = _clean_text(asset_id, max_len=80)
        if not selected_asset_id:
            return
        request = payload if isinstance(payload, dict) else {}
        now_utc = _utc_now()
        current = conn.execute(
            "SELECT * FROM asset_profile WHERE asset_id = ? LIMIT 1",
            (selected_asset_id,),
        ).fetchone()
        domain_hierarchy = normalize_domain_hierarchy(
            request.get("domain") if "domain" in request else None,
            request.get("sub_domain_1") if "sub_domain_1" in request else None,
            request.get("sub_domain_2") if "sub_domain_2" in request else None,
            fallback_domain=current["domain"] if current is not None else "",
        )
        domain_value = _clean_text(domain_hierarchy.get("domain"), max_len=240)
        if current is None:
            conn.execute(
                """
                INSERT INTO asset_profile (
                    asset_id,
                    type,
                    origin,
                    proliferation,
                    domain,
                    builder,
                    alt_designation,
                    crew,
                    created_utc,
                    updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_asset_id,
                    _clean_text(request.get("type"), max_len=240),
                    _clean_text(request.get("origin"), max_len=240),
                    _clean_text(request.get("proliferation"), max_len=240),
                    domain_value,
                    _clean_text(request.get("builder"), max_len=240),
                    _clean_text(request.get("alt_designation"), max_len=240),
                    _clean_text(request.get("crew"), max_len=120),
                    now_utc,
                    now_utc,
                ),
            )
            return

        conn.execute(
            """
            UPDATE asset_profile
            SET
                type = ?,
                origin = ?,
                proliferation = ?,
                domain = ?,
                builder = ?,
                alt_designation = ?,
                crew = ?,
                updated_utc = ?
            WHERE asset_id = ?
            """,
            (
                _clean_text(request.get("type", current["type"]), max_len=240),
                _clean_text(request.get("origin", current["origin"]), max_len=240),
                _clean_text(request.get("proliferation", current["proliferation"]), max_len=240),
                domain_value,
                _clean_text(request.get("builder", current["builder"]), max_len=240),
                _clean_text(request.get("alt_designation", current["alt_designation"]), max_len=240),
                _clean_text(request.get("crew", current["crew"]), max_len=120),
                now_utc,
                selected_asset_id,
            ),
        )

    def _sync_asset_dimensions(self, conn: sqlite3.Connection) -> None:
        missing_rows = conn.execute(
            """
            SELECT a.asset_id
            FROM asset a
            LEFT JOIN asset_dimension d ON d.asset_id = a.asset_id
            WHERE d.asset_id IS NULL
               OR (d.length_raw IS NULL AND d.width_raw IS NULL AND d.draft_raw IS NULL AND d.tonnage_raw IS NULL)
            """
        ).fetchall()
        for row in missing_rows:
            asset_id = _clean_text(row["asset_id"], max_len=80)
            if not asset_id:
                continue
            derived = self._derive_dimensions_from_raw(conn, asset_id)
            self._upsert_asset_dimensions(conn, asset_id, derived)

    def _derive_dimensions_from_raw(self, conn: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
        rows = conn.execute(
            """
            SELECT
                av.raw_key,
                av.raw_value,
                lower(coalesce(si.canonical_section_name, '')) AS section_name
            FROM asset_attribute_value av
            LEFT JOIN section_instance si ON si.id = av.section_instance_id
            WHERE av.asset_id = ?
            ORDER BY CASE WHEN lower(coalesce(si.canonical_section_name, '')) = 'dimensions' THEN 0 ELSE 1 END, av.id
            """,
            (asset_id,),
        ).fetchall()

        length_raw = ""
        width_raw = ""
        draft_raw = ""
        tonnage_raw = ""

        for row in rows:
            key_low = _clean_text(row["raw_key"], max_len=180).lower()
            raw_value = _clean_text(row["raw_value"], max_len=240)
            if not raw_value:
                continue
            if not length_raw and self._is_length_key(key_low):
                length_raw = raw_value
                continue
            if not width_raw and self._is_width_key(key_low):
                width_raw = raw_value
                continue
            if not draft_raw and self._is_draft_key(key_low):
                draft_raw = raw_value
                continue
            if not tonnage_raw and self._is_tonnage_key(key_low):
                tonnage_raw = raw_value

        return {
            "length_raw": length_raw,
            "width_raw": width_raw,
            "draft_raw": draft_raw,
            "tonnage_raw": tonnage_raw,
            "length_m": _parse_dimension_meters(length_raw),
            "width_m": _parse_dimension_meters(width_raw),
            "draft_m": _parse_dimension_meters(draft_raw),
            "tonnage_mt": _parse_tonnage_metric_tons(tonnage_raw),
        }

    @staticmethod
    def _is_length_key(key_low: str) -> bool:
        if "length" not in key_low and key_low not in {"loa", "length overall"}:
            return False
        return not any(
            token in key_low
            for token in ("barrel", "cartridge", "projectile", "launcher", "rocket", "missile", "runway", "deck", "boom", "ramp")
        )

    @staticmethod
    def _is_width_key(key_low: str) -> bool:
        if "beam" in key_low:
            return True
        if "width" not in key_low:
            return False
        return not any(token in key_low for token in ("bandwidth", "horizontal beam"))

    @staticmethod
    def _is_draft_key(key_low: str) -> bool:
        return "draft" in key_low and "sonar" not in key_low

    @staticmethod
    def _is_tonnage_key(key_low: str) -> bool:
        return "displacement" in key_low or "tonnage" in key_low

    def _upsert_asset_dimensions(self, conn: sqlite3.Connection, asset_id: str, payload: dict[str, Any]) -> None:
        selected_asset_id = _clean_text(asset_id, max_len=80)
        if not selected_asset_id:
            return

        current = conn.execute(
            "SELECT * FROM asset_dimension WHERE asset_id = ? LIMIT 1",
            (selected_asset_id,),
        ).fetchone()
        now_utc = _utc_now()

        length_raw = _clean_text(payload.get("length_raw", current["length_raw"] if current else ""), max_len=120)
        width_raw = _clean_text(payload.get("width_raw", current["width_raw"] if current else ""), max_len=120)
        draft_raw = _clean_text(payload.get("draft_raw", current["draft_raw"] if current else ""), max_len=120)
        tonnage_raw = _clean_text(payload.get("tonnage_raw", current["tonnage_raw"] if current else ""), max_len=120)

        length_m = payload.get("length_m", current["length_m"] if current else None)
        width_m = payload.get("width_m", current["width_m"] if current else None)
        draft_m = payload.get("draft_m", current["draft_m"] if current else None)
        tonnage_mt = payload.get("tonnage_mt", current["tonnage_mt"] if current else None)

        length_m_num = _to_float(length_m)
        if length_m_num is None and length_raw:
            length_m_num = _parse_dimension_meters(length_raw)
        width_m_num = _to_float(width_m)
        if width_m_num is None and width_raw:
            width_m_num = _parse_dimension_meters(width_raw)
        draft_m_num = _to_float(draft_m)
        if draft_m_num is None and draft_raw:
            draft_m_num = _parse_dimension_meters(draft_raw)
        tonnage_mt_num = _to_float(tonnage_mt)
        if tonnage_mt_num is None and tonnage_raw:
            tonnage_mt_num = _parse_tonnage_metric_tons(tonnage_raw)

        if current is None:
            conn.execute(
                """
                INSERT INTO asset_dimension (
                    asset_id,
                    length_raw,
                    width_raw,
                    draft_raw,
                    tonnage_raw,
                    length_m,
                    width_m,
                    draft_m,
                    tonnage_mt,
                    updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_asset_id,
                    length_raw,
                    width_raw,
                    draft_raw,
                    tonnage_raw,
                    length_m_num,
                    width_m_num,
                    draft_m_num,
                    tonnage_mt_num,
                    now_utc,
                ),
            )
            return

        conn.execute(
            """
            UPDATE asset_dimension
            SET
                length_raw = ?,
                width_raw = ?,
                draft_raw = ?,
                tonnage_raw = ?,
                length_m = ?,
                width_m = ?,
                draft_m = ?,
                tonnage_mt = ?,
                updated_utc = ?
            WHERE asset_id = ?
            """,
            (
                length_raw,
                width_raw,
                draft_raw,
                tonnage_raw,
                length_m_num,
                width_m_num,
                draft_m_num,
                tonnage_mt_num,
                now_utc,
                selected_asset_id,
            ),
        )

    def _sync_asset_systems(self, conn: sqlite3.Connection) -> None:
        sections = conn.execute(
            """
            SELECT
                si.id AS section_id,
                si.asset_id,
                si.raw_section_name,
                si.canonical_section_name,
                si.page_start,
                si.page_end,
                (SELECT COUNT(*) FROM asset_attribute_value av WHERE av.section_instance_id = si.id) AS attr_count,
                (SELECT COUNT(*) FROM asset_text_block tb WHERE tb.section_instance_id = si.id) AS text_count
            FROM section_instance si
            LEFT JOIN asset_system s ON s.section_instance_id = si.id
            WHERE s.section_instance_id IS NULL
            ORDER BY si.asset_id, si.page_start, si.id
            """
        ).fetchall()

        now_utc = _utc_now()
        for section in sections:
            canonical_name = _clean_text(section["canonical_section_name"], max_len=240)
            raw_name = _clean_text(section["raw_section_name"], max_len=240)
            section_name = raw_name or canonical_name
            attr_count = _to_int(section["attr_count"], default=0)
            text_count = _to_int(section["text_count"], default=0)
            if not self._is_system_section(section_name, canonical_name, attr_count, text_count):
                continue

            attrs = conn.execute(
                """
                SELECT raw_key, raw_value, value_type, num_value, unit, bool_value
                FROM asset_attribute_value
                WHERE section_instance_id = ?
                ORDER BY id
                """,
                (_to_int(section["section_id"], default=0),),
            ).fetchall()

            description = self._compose_system_description(attrs)
            category = self._infer_system_category(section_name)
            display_order = max(
                _to_int(section["page_start"], default=0) * 1000 + _to_int(section["section_id"], default=0),
                _to_int(section["section_id"], default=0),
            )

            cur = conn.execute(
                """
                INSERT INTO asset_system (
                    asset_id,
                    section_instance_id,
                    system_name,
                    system_category,
                    description,
                    page_start,
                    page_end,
                    display_order,
                    source,
                    created_utc,
                    updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _clean_text(section["asset_id"], max_len=80),
                    _to_int(section["section_id"], default=0),
                    section_name,
                    category,
                    description,
                    _to_int(section["page_start"], default=0),
                    _to_int(section["page_end"], default=0),
                    display_order,
                    "parser",
                    now_utc,
                    now_utc,
                ),
            )
            system_id = _to_int(cur.lastrowid, default=0)
            if system_id <= 0:
                continue

            sort_order = 0
            for attr in attrs:
                key = _clean_text(attr["raw_key"], max_len=180)
                value = _clean_text(attr["raw_value"], max_len=1600)
                if not key and not value:
                    continue
                sort_order += 1
                conn.execute(
                    """
                    INSERT INTO asset_system_attribute (
                        system_id,
                        attr_key,
                        attr_value,
                        value_type,
                        num_value,
                        unit,
                        bool_value,
                        sort_order,
                        created_utc,
                        updated_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        system_id,
                        key or "Value",
                        value,
                        _clean_text(attr["value_type"], max_len=20),
                        attr["num_value"],
                        _clean_text(attr["unit"], max_len=60),
                        _to_int(attr["bool_value"], default=0) if attr["bool_value"] is not None else None,
                        sort_order,
                        now_utc,
                        now_utc,
                    ),
                )

    def _sync_fleet_units(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT
                s.asset_id,
                s.id AS system_id,
                s.system_name,
                sa.attr_key,
                sa.attr_value
            FROM asset_system_attribute sa
            JOIN asset_system s ON s.id = sa.system_id
            ORDER BY s.asset_id, s.id, sa.id
            """
        ).fetchall()
        if not rows:
            return

        now_utc = _utc_now()
        unit_by_system: dict[tuple[str, int], int] = {}

        for row in rows:
            asset_id = _clean_text(row["asset_id"], max_len=80)
            system_id = _to_int(row["system_id"], default=0)
            system_name = _clean_text(row["system_name"], max_len=300)
            attr_key = _clean_text(row["attr_key"], max_len=180)
            attr_value = _clean_text(row["attr_value"], max_len=240)
            if not asset_id or system_id <= 0 or not attr_key or not attr_value:
                continue

            identifier_type = _infer_identifier_type(attr_key)
            if not identifier_type:
                continue
            identifier_norm = _normalize_identifier_value(attr_value)
            if not identifier_norm:
                continue

            system_key = (asset_id, system_id)
            unit_id = unit_by_system.get(system_key, 0)

            existing_identifier = conn.execute(
                """
                SELECT
                    fui.id,
                    fui.unit_id,
                    fui.source_system_id,
                    fu.asset_id
                FROM fleet_unit_identifier fui
                JOIN fleet_unit fu ON fu.id = fui.unit_id
                WHERE fui.identifier_type = ?
                  AND fui.identifier_norm = ?
                LIMIT 1
                """,
                (identifier_type, identifier_norm),
            ).fetchone()

            if unit_id <= 0 and existing_identifier is not None:
                existing_asset_id = _clean_text(existing_identifier["asset_id"], max_len=80)
                if existing_asset_id != asset_id:
                    # Keep associations deterministic if two assets share an identifier.
                    continue
                unit_id = _to_int(existing_identifier["unit_id"], default=0)
                identifier_id = _to_int(existing_identifier["id"], default=0)
                source_system_id = _to_int(existing_identifier["source_system_id"], default=0)
                if identifier_id > 0 and source_system_id <= 0:
                    conn.execute(
                        "UPDATE fleet_unit_identifier SET source_system_id = ?, updated_utc = ? WHERE id = ?",
                        (system_id, now_utc, identifier_id),
                    )

            if unit_id <= 0:
                display_name = attr_value
                cur = conn.execute(
                    """
                    INSERT INTO fleet_unit (
                        asset_id,
                        display_name,
                        status,
                        source,
                        created_utc,
                        updated_utc
                    ) VALUES (?, ?, 'unknown', 'parser', ?, ?)
                    """,
                    (
                        asset_id,
                        display_name,
                        now_utc,
                        now_utc,
                    ),
                )
                unit_id = _to_int(cur.lastrowid, default=0)
                if unit_id <= 0:
                    continue

            unit_by_system[system_key] = unit_id

            identifier_for_unit = conn.execute(
                """
                SELECT id
                FROM fleet_unit_identifier
                WHERE unit_id = ?
                  AND identifier_type = ?
                  AND identifier_norm = ?
                LIMIT 1
                """,
                (unit_id, identifier_type, identifier_norm),
            ).fetchone()
            if identifier_for_unit is None:
                has_primary = conn.execute(
                    "SELECT 1 FROM fleet_unit_identifier WHERE unit_id = ? AND is_primary = 1 LIMIT 1",
                    (unit_id,),
                ).fetchone()
                is_primary = 1 if identifier_type == "pennant" or has_primary is None else 0
                conn.execute(
                    """
                    INSERT OR IGNORE INTO fleet_unit_identifier (
                        unit_id,
                        identifier_type,
                        identifier_raw,
                        identifier_norm,
                        is_primary,
                        confidence,
                        source_system_id,
                        created_utc,
                        updated_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        unit_id,
                        identifier_type,
                        attr_value,
                        identifier_norm,
                        is_primary,
                        1.0,
                        system_id,
                        now_utc,
                        now_utc,
                    ),
                )

            if system_name.lower() not in {"", "system"}:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO fleet_unit_system_fit (
                        unit_id,
                        system_id,
                        fit_status,
                        quantity,
                        effective_from,
                        effective_to,
                        source,
                        created_utc,
                        updated_utc
                    ) VALUES (?, ?, 'unknown', NULL, NULL, NULL, 'parser', ?, ?)
                    """,
                    (
                        unit_id,
                        system_id,
                        now_utc,
                        now_utc,
                    ),
                )

            conn.execute(
                """
                UPDATE fleet_unit
                SET
                    display_name = CASE
                        WHEN trim(coalesce(display_name, '')) = '' THEN ?
                        ELSE display_name
                    END,
                    updated_utc = ?
                WHERE id = ?
                """,
                (
                    attr_value,
                    now_utc,
                    unit_id,
                ),
            )

        conn.execute(
            """
            DELETE FROM fleet_unit
            WHERE lower(coalesce(source, '')) = 'parser'
              AND id NOT IN (
                SELECT DISTINCT unit_id
                FROM fleet_unit_identifier
                WHERE unit_id IS NOT NULL
            )
            """
        )

    @staticmethod
    def _is_system_section(section_name: str, canonical_name: str, attr_count: int, text_count: int) -> bool:
        canon_low = _clean_text(canonical_name, max_len=240).lower()
        name_low = _clean_text(section_name, max_len=240).lower()
        if canon_low in SYSTEM_SECTION_EXACT_EXCLUDE:
            return False
        if name_low in SYSTEM_SECTION_EXACT_EXCLUDE:
            return False
        if attr_count <= 0 and text_count <= 0:
            return False
        if any(token in name_low for token in SYSTEM_SECTION_KEYWORDS):
            return True
        if any(token in canon_low for token in SYSTEM_SECTION_KEYWORDS):
            return True
        if attr_count >= 3 and len(name_low) > 4:
            return True
        return False

    @staticmethod
    def _compose_system_description(attrs: list[sqlite3.Row]) -> str:
        preferred_keys = {"name", "type", "quantity", "role", "purpose"}
        parts: list[str] = []
        for row in attrs:
            key = _clean_text(row["raw_key"], max_len=180)
            value = _clean_text(row["raw_value"], max_len=400)
            if not key or not value:
                continue
            if key.lower() in preferred_keys:
                parts.append(f"{key}: {value}")
            if len(parts) >= 3:
                break
        if parts:
            return " | ".join(parts)
        if not attrs:
            return ""
        first = attrs[0]
        key = _clean_text(first["raw_key"], max_len=180)
        value = _clean_text(first["raw_value"], max_len=400)
        if key and value:
            return f"{key}: {value}"
        return value

    @staticmethod
    def _infer_system_category(section_name: str) -> str:
        value = _clean_text(section_name, max_len=240).lower()
        if "radar" in value:
            return "Radar"
        if "sonar" in value:
            return "Sonar"
        if "propulsion" in value or "engine" in value:
            return "Propulsion"
        if "gun" in value or "weapon" in value or "missile" in value or "torpedo" in value:
            return "Weapon"
        if "fire control" in value:
            return "Fire Control"
        if "communication" in value:
            return "Communications"
        if "protection" in value:
            return "Protection"
        if "aviation" in value or "aircraft" in value:
            return "Aviation"
        return "General"

    def _ensure_manual_batch(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            """
            SELECT id
            FROM import_batch
            WHERE source_path = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (MANUAL_BATCH_SOURCE,),
        ).fetchone()
        if row is not None:
            return _to_int(row["id"], default=0)

        cur = conn.execute(
            """
            INSERT INTO import_batch (
                source_path,
                file_size_bytes,
                file_sha256,
                page_count,
                unique_page_count,
                duplication_factor,
                exported_utc,
                created_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                MANUAL_BATCH_SOURCE,
                0,
                "0" * 64,
                0,
                0,
                1,
                None,
                _utc_now(),
            ),
        )
        return _to_int(cur.lastrowid, default=0)

    def _replace_taxonomy(self, conn: sqlite3.Connection, asset_id: str, payload: dict[str, Any]) -> None:
        selected_asset_id = _clean_text(asset_id, max_len=80)
        if not selected_asset_id:
            return
        request = payload if isinstance(payload, dict) else {}
        current_domain = self._first_taxonomy_value(conn, selected_asset_id, "domain")
        current_origin = self._first_taxonomy_value(conn, selected_asset_id, "origin")
        current_proliferation = self._first_taxonomy_value(conn, selected_asset_id, "proliferation")
        domain_hierarchy = normalize_domain_hierarchy(
            request.get("domain") if "domain" in request else None,
            request.get("sub_domain_1") if "sub_domain_1" in request else None,
            request.get("sub_domain_2") if "sub_domain_2" in request else None,
            fallback_domain=current_domain,
        )
        domain = _clean_text(domain_hierarchy.get("domain"), max_len=240)
        origin = _clean_text(
            request.get("origin") if "origin" in request else current_origin,
            max_len=240,
        )
        proliferation = _clean_text(
            request.get("proliferation") if "proliferation" in request else current_proliferation,
            max_len=240,
        )

        conn.execute(
            """
            DELETE FROM asset_taxonomy
            WHERE asset_id = ?
              AND kind IN ('domain', 'origin', 'proliferation')
            """,
            (selected_asset_id,),
        )

        if domain:
            conn.execute(
                """
                INSERT INTO asset_taxonomy (
                    asset_id,
                    kind,
                    raw_value,
                    token_order,
                    token_value
                ) VALUES (?, 'domain', ?, 0, ?)
                """,
                (selected_asset_id, domain, domain),
            )
            for idx, token in enumerate(domain_hierarchy.get("tokens") or [], start=1):
                conn.execute(
                    """
                    INSERT INTO asset_taxonomy (
                        asset_id,
                        kind,
                        raw_value,
                        token_order,
                        token_value
                    ) VALUES (?, 'domain', ?, ?, ?)
                    """,
                    (selected_asset_id, domain, idx, token),
                )

        if origin:
            conn.execute(
                """
                INSERT INTO asset_taxonomy (
                    asset_id,
                    kind,
                    raw_value,
                    token_order,
                    token_value
                ) VALUES (?, 'origin', ?, 0, ?)
                """,
                (selected_asset_id, origin, origin),
            )

        if proliferation:
            conn.execute(
                """
                INSERT INTO asset_taxonomy (
                    asset_id,
                    kind,
                    raw_value,
                    token_order,
                    token_value
                ) VALUES (?, 'proliferation', ?, 0, ?)
                """,
                (selected_asset_id, proliferation, proliferation),
            )

    def _first_attr_value(self, conn: sqlite3.Connection, asset_id: str, keys: set[str], preferred_section: str = "") -> str:
        key_tokens = [_clean_text(value, max_len=180).lower() for value in keys if _clean_text(value)]
        if not key_tokens:
            return ""
        placeholders = ",".join("?" for _ in key_tokens)
        params: list[Any] = [asset_id]
        params.extend(key_tokens)
        params.append(_clean_text(preferred_section, max_len=120).lower())

        row = conn.execute(
            f"""
            SELECT av.raw_value
            FROM asset_attribute_value av
            LEFT JOIN section_instance si ON si.id = av.section_instance_id
            WHERE av.asset_id = ?
              AND lower(av.raw_key) IN ({placeholders})
            ORDER BY
              CASE
                WHEN lower(coalesce(si.canonical_section_name, '')) = ? THEN 0
                ELSE 1
              END,
              av.id
            LIMIT 1
            """,
            params,
        ).fetchone()
        return _clean_text(row["raw_value"], max_len=240) if row is not None else ""

    @staticmethod
    def _first_taxonomy_value(conn: sqlite3.Connection, asset_id: str, kind: str) -> str:
        row = conn.execute(
            """
            SELECT raw_value
            FROM asset_taxonomy
            WHERE asset_id = ?
              AND kind = ?
              AND token_order = 0
            ORDER BY id
            LIMIT 1
            """,
            (asset_id, kind),
        ).fetchone()
        return _clean_text(row["raw_value"], max_len=240) if row is not None else ""

    @staticmethod
    def _rounded(value: Any, digits: int = 3) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value), digits)
        except Exception:
            return None
