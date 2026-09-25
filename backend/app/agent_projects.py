"""Backend-independent project, site, and context services for Image-Mate.

This module deliberately does not import ``backend.app.main``.  It can be used
by Hermes, a local CLI, or a future worker while the FastAPI/UI process is
stopped.  The UI later reads the same MonitoringStore SQLite database.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .monitoring_store import MonitoringStore

try:  # pragma: no cover - exercised when project dependencies are installed
    from shapely.geometry import box, mapping
    from shapely.ops import unary_union
except Exception:  # pragma: no cover - stdlib fallback is tested
    box = None
    mapping = None
    unary_union = None


PROJECT_STATUSES = {"draft", "approved", "active", "paused", "archived"}


def _site_square(lon: float, lat: float, footprint_m: float) -> dict[str, Any]:
    half = max(1.0, float(footprint_m)) / 2.0
    dlat = half / 111_320.0
    dlon = half / (111_320.0 * max(0.15, math.cos(math.radians(lat))))
    ring = [
        [lon - dlon, lat - dlat],
        [lon + dlon, lat - dlat],
        [lon + dlon, lat + dlat],
        [lon - dlon, lat + dlat],
        [lon - dlon, lat - dlat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def _site_point(lon: float, lat: float) -> dict[str, Any]:
    return {"type": "Point", "coordinates": [lon, lat]}


def geometry_from_sites(sites: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive a project AOI from site-centered footprints without a provider call."""

    if not sites:
        raise ValueError("At least one site is required to derive project geometry")
    if box is not None and mapping is not None and unary_union is not None:
        polygons = []
        for site in sites:
            lon = float(site["longitude"])
            lat = float(site["latitude"])
            footprint = float(site.get("footprint_m") or 2000.0)
            half = max(1.0, footprint) / 2.0
            dlat = half / 111_320.0
            dlon = half / (111_320.0 * max(0.15, math.cos(math.radians(lat))))
            polygons.append(box(lon - dlon, lat - dlat, lon + dlon, lat + dlat))
        return mapping(unary_union(polygons))
    polygons = [
        _site_square(float(site["longitude"]), float(site["latitude"]), float(site.get("footprint_m") or 2000.0))["coordinates"]
        for site in sites
    ]
    return {"type": "MultiPolygon", "coordinates": polygons}


def normalize_sites(sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(sites, list) or not sites:
        raise ValueError("At least one site is required")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in sites:
        if not isinstance(raw, dict):
            raise ValueError("Each site must be an object")
        site_id = str(raw.get("site_id") or "").strip()
        name = str(raw.get("name") or site_id).strip()
        if not site_id or not name:
            raise ValueError("Every site requires site_id and name")
        if site_id in seen:
            raise ValueError(f"Duplicate site_id: {site_id}")
        seen.add(site_id)
        latitude = float(raw.get("latitude"))
        longitude = float(raw.get("longitude"))
        footprint_m = float(raw.get("footprint_m") or 2000.0)
        if not -90 <= latitude <= 90:
            raise ValueError(f"{site_id}: latitude must be between -90 and 90")
        if not -180 <= longitude <= 180:
            raise ValueError(f"{site_id}: longitude must be between -180 and 180")
        if footprint_m <= 0:
            raise ValueError(f"{site_id}: footprint_m must be positive")
        provenance = raw.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {
                key: raw[key]
                for key in ("original_coordinate", "site_overrides", "report_profile", "order_ids")
                if key in raw
            }
        normalized.append(
            {
                "site_id": site_id,
                "name": name,
                "latitude": latitude,
                "longitude": longitude,
                "footprint_m": footprint_m,
                "geometry": raw.get("geometry") or _site_point(longitude, latitude),
                "provenance": provenance,
                "active": bool(raw.get("active", True)),
            }
        )
    return normalized


class AgentProjectService:
    """Local project/site/context controller backed by MonitoringStore."""

    def __init__(self, store: MonitoringStore):
        self.store = store

    def create_project(
        self,
        project: dict[str, Any],
        sites: list[dict[str, Any]],
        *,
        context_text: str | None = None,
        context_sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(project, dict):
            raise ValueError("project must be an object")
        normalized_sites = normalize_sites(sites)
        name = str(project.get("name") or "").strip()
        if not name:
            raise ValueError("Project name is required")
        status = str(project.get("status") or "draft").strip().lower()
        if status not in PROJECT_STATUSES:
            raise ValueError(f"Invalid project status: {status}")
        if context_text is not None and not str(context_text).strip():
            raise ValueError("Context text cannot be empty")
        payload = dict(project)
        payload["name"] = name
        payload["status"] = status
        payload["lifecycle_status"] = status
        payload["enabled"] = bool(project.get("enabled", False)) if status != "draft" else False
        payload.setdefault("geometry", geometry_from_sites(normalized_sites))
        row = self.store.create_project(payload)
        self.store.replace_project_sites(row["project_id"], normalized_sites)
        if context_text is not None:
            self.store.upsert_project_context(row["project_id"], context_text, context_sources or [])
        return self.store.get_project(row["project_id"]) or row

    def sync_project(
        self,
        project_id: str,
        sites: list[dict[str, Any]],
        *,
        context_text: str | None = None,
        context_sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not self.store.get_project(project_id):
            raise KeyError(f"Unknown project: {project_id}")
        normalized_sites = normalize_sites(sites)
        self.store.replace_project_sites(project_id, normalized_sites)
        if context_text is not None:
            self.store.upsert_project_context(project_id, context_text, context_sources or [])
        return self.store.get_project(project_id) or {}

    def list_projects(self) -> list[dict[str, Any]]:
        return self.store.list_projects(enabled_only=False)

    def get_project(self, project_id: str, *, include_context: bool = False) -> dict[str, Any]:
        project = self.store.get_project(project_id)
        if not project:
            raise KeyError(f"Unknown project: {project_id}")
        if include_context:
            project["context_detail"] = self.store.get_project_context(project_id)
        return project

    def replace_sites(self, project_id: str, sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.store.get_project(project_id):
            raise KeyError(f"Unknown project: {project_id}")
        return self.store.replace_project_sites(project_id, normalize_sites(sites))

    def list_sites(self, project_id: str) -> list[dict[str, Any]]:
        if not self.store.get_project(project_id):
            raise KeyError(f"Unknown project: {project_id}")
        return self.store.list_project_sites(project_id)

    def import_context(
        self,
        project_id: str,
        text: str,
        sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not self.store.get_project(project_id):
            raise KeyError(f"Unknown project: {project_id}")
        return self.store.upsert_project_context(project_id, text, sources or [])

    def get_context(self, project_id: str, *, history: bool = False) -> dict[str, Any]:
        if not self.store.get_project(project_id):
            raise KeyError(f"Unknown project: {project_id}")
        current = self.store.get_project_context(project_id)
        result: dict[str, Any] = {"current": current}
        if history:
            result["history"] = self.store.list_project_context_history(project_id)
        return result


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))


def load_sites(path: str | Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, dict) and isinstance(payload.get("sites"), list):
        return payload["sites"]
    if isinstance(payload, list):
        return payload
    raise ValueError("Site file must be a JSON list or an object containing a sites list")
