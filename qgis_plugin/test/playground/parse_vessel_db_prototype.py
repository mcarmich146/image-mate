#!/usr/bin/env python3
"""
Prototype parser for Vessel DB PDF exports.

Reads a large export PDF, detects repeated concatenation blocks, parses the
unique block, and writes a normalized SQLite database with:
- assets
- sections
- key/value attributes
- taxonomy
- free-text blocks
- extracted source links
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import fitz


DEFAULT_PDF = r"G:\My Drive\Vessel DB\Vessel DB.pdf"
DEFAULT_DB = r"qgis_plugin\test\playground\asset_intel_prototype.sqlite"

ASSET_URL_RE = re.compile(r"WEG Location:\s*(https?://[^\s]+/WEG/Asset/([a-fA-F0-9]{32}))")
KEY_VALUE_RE = re.compile(r"^([^:]{1,110}):\s*(.+)$")
PAGE_NUMBER_RE = re.compile(r"^\d+$")
URL_RE = re.compile(r"https?://\S+")
NUMERIC_RE = re.compile(r"^\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*([A-Za-z%°/\-^0-9]+)?\s*$")

IMAGE_SOURCE_HEADERS = {"Image Sources", "Source Images"}
NULLISH_VALUES = {"ina", "n/a", "na", "none", "unknown"}
BOOL_MAP = {"yes": 1, "true": 1, "no": 0, "false": 0}
NUMBER_RE = re.compile(r"([-+]?\d[\d,]*(?:\.\d+)?)")
TONNAGE_RE = re.compile(
    r"([-+]?\d[\d,]*(?:\.\d+)?)\s*(long tons?|short tons?|metric tons?|tonnes?|tons?|t|kg)\b",
    re.IGNORECASE,
)

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


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    value = value.replace("\u00a0", " ")
    value = (
        value.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    value = re.sub(r"\s+", " ", value.strip())
    return value


def normalize_key_token(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", key.lower())


def infer_identifier_type(raw_key: str) -> str:
    token = normalize_key_token(raw_key)
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


def normalize_identifier_value(raw_value: str) -> str:
    text = clean_text(raw_value).upper()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def normalize_section_name(raw_name: str) -> str:
    name = clean_text(raw_name)
    if name in IMAGE_SOURCE_HEADERS:
        return "Image Sources"
    if not name:
        return "UNKNOWN"
    return name


def is_boilerplate_line(line: str) -> bool:
    if not line:
        return True
    if line == "For Training Use Only":
        return True
    if line.startswith("Exported (UTC) @"):
        return True
    if PAGE_NUMBER_RE.match(line):
        return True
    return False


def is_valid_key(key: str) -> bool:
    key = clean_text(key)
    if not key or len(key) > 95:
        return False
    if "http" in key.lower():
        return False
    if ";" in key:
        return False
    # Accept unicode letters too (for names such as "Persée").
    if not any(ch.isalpha() for ch in key):
        return False
    return True


def is_heading_no_colon(line: str) -> bool:
    if ":" in line:
        return False
    if len(line) > 52:
        return False
    if not re.match(r"^[A-Za-z0-9 /&\-\(\)#]+$", line):
        return False
    words = line.split()
    if not (1 <= len(words) <= 8):
        return False
    alpha_words = [w for w in words if any(c.isalpha() for c in w)]
    if not alpha_words:
        return False
    titleish = sum(1 for w in alpha_words if w[0].isupper())
    return titleish >= max(1, len(alpha_words) - 1)


def is_section_colon_line(line: str) -> bool:
    return line.endswith(":") and line.count(":") == 1 and len(line) <= 95


def classify_value(raw_value: str) -> Tuple[str, Optional[float], Optional[str], Optional[int]]:
    v = raw_value.strip()
    low = v.lower()
    if low in BOOL_MAP:
        return "bool", None, None, BOOL_MAP[low]
    if low in NULLISH_VALUES:
        return "nullish", None, None, None

    m = NUMERIC_RE.match(v)
    if m:
        number_raw = m.group(1).replace(",", "")
        unit = m.group(2)
        try:
            num = float(number_raw)
            return "number", num, unit, None
        except ValueError:
            pass
    return "text", None, None, None


def parse_dimension_meters(raw_value: str) -> Optional[float]:
    text = clean_text(raw_value).lower()
    if not text:
        return None
    m = re.search(
        r"([-+]?\d[\d,]*(?:\.\d+)?)\s*(m|meter|meters|metre|metres|ft|feet|foot|in|inch|inches|cm|mm|km)\b",
        text,
    )
    if m:
        num = None
        try:
            num = float(m.group(1).replace(",", ""))
        except ValueError:
            num = None
        if num is None:
            return None
        unit = m.group(2).lower()
        if unit in {"m", "meter", "meters", "metre", "metres"}:
            return num
        if unit == "km":
            return num * 1000.0
        if unit == "cm":
            return num * 0.01
        if unit == "mm":
            return num * 0.001
        if unit in {"ft", "feet", "foot"}:
            return num * 0.3048
        if unit in {"in", "inch", "inches"}:
            return num * 0.0254
    m2 = NUMBER_RE.search(text)
    if not m2:
        return None
    try:
        return float(m2.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_tonnage_metric_tons(raw_value: str) -> Optional[float]:
    text = clean_text(raw_value).lower()
    if not text:
        return None
    m = TONNAGE_RE.search(text)
    if m:
        try:
            num = float(m.group(1).replace(",", ""))
        except ValueError:
            return None
        unit = m.group(2).lower()
        if "long ton" in unit:
            return num * 1.0160469088
        if "short ton" in unit:
            return num * 0.90718474
        if unit == "kg":
            return num / 1000.0
        return num
    m2 = NUMBER_RE.search(text)
    if not m2:
        return None
    try:
        return float(m2.group(1).replace(",", ""))
    except ValueError:
        return None


def is_length_key(key_low: str) -> bool:
    if "length" not in key_low and key_low not in {"loa", "length overall"}:
        return False
    excluded = (
        "barrel",
        "cartridge",
        "projectile",
        "launcher",
        "rocket",
        "missile",
        "runway",
        "deck",
        "boom",
        "ramp",
    )
    return not any(token in key_low for token in excluded)


def is_width_key(key_low: str) -> bool:
    if "beam" in key_low:
        return True
    if "width" not in key_low:
        return False
    return not any(token in key_low for token in ("bandwidth", "horizontal beam"))


def is_draft_key(key_low: str) -> bool:
    return "draft" in key_low and "sonar" not in key_low


def is_tonnage_key(key_low: str) -> bool:
    return "displacement" in key_low or "tonnage" in key_low


def infer_system_category(section_name: str) -> str:
    value = clean_text(section_name).lower()
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


def is_system_section(section_name: str, canonical_name: str, attr_count: int, text_count: int) -> bool:
    canon_low = clean_text(canonical_name).lower()
    name_low = clean_text(section_name).lower()
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


def compose_system_description(attrs: List[Tuple[str, str]]) -> str:
    preferred_keys = {"name", "type", "quantity", "role", "purpose"}
    parts: List[str] = []
    for key, value in attrs:
        key_clean = clean_text(key)
        value_clean = clean_text(value)
        if not key_clean or not value_clean:
            continue
        if key_clean.lower() in preferred_keys:
            parts.append(f"{key_clean}: {value_clean}")
        if len(parts) >= 3:
            break
    if parts:
        return " | ".join(parts)
    if not attrs:
        return ""
    first_key, first_value = attrs[0]
    first_key = clean_text(first_key)
    first_value = clean_text(first_value)
    if first_key and first_value:
        return f"{first_key}: {first_value}"
    return first_value


def extract_urls(text: str) -> List[str]:
    urls = []
    for m in URL_RE.findall(text):
        url = m.rstrip(".,);")
        if url:
            urls.append(url)
    return urls


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def detect_duplication_factor(doc: fitz.Document) -> Tuple[int, int]:
    page_count = doc.page_count
    page_markers: List[str] = []

    for i in range(page_count):
        text = doc.load_page(i).get_text("text")
        text = text or ""
        m = ASSET_URL_RE.search(text)
        page_markers.append(m.group(2).lower() if m else "")

    # Try larger factors first.
    for factor in (6, 5, 4, 3, 2):
        if page_count % factor != 0:
            continue
        chunk_size = page_count // factor
        first = page_markers[:chunk_size]
        if not any(first):
            continue
        if all(
            page_markers[idx * chunk_size : (idx + 1) * chunk_size] == first
            for idx in range(1, factor)
        ):
            return factor, chunk_size

    return 1, page_count


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS import_batch (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    file_sha256 TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    unique_page_count INTEGER NOT NULL,
    duplication_factor INTEGER NOT NULL,
    exported_utc TEXT,
    created_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset (
    asset_id TEXT PRIMARY KEY,
    batch_id INTEGER NOT NULL,
    title TEXT,
    weg_url TEXT,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    FOREIGN KEY(batch_id) REFERENCES import_batch(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS asset_taxonomy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    token_order INTEGER,
    token_value TEXT,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS section_dictionary (
    canonical_name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS section_instance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    raw_section_name TEXT NOT NULL,
    canonical_section_name TEXT NOT NULL,
    occurrence_index INTEGER NOT NULL,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE,
    FOREIGN KEY(canonical_section_name) REFERENCES section_dictionary(canonical_name)
);

CREATE TABLE IF NOT EXISTS attribute_dictionary (
    token TEXT PRIMARY KEY,
    canonical_key TEXT NOT NULL,
    value_kind_hint TEXT,
    unit_hint TEXT
);

CREATE TABLE IF NOT EXISTS attribute_alias (
    alias_key TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    confidence REAL NOT NULL,
    FOREIGN KEY(token) REFERENCES attribute_dictionary(token)
);

CREATE TABLE IF NOT EXISTS asset_attribute_value (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    section_instance_id INTEGER,
    attribute_token TEXT NOT NULL,
    raw_key TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    num_value REAL,
    unit TEXT,
    bool_value INTEGER,
    page_no INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    occurrence_index INTEGER NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE,
    FOREIGN KEY(section_instance_id) REFERENCES section_instance(id) ON DELETE SET NULL,
    FOREIGN KEY(attribute_token) REFERENCES attribute_dictionary(token)
);

CREATE TABLE IF NOT EXISTS asset_text_block (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    section_instance_id INTEGER,
    block_type TEXT NOT NULL,
    text TEXT NOT NULL,
    page_no INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    block_order INTEGER NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE,
    FOREIGN KEY(section_instance_id) REFERENCES section_instance(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS asset_source_link (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    section_instance_id INTEGER,
    url TEXT NOT NULL,
    source_context TEXT,
    raw_line TEXT,
    page_no INTEGER NOT NULL,
    line_no INTEGER NOT NULL,
    order_in_line INTEGER NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES asset(asset_id) ON DELETE CASCADE,
    FOREIGN KEY(section_instance_id) REFERENCES section_instance(id) ON DELETE SET NULL
);

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

CREATE INDEX IF NOT EXISTS idx_asset_batch ON asset(batch_id);
CREATE INDEX IF NOT EXISTS idx_attr_asset ON asset_attribute_value(asset_id);
CREATE INDEX IF NOT EXISTS idx_attr_section ON asset_attribute_value(section_instance_id);
CREATE INDEX IF NOT EXISTS idx_text_asset ON asset_text_block(asset_id);
CREATE INDEX IF NOT EXISTS idx_links_asset ON asset_source_link(asset_id);
CREATE INDEX IF NOT EXISTS idx_taxonomy_asset ON asset_taxonomy(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_system_asset ON asset_system(asset_id);
CREATE INDEX IF NOT EXISTS idx_asset_system_attr_system ON asset_system_attribute(system_id);
CREATE INDEX IF NOT EXISTS idx_fleet_unit_asset ON fleet_unit(asset_id);
CREATE INDEX IF NOT EXISTS idx_fleet_unit_identifier_unit ON fleet_unit_identifier(unit_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fleet_unit_identifier_type_norm
    ON fleet_unit_identifier(identifier_type, identifier_norm);
CREATE INDEX IF NOT EXISTS idx_fleet_unit_fit_unit ON fleet_unit_system_fit(unit_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fleet_unit_fit_unit_system
    ON fleet_unit_system_fit(unit_id, system_id);
CREATE INDEX IF NOT EXISTS idx_analyst_note_asset ON analyst_note(asset_id);
CREATE INDEX IF NOT EXISTS idx_analyst_note_system ON analyst_note(system_id);
CREATE INDEX IF NOT EXISTS idx_analyst_note_fleet_unit ON analyst_note(fleet_unit_id);
CREATE INDEX IF NOT EXISTS idx_asset_profile_domain ON asset_profile(domain);
""" 


