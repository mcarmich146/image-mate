# -*- coding: utf-8 -*-
"""Shared contracts and constants for Mosaic collection workflow."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re

MOSAIC_SCHEMA_VERSION = 1
MOSAIC_PROJECT_META_FILENAME = "project_meta.json"
MOSAIC_TILES_SHAPEFILE_FILENAME = "tiles.shp"
MOSAIC_TRACKING_DB_FILENAME = "mosaic_tracking.sqlite3"

PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

QA_STATUS_NOT_ACCEPTED = "NotAccepted"
QA_STATUS_ACCEPTED = "Accepted"
QA_STATUSES = {QA_STATUS_NOT_ACCEPTED, QA_STATUS_ACCEPTED}

API_STATUS_NOT_SUBMITTED = "not_submitted"
API_STATUS_SUBMISSION_FAILED = "submission_failed"

ATTEMPT_STATUS_SUBMITTED = "submitted"
ATTEMPT_STATUS_FAILED = "failed"
ATTEMPT_STATUS_SKIPPED = "skipped"

MUTATION_SOURCE_CREATE = "create"
MUTATION_SOURCE_REFRESH = "refresh_status"
MUTATION_SOURCE_ACCEPT = "mark_accepted"
MUTATION_SOURCE_RETASK = "retask"

DEFAULT_TILE_API_STATUS = API_STATUS_NOT_SUBMITTED
DEFAULT_TILE_QA_STATUS = QA_STATUS_NOT_ACCEPTED

TASKING_DEFAULT_TARGET_TYPE = "point"
TASKING_DEFAULT_SKU = "TSKPOI-M"
TASKING_DEFAULT_DURATION_HOURS = 24

PRICE_USD_PER_KM2 = 8.0
GRID_SIZE_M = 3_000.0
GRID_EQUAL_AREA_EPSG = "EPSG:6933"


class MosaicValidationError(RuntimeError):
    """Input or state validation error for Mosaic workflow."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_operator_name() -> str:
    return str(os.getenv("USERNAME") or "").strip() or "operator"


def normalize_project_id(project_id: str | None) -> str:
    return str(project_id or "").strip()


def validate_project_id(project_id: str | None) -> tuple[bool, str]:
    value = normalize_project_id(project_id)
    if not value:
        return False, "Project ID is required."
    if value in {".", ".."}:
        return False, "Project ID cannot be '.' or '..'."
    if not PROJECT_ID_PATTERN.fullmatch(value):
        return False, "Project ID must match [A-Za-z0-9._-] and be <= 64 characters."
    return True, ""