@dataclass
class SectionState:
    section_id: int
    canonical_name: str
    raw_name: str


class ParserContext:
    def __init__(self, conn: sqlite3.Connection, batch_id: int):
        self.conn = conn
        self.batch_id = batch_id
        self.current_asset: Optional[str] = None
        self.current_section: Optional[SectionState] = None
        self.asset_seen: set[str] = set()
        self.asset_end_page: Dict[str, int] = {}
        self.section_occurrence: Dict[Tuple[str, str], int] = defaultdict(int)
        self.section_bounds: Dict[int, List[int]] = {}
        self.attribute_alias_counts: Dict[str, Counter] = defaultdict(Counter)
        self.attribute_type_counts: Dict[str, Counter] = defaultdict(Counter)
        self.attribute_unit_counts: Dict[str, Counter] = defaultdict(Counter)
        self.attr_occurrence: Dict[Tuple[str, int, str], int] = defaultdict(int)
        self.text_block_order: Dict[str, int] = defaultdict(int)

    def ensure_asset(self, asset_id: str, title: str, page_no: int) -> None:
        if asset_id in self.asset_seen:
            self.asset_end_page[asset_id] = max(self.asset_end_page.get(asset_id, page_no), page_no)
            return

        self.asset_seen.add(asset_id)
        self.asset_end_page[asset_id] = page_no
        self.conn.execute(
            """
            INSERT INTO asset (asset_id, batch_id, title, weg_url, start_page, end_page)
            VALUES (?, ?, ?, NULL, ?, ?)
            """,
            (asset_id, self.batch_id, title, page_no, page_no),
        )

    def set_asset_end_page(self, asset_id: str, page_no: int) -> None:
        if asset_id in self.asset_seen:
            self.asset_end_page[asset_id] = max(self.asset_end_page[asset_id], page_no)

    def set_current_asset(self, asset_id: str) -> None:
        self.current_asset = asset_id
        self.current_section = None

    def open_section(self, raw_section_name: str, page_no: int) -> None:
        if not self.current_asset:
            return
        canonical = normalize_section_name(raw_section_name)
        key = (self.current_asset, canonical)
        self.section_occurrence[key] += 1
        occurrence_index = self.section_occurrence[key]

        self.conn.execute(
            "INSERT OR IGNORE INTO section_dictionary (canonical_name) VALUES (?)",
            (canonical,),
        )
        cur = self.conn.execute(
            """
            INSERT INTO section_instance (
                asset_id, raw_section_name, canonical_section_name, occurrence_index, page_start, page_end
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (self.current_asset, clean_text(raw_section_name), canonical, occurrence_index, page_no, page_no),
        )
        section_id = int(cur.lastrowid)
        self.section_bounds[section_id] = [page_no, page_no]
        self.current_section = SectionState(section_id=section_id, canonical_name=canonical, raw_name=raw_section_name)

    def ensure_root_section(self, page_no: int) -> None:
        if self.current_section is None:
            self.open_section("ROOT", page_no)

    def touch_current_section_page(self, page_no: int) -> None:
        if not self.current_section:
            return
        bounds = self.section_bounds[self.current_section.section_id]
        if page_no < bounds[0]:
            bounds[0] = page_no
        if page_no > bounds[1]:
            bounds[1] = page_no

    def upsert_attribute_alias(self, raw_key: str) -> str:
        token = normalize_key_token(raw_key)
        if not token:
            token = "unknown"

        self.conn.execute(
            """
            INSERT OR IGNORE INTO attribute_dictionary (token, canonical_key, value_kind_hint, unit_hint)
            VALUES (?, ?, NULL, NULL)
            """,
            (token, raw_key),
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO attribute_alias (alias_key, token, confidence)
            VALUES (?, ?, 1.0)
            """,
            (raw_key, token),
        )
        self.attribute_alias_counts[token][raw_key] += 1
        return token

    def insert_taxonomy(self, kind: str, raw_value: str) -> None:
        if not self.current_asset:
            return
        self.conn.execute(
            """
            INSERT INTO asset_taxonomy (asset_id, kind, raw_value, token_order, token_value)
            VALUES (?, ?, ?, ?, ?)
            """,
            (self.current_asset, kind, raw_value, 0, raw_value),
        )
        if kind == "domain":
            parts = [clean_text(p) for p in raw_value.split(",") if clean_text(p)]
            for idx, part in enumerate(parts, start=1):
                self.conn.execute(
                    """
                    INSERT INTO asset_taxonomy (asset_id, kind, raw_value, token_order, token_value)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (self.current_asset, kind, raw_value, idx, part),
                )

    def insert_source_links(
        self,
        line: str,
        page_no: int,
        line_no: int,
        source_context: Optional[str] = None,
    ) -> None:
        if not self.current_asset:
            return
        urls = extract_urls(line)
        if not urls:
            return
        section_id = self.current_section.section_id if self.current_section else None
        for order, url in enumerate(urls, start=1):
            self.conn.execute(
                """
                INSERT INTO asset_source_link (
                    asset_id, section_instance_id, url, source_context, raw_line, page_no, line_no, order_in_line
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (self.current_asset, section_id, url, source_context, line, page_no, line_no, order),
            )

    def insert_text_block(self, text: str, page_no: int, line_no: int) -> None:
        if not self.current_asset:
            return
        self.ensure_root_section(page_no)
        self.touch_current_section_page(page_no)
        self.text_block_order[self.current_asset] += 1
        section_name = self.current_section.canonical_name.lower() if self.current_section else "root"
        if section_name == "notes":
            block_type = "notes"
        elif "variant" in section_name:
            block_type = "variants"
        elif section_name == "image sources":
            block_type = "source_notes"
        else:
            block_type = "other"

        self.conn.execute(
            """
            INSERT INTO asset_text_block (
                asset_id, section_instance_id, block_type, text, page_no, line_no, block_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.current_asset,
                self.current_section.section_id if self.current_section else None,
                block_type,
                text,
                page_no,
                line_no,
                self.text_block_order[self.current_asset],
            ),
        )

    def insert_attribute(self, key: str, value: str, page_no: int, line_no: int) -> None:
        if not self.current_asset:
            return

        self.ensure_root_section(page_no)
        self.touch_current_section_page(page_no)
        token = self.upsert_attribute_alias(key)
        value_type, num_value, unit, bool_value = classify_value(value)
        self.attribute_type_counts[token][value_type] += 1
        if unit:
            self.attribute_unit_counts[token][unit] += 1

        occ_key = (self.current_asset, self.current_section.section_id, token)
        self.attr_occurrence[occ_key] += 1
        occurrence_index = self.attr_occurrence[occ_key]

        self.conn.execute(
            """
            INSERT INTO asset_attribute_value (
                asset_id, section_instance_id, attribute_token, raw_key, raw_value, value_type,
                num_value, unit, bool_value, page_no, line_no, occurrence_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.current_asset,
                self.current_section.section_id if self.current_section else None,
                token,
                key,
                value,
                value_type,
                num_value,
                unit,
                bool_value,
                page_no,
                line_no,
                occurrence_index,
            ),
        )

        if key == "WEG Location":
            self.conn.execute(
                "UPDATE asset SET weg_url = ? WHERE asset_id = ?",
                (value, self.current_asset),
            )
        elif key == "Domain":
            self.insert_taxonomy("domain", value)
        elif key == "Proliferation":
            self.insert_taxonomy("proliferation", value)
        elif key == "Origin":
            self.insert_taxonomy("origin", value)

        source_context = self.current_section.canonical_name if self.current_section else None
        self.insert_source_links(value, page_no, line_no, source_context=source_context)

    def finalize(self) -> None:
        for asset_id, end_page in self.asset_end_page.items():
            self.conn.execute(
                "UPDATE asset SET end_page = ? WHERE asset_id = ?",
                (end_page, asset_id),
            )

        for section_id, bounds in self.section_bounds.items():
            self.conn.execute(
                "UPDATE section_instance SET page_start = ?, page_end = ? WHERE id = ?",
                (bounds[0], bounds[1], section_id),
            )

        for token, alias_counts in self.attribute_alias_counts.items():
            total = sum(alias_counts.values())
            canonical, _ = alias_counts.most_common(1)[0]

            type_hint = None
            if token in self.attribute_type_counts:
                type_hint = self.attribute_type_counts[token].most_common(1)[0][0]

            unit_hint = None
            if token in self.attribute_unit_counts and self.attribute_unit_counts[token]:
                unit_hint = self.attribute_unit_counts[token].most_common(1)[0][0]

            self.conn.execute(
                """
                UPDATE attribute_dictionary
                SET canonical_key = ?, value_kind_hint = ?, unit_hint = ?
                WHERE token = ?
                """,
                (canonical, type_hint, unit_hint, token),
            )

            for alias_key, count in alias_counts.items():
                confidence = count / total if total else 1.0
                self.conn.execute(
                    "UPDATE attribute_alias SET confidence = ? WHERE alias_key = ?",
                    (confidence, alias_key),
                )


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


def first_taxonomy_value(conn: sqlite3.Connection, asset_id: str, kind: str) -> str:
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
    return clean_text(row[0]) if row and row[0] is not None else ""


def first_attr_value(
    conn: sqlite3.Connection,
    asset_id: str,
    keys: List[str],
    preferred_section: str = "",
) -> str:
    key_tokens = [clean_text(k).lower() for k in keys if clean_text(k)]
    if not key_tokens:
        return ""
    placeholders = ",".join("?" for _ in key_tokens)
    params: List[str] = [asset_id]
    params.extend(key_tokens)
    params.append(clean_text(preferred_section).lower())
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
    return clean_text(row[0]) if row and row[0] is not None else ""


def populate_asset_profile(conn: sqlite3.Connection) -> None:
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    asset_rows = conn.execute("SELECT asset_id FROM asset ORDER BY asset_id").fetchall()
    for asset_row in asset_rows:
        asset_id = clean_text(asset_row[0])
        domain = first_taxonomy_value(conn, asset_id, "domain") or first_attr_value(
            conn,
            asset_id,
            ["Domain"],
            preferred_section="tiers",
        )
        origin = first_taxonomy_value(conn, asset_id, "origin") or first_attr_value(
            conn,
            asset_id,
            ["Origin"],
            preferred_section="tiers",
        )
        proliferation = first_taxonomy_value(conn, asset_id, "proliferation") or first_attr_value(
            conn,
            asset_id,
            ["Proliferation"],
            preferred_section="tiers",
        )
        type_value = first_attr_value(conn, asset_id, ["Type"], preferred_section="system")
        builder = first_attr_value(conn, asset_id, ["Builder"], preferred_section="system")
        alt_designation = first_attr_value(
            conn,
            asset_id,
            ["Alternative Designation", "Alternative Name"],
            preferred_section="system",
        )
        crew = first_attr_value(conn, asset_id, ["Crew"], preferred_section="system")
        conn.execute(
            """
            INSERT INTO asset_profile (
                asset_id, type, origin, proliferation, domain, builder, alt_designation, crew, created_utc, updated_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
                type = excluded.type,
                origin = excluded.origin,
                proliferation = excluded.proliferation,
                domain = excluded.domain,
                builder = excluded.builder,
                alt_designation = excluded.alt_designation,
                crew = excluded.crew,
                updated_utc = excluded.updated_utc
            """,
            (
                asset_id,
                type_value,
                origin,
                proliferation,
                domain,
                builder,
                alt_designation,
                crew,
                now_utc,
                now_utc,
            ),
        )


def populate_asset_dimensions(conn: sqlite3.Connection) -> None:
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    asset_rows = conn.execute("SELECT asset_id FROM asset ORDER BY asset_id").fetchall()
    for asset_row in asset_rows:
        asset_id = clean_text(asset_row[0])
        attr_rows = conn.execute(
            """
            SELECT
                av.raw_key,
                av.raw_value,
                lower(coalesce(si.canonical_section_name, '')) AS section_name
            FROM asset_attribute_value av
            LEFT JOIN section_instance si ON si.id = av.section_instance_id
            WHERE av.asset_id = ?
            ORDER BY
              CASE WHEN lower(coalesce(si.canonical_section_name, '')) = 'dimensions' THEN 0 ELSE 1 END,
              av.id
            """,
            (asset_id,),
        ).fetchall()
        length_raw = ""
        width_raw = ""
        draft_raw = ""
        tonnage_raw = ""
        for raw_key, raw_value, _section_name in attr_rows:
            key_low = clean_text(raw_key).lower()
            value = clean_text(raw_value)
            if not value:
                continue
            if not length_raw and is_length_key(key_low):
                length_raw = value
                continue
            if not width_raw and is_width_key(key_low):
                width_raw = value
                continue
            if not draft_raw and is_draft_key(key_low):
                draft_raw = value
                continue
            if not tonnage_raw and is_tonnage_key(key_low):
                tonnage_raw = value

        conn.execute(
            """
            INSERT INTO asset_dimension (
                asset_id, length_raw, width_raw, draft_raw, tonnage_raw,
                length_m, width_m, draft_m, tonnage_mt, updated_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset_id) DO UPDATE SET
                length_raw = excluded.length_raw,
                width_raw = excluded.width_raw,
                draft_raw = excluded.draft_raw,
                tonnage_raw = excluded.tonnage_raw,
                length_m = excluded.length_m,
                width_m = excluded.width_m,
                draft_m = excluded.draft_m,
                tonnage_mt = excluded.tonnage_mt,
                updated_utc = excluded.updated_utc
            """,
            (
                asset_id,
                length_raw,
                width_raw,
                draft_raw,
                tonnage_raw,
                parse_dimension_meters(length_raw),
                parse_dimension_meters(width_raw),
                parse_dimension_meters(draft_raw),
                parse_tonnage_metric_tons(tonnage_raw),
                now_utc,
            ),
        )


def populate_asset_systems(conn: sqlite3.Connection) -> None:
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute("DELETE FROM asset_system_attribute")
    conn.execute("DELETE FROM asset_system")
    sections = conn.execute(
        """
        SELECT
            si.id AS section_id,
            si.asset_id,
            si.raw_section_name,
            si.canonical_section_name,
            si.page_start,
            si.page_end,
            (
                SELECT COUNT(*)
                FROM asset_attribute_value av
                WHERE av.section_instance_id = si.id
            ) AS attr_count,
            (
                SELECT COUNT(*)
                FROM asset_text_block tb
                WHERE tb.section_instance_id = si.id
            ) AS text_count
        FROM section_instance si
        ORDER BY si.asset_id, si.page_start, si.id
        """
    ).fetchall()
    for section in sections:
        section_id = int(section[0])
        asset_id = clean_text(section[1])
        raw_name = clean_text(section[2])
        canonical_name = clean_text(section[3])
        page_start = int(section[4] or 0)
        page_end = int(section[5] or 0)
        attr_count = int(section[6] or 0)
        text_count = int(section[7] or 0)
        section_name = raw_name or canonical_name
        if not is_system_section(section_name, canonical_name, attr_count, text_count):
            continue
        attrs = conn.execute(
            """
            SELECT raw_key, raw_value, value_type, num_value, unit, bool_value
            FROM asset_attribute_value
            WHERE section_instance_id = ?
            ORDER BY id
            """,
            (section_id,),
        ).fetchall()
        description = compose_system_description(
            [(clean_text(attr[0]), clean_text(attr[1])) for attr in attrs]
        )
        display_order = max(page_start * 1000 + section_id, section_id)
        cur = conn.execute(
            """
            INSERT INTO asset_system (
                asset_id, section_instance_id, system_name, system_category, description,
                page_start, page_end, display_order, source, created_utc, updated_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                section_id,
                section_name,
                infer_system_category(section_name),
                description,
                page_start,
                page_end,
                display_order,
                "parser",
                now_utc,
                now_utc,
            ),
        )
        system_id = int(cur.lastrowid)
        sort_order = 0
        for raw_key, raw_value, value_type, num_value, unit, bool_value in attrs:
            key = clean_text(raw_key)
            value = clean_text(raw_value)
            if not key and not value:
                continue
            sort_order += 1
            conn.execute(
                """
                INSERT INTO asset_system_attribute (
                    system_id, attr_key, attr_value, value_type, num_value, unit, bool_value,
                    sort_order, created_utc, updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    system_id,
                    key or "Value",
                    value,
                    clean_text(value_type),
                    num_value,
                    clean_text(unit),
                    bool_value,
                    sort_order,
                    now_utc,
                    now_utc,
                ),
                )


def populate_fleet_units(conn: sqlite3.Connection) -> None:
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute("DELETE FROM fleet_unit_system_fit")
    conn.execute("DELETE FROM fleet_unit_identifier")
    conn.execute("DELETE FROM fleet_unit")

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

    unit_by_identifier: Dict[Tuple[str, str, str], int] = {}
    unit_by_system: Dict[Tuple[str, int], int] = {}

    for row in rows:
        asset_id = clean_text(row[0])
        system_id = int(row[1] or 0)
        system_name = clean_text(row[2])
        attr_key = clean_text(row[3])
        attr_value = clean_text(row[4])
        if not asset_id or system_id <= 0 or not attr_key or not attr_value:
            continue

        identifier_type = infer_identifier_type(attr_key)
        if not identifier_type:
            continue
        identifier_norm = normalize_identifier_value(attr_value)
        if not identifier_norm:
            continue

        system_key = (asset_id, system_id)
        identifier_key = (asset_id, identifier_type, identifier_norm)
        unit_id = unit_by_system.get(system_key) or unit_by_identifier.get(identifier_key) or 0

        if unit_id <= 0:
            existing = conn.execute(
                """
                SELECT
                    fui.unit_id,
                    fu.asset_id
                FROM fleet_unit_identifier fui
                JOIN fleet_unit fu ON fu.id = fui.unit_id
                WHERE fui.identifier_type = ?
                  AND fui.identifier_norm = ?
                LIMIT 1
                """,
                (identifier_type, identifier_norm),
            ).fetchone()
            if existing is not None:
                existing_asset_id = clean_text(existing[1])
                if existing_asset_id != asset_id:
                    # Keep parse deterministic when an identifier collides across assets.
                    continue
                unit_id = int(existing[0] or 0)

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
            unit_id = int(cur.lastrowid or 0)
            if unit_id <= 0:
                continue

        unit_by_system[system_key] = unit_id
        unit_by_identifier[identifier_key] = unit_id

        existing_identifier = conn.execute(
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
        if existing_identifier is None:
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


def extract_title(lines: List[str]) -> str:
    for line in lines[:15]:
        if line.startswith("WEG Location:"):
            break
        if is_boilerplate_line(line):
            continue
        if line == "Tiers:":
            continue
        return line
    return ""


def is_new_section_line(line: str) -> bool:
    if line in IMAGE_SOURCE_HEADERS:
        return True
    if is_section_colon_line(line):
        return True
    if is_heading_no_colon(line):
        return True
    return False


def parse_pdf_to_db(pdf_path: str, db_path: str, max_pages: Optional[int] = None) -> Dict[str, int]:
    doc = fitz.open(pdf_path)
    factor, unique_pages_detected = detect_duplication_factor(doc)
    unique_pages = unique_pages_detected
    if max_pages is not None:
        unique_pages = min(unique_pages, max_pages)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)

    batch_id = conn.execute(
        """
        INSERT INTO import_batch (
            source_path, file_size_bytes, file_sha256, page_count, unique_page_count,
            duplication_factor, exported_utc, created_utc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pdf_path,
            os.path.getsize(pdf_path),
            file_sha256(pdf_path),
            doc.page_count,
            unique_pages,
            factor,
            None,
            datetime.now(timezone.utc).isoformat(),
        ),
    ).lastrowid

    ctx = ParserContext(conn, int(batch_id))

    exported_utc = None
    page_count = unique_pages
    for page_index in range(page_count):
        page_no = page_index + 1
        text = doc.load_page(page_index).get_text("text")
        if not text:
            continue
        raw_lines = [clean_text(x) for x in text.splitlines() if clean_text(x)]

        # Detect an asset switch for the page.
        page_asset_id = None
        page_weg_url = None
        marker_line_idx: Optional[int] = None
        for line in raw_lines[:30]:
            m = ASSET_URL_RE.search(line)
            if m:
                page_weg_url = m.group(1)
                page_asset_id = m.group(2).lower()
                marker_line_idx = raw_lines.index(line)
                break

        if page_asset_id:
            title = extract_title(raw_lines)
            ctx.ensure_asset(page_asset_id, title, page_no)
            ctx.set_current_asset(page_asset_id)
            ctx.open_section("ROOT", page_no)
            if page_weg_url:
                ctx.insert_attribute("WEG Location", page_weg_url, page_no, 0)
        elif ctx.current_asset:
            ctx.set_asset_end_page(ctx.current_asset, page_no)

        i = 0
        while i < len(raw_lines):
            line = raw_lines[i]
            line_no = i + 1

            # Ignore preamble lines before the WEG marker on each asset start page.
            if marker_line_idx is not None and i < marker_line_idx:
                i += 1
                continue

            if is_boilerplate_line(line):
                if line.startswith("Exported (UTC) @") and not exported_utc:
                    exported_utc = line.replace("Exported (UTC) @", "").strip()
                i += 1
                continue

            # Skip the WEG line because we already insert it once at asset detection.
            if line.startswith("WEG Location:"):
                i += 1
                continue

            if line in IMAGE_SOURCE_HEADERS:
                ctx.open_section("Image Sources", page_no)
                i += 1
                continue

            if is_section_colon_line(line):
                section_name = clean_text(line[:-1])
                if section_name not in {"WEG Location", "For Training Use Only"}:
                    ctx.open_section(section_name, page_no)
                    i += 1
                    continue

            if is_heading_no_colon(line):
                ctx.open_section(line, page_no)
                i += 1
                continue

            kv = KEY_VALUE_RE.match(line)
            if kv and is_valid_key(kv.group(1)):
                key = clean_text(kv.group(1))
                value = clean_text(kv.group(2))
                j = i + 1
                while j < len(raw_lines):
                    nxt = raw_lines[j]
                    if is_boilerplate_line(nxt):
                        break
                    if nxt.startswith("WEG Location:"):
                        break
                    if nxt in IMAGE_SOURCE_HEADERS:
                        break
                    if is_section_colon_line(nxt) or is_heading_no_colon(nxt):
                        break
                    next_kv = KEY_VALUE_RE.match(nxt)
                    if next_kv and is_valid_key(next_kv.group(1)):
                        break
                    value = f"{value} {nxt}".strip()
                    j += 1

                ctx.insert_attribute(key, value, page_no, line_no)
                i = j
                continue

            # Free text.
            if ctx.current_asset:
                ctx.insert_text_block(line, page_no, line_no)
                source_context = ctx.current_section.canonical_name if ctx.current_section else None
                ctx.insert_source_links(line, page_no, line_no, source_context=source_context)

            i += 1

        if ctx.current_asset:
            ctx.set_asset_end_page(ctx.current_asset, page_no)

    ctx.finalize()
    if exported_utc:
        conn.execute(
            "UPDATE import_batch SET exported_utc = ? WHERE id = ?",
            (exported_utc, batch_id),
        )

    populate_asset_profile(conn)
    populate_asset_dimensions(conn)
    populate_asset_systems(conn)
    populate_fleet_units(conn)

    conn.commit()

    result = {
        "batch_id": int(batch_id),
        "page_count": doc.page_count,
        "unique_page_count": unique_pages,
        "duplication_factor": factor,
        "asset_count": conn.execute("SELECT COUNT(*) FROM asset WHERE batch_id = ?", (batch_id,)).fetchone()[0],
        "section_count": conn.execute("SELECT COUNT(*) FROM section_instance").fetchone()[0],
        "attribute_count": conn.execute("SELECT COUNT(*) FROM asset_attribute_value").fetchone()[0],
        "text_block_count": conn.execute("SELECT COUNT(*) FROM asset_text_block").fetchone()[0],
        "source_link_count": conn.execute("SELECT COUNT(*) FROM asset_source_link").fetchone()[0],
        "dimension_count": conn.execute("SELECT COUNT(*) FROM asset_dimension").fetchone()[0],
        "system_count": conn.execute("SELECT COUNT(*) FROM asset_system").fetchone()[0],
        "system_attribute_count": conn.execute("SELECT COUNT(*) FROM asset_system_attribute").fetchone()[0],
        "fleet_unit_count": conn.execute("SELECT COUNT(*) FROM fleet_unit").fetchone()[0],
        "fleet_unit_identifier_count": conn.execute("SELECT COUNT(*) FROM fleet_unit_identifier").fetchone()[0],
        "fleet_unit_fit_count": conn.execute("SELECT COUNT(*) FROM fleet_unit_system_fit").fetchone()[0],
    }

    conn.close()
    doc.close()
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse Vessel DB PDF into a prototype SQLite database.")
    parser.add_argument("--pdf-path", default=DEFAULT_PDF, help="Path to Vessel DB PDF.")
    parser.add_argument("--db-path", default=DEFAULT_DB, help="Output SQLite database path.")
    parser.add_argument("--max-pages", type=int, default=None, help="Optional limit on unique pages to parse.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing DB file if it already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_path = os.path.abspath(args.pdf_path)
    db_path = os.path.abspath(args.db_path)

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        if not args.force:
            raise FileExistsError(
                f"Database already exists: {db_path}. Re-run with --force to overwrite."
            )
        os.remove(db_path)

    result = parse_pdf_to_db(pdf_path=pdf_path, db_path=db_path, max_pages=args.max_pages)
    print("Prototype parse complete")
    print(f"db_path={db_path}")
    for key in sorted(result):
        print(f"{key}={result[key]}")


if __name__ == "__main__":
    main()
