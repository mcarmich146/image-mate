from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import uuid
import zipfile
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape

from shapely.geometry import box, mapping, shape
from PIL import Image

from .geoagent import generate_geo_report

logger = logging.getLogger("image_mate")

UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def maybe_float(value: Any) -> float | None:
    try:
        v = float(value)
    except Exception:
        return None
    if math.isfinite(v):
        return v
    return None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(v)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def to_iso_date(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    def norm_lon(lon: Any) -> float:
        value = float(lon)
        return ((((value + 180.0) % 360.0) + 360.0) % 360.0) - 180.0

    def norm_lat(lat: Any) -> float:
        value = float(lat)
        return max(-90.0, min(90.0, value))

    def norm_coords(coords: Any) -> Any:
        if isinstance(coords, (list, tuple)):
            if len(coords) >= 2 and isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
                out = [norm_lon(coords[0]), norm_lat(coords[1])]
                if len(coords) > 2:
                    out.extend(coords[2:])
                return out
            return [norm_coords(c) for c in coords]
        return coords

    if not isinstance(geometry, dict):
        return geometry
    out = dict(geometry)
    out["coordinates"] = norm_coords(geometry.get("coordinates"))
    if isinstance(geometry.get("geometries"), list):
        out["geometries"] = [normalize_geometry(g) for g in geometry["geometries"] if isinstance(g, dict)]
    return out


def bounds_from_geometry(geometry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    try:
        geom = shape(geometry)
        minx, miny, maxx, maxy = geom.bounds
    except Exception:
        return None
    if maxx <= minx or maxy <= miny:
        return None
    return float(minx), float(miny), float(maxx), float(maxy)


def bbox_geometry(bounds: tuple[float, float, float, float]) -> dict[str, Any]:
    minx, miny, maxx, maxy = bounds
    return {
        "type": "Polygon",
        "coordinates": [[
            [minx, miny],
            [maxx, miny],
            [maxx, maxy],
            [minx, maxy],
            [minx, miny],
        ]],
    }


def _tile_xy_float(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Return fractional Web Mercator tile coordinates for a lat/lon at zoom."""
    n = 2 ** zoom
    x_float = (lon + 180.0) / 360.0 * n
    lat = max(-85.05112878, min(85.05112878, lat))
    lat_rad = math.radians(lat)
    y_float = (1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * n
    # Clamp to tile-space bounds so edge rounding stays inside [0, n].
    x_float = max(0.0, min(float(n), x_float))
    y_float = max(0.0, min(float(n), y_float))
    return x_float, y_float


def _tile_xy(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """
    Calculate tile coordinates for a given lat/lon at specified zoom level.
    Uses floor for tile calculation - to get all tiles overlapping a geometry,
    use floor(min_coord) through ceil(max_coord)-1.

    Args:
        lat: Latitude in degrees
        lon: Longitude in degrees
        zoom: Zoom level
    """
    n = 2 ** zoom
    x_float, y_float = _tile_xy_float(lat, lon, zoom)
    x = int(x_float)  # floor
    y = int(y_float)  # floor
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _quadkey(x: int, y: int, zoom: int) -> str:
    key = []
    for i in range(zoom, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if x & mask:
            digit += 1
        if y & mask:
            digit += 2
        key.append(str(digit))
    return "".join(key)


def geometry_quadkeys(geometry: dict[str, Any], zoom: int = 6) -> set[str]:
    bounds = bounds_from_geometry(geometry)
    if not bounds:
        return set()
    minx, miny, maxx, maxy = bounds
    # Use fractional tile coordinates so max bounds include edge tiles.
    # X increases eastward; Y increases southward in Web Mercator tile space.
    x_min_f, y_min_f = _tile_xy_float(maxy, minx, zoom)  # NW corner
    x_max_f, y_max_f = _tile_xy_float(miny, maxx, zoom)  # SE corner
    n = 2 ** zoom
    x0 = int(math.floor(min(x_min_f, x_max_f)))
    x1 = int(math.ceil(max(x_min_f, x_max_f)) - 1)
    y0 = int(math.floor(min(y_min_f, y_max_f)))
    y1 = int(math.ceil(max(y_min_f, y_max_f)) - 1)
    x0 = max(0, min(n - 1, x0))
    x1 = max(0, min(n - 1, x1))
    y0 = max(0, min(n - 1, y0))
    y1 = max(0, min(n - 1, y1))
    
    out: set[str] = set()
    for x in range(min(x0, x1), max(x0, x1) + 1):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            out.add(_quadkey(x, y, zoom))
    return out


def scene_from_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_id": item.get("id") or "",
        "captured_at": item.get("datetime"),
        "outcome_id": item.get("outcome_id"),
        "quality": {
            "cloud_cover": item.get("cloud_cover"),
            "gsd": item.get("gsd"),
            "valid_pixel_percent": item.get("valid_pixel_percent"),
        },
        "footprint": normalize_geometry(item.get("geometry") or {}),
        "assets": {
            "thumbnail": (item.get("assets") or {}).get("thumbnail") or "",
            "preview": (item.get("assets") or {}).get("preview") or "",
            "visual": (item.get("assets") or {}).get("visual") or "",
        },
    }


def report_json_schema_check(report_json: dict[str, Any]) -> tuple[bool, str]:
    required = ["profile", "summary", "findings", "confidence", "limitations", "appendix"]
    for field in required:
        if field not in report_json:
            return False, f"report.json missing field: {field}"
    if not isinstance(report_json.get("findings"), list):
        return False, "report.json findings must be a list"
    return True, "ok"


def lint_citations(report_md: str) -> tuple[bool, str, list[str]]:
    findings_started = False
    failures: list[str] = []
    evidence_token = re.compile(r"\[EVIDENCE\s+scene_id=.*captured_at=.*artifact=.*uri=.*\]")
    for raw_line in report_md.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.lower().startswith("## findings"):
            findings_started = True
            continue
        if line.startswith("## ") and findings_started:
            break
        if findings_started and line.startswith("-"):
            if not evidence_token.search(line):
                failures.append(raw_line)
    if failures:
        return False, "Findings contain claims without evidence tokens", failures
    if "[EVIDENCE " not in report_md:
        return False, "No evidence tokens found in report", []
    return True, "ok", []


@dataclass
class ProviderManifest:
    provider_id: str
    provider_version: str
    capabilities: list[str]
    output_schema: dict[str, Any]


class BaseProvider:
    manifest: ProviderManifest

    def run(self, scenes: list[dict[str, Any]], roi: dict[str, Any], analytic_types: list[str], params: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError


class MockThirdPartyProvider(BaseProvider):
    manifest = ProviderManifest(
        provider_id="thirdparty.mock",
        provider_version="1.0.0",
        capabilities=["aircraft", "infrastructure", "change", "deforestation", "landuse", "urban_change"],
        output_schema={"type": "FeatureCollection", "features": "provider_specific"},
    )

    def run(self, scenes: list[dict[str, Any]], roi: dict[str, Any], analytic_types: list[str], params: dict[str, Any]) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        roi_geom = shape(roi) if roi else None
        for scene in scenes:
            sid = scene.get("scene_id") or ""
            captured = scene.get("captured_at")
            footprint = scene.get("footprint") or {}
            bounds = bounds_from_geometry(footprint)
            if not bounds:
                continue
            minx, miny, maxx, maxy = bounds
            cx = (minx + maxx) / 2.0
            cy = (miny + maxy) / 2.0
            dx = max(1e-6, (maxx - minx) * 0.18)
            dy = max(1e-6, (maxy - miny) * 0.18)
            seed = int(hashlib.sha256(sid.encode("utf-8")).hexdigest()[:8], 16)

            for idx, analytic in enumerate(analytic_types):
                # Deterministic thinning to avoid over-claiming.
                if (seed + idx) % 3 != 0:
                    continue
                x0 = cx + (((seed % 7) - 3) * dx * 0.08)
                y0 = cy + ((((seed // 7) % 7) - 3) * dy * 0.08)
                geom = box(x0 - dx, y0 - dy, x0 + dx, y0 + dy)
                if roi_geom is not None:
                    geom = geom.intersection(roi_geom)
                if geom.is_empty:
                    continue
                confidence = 0.55 + (((seed + idx) % 35) / 100.0)
                outputs.append({
                    "type": "Feature",
                    "geometry": mapping(geom),
                    "properties": {
                        "scene_id": sid,
                        "captured_at": captured,
                        "label": (
                            "forest_loss"
                            if analytic in {"deforestation", "landuse"}
                            else ("urban_expansion" if analytic in {"urban_change", "urban"} else analytic)
                        ),
                        "analytic_type": analytic,
                        "confidence": round(min(0.95, confidence), 3),
                        "model": "mock-detector-v1",
                        "provider": self.manifest.provider_id,
                        "provider_version": self.manifest.provider_version,
                        "processed_at": utc_now_iso(),
                    },
                })
        return outputs


class ProviderScaffold(BaseProvider):
    manifest = ProviderManifest(
        provider_id="thirdparty.scaffold",
        provider_version="0.1.0",
        capabilities=["aircraft", "forest", "landuse", "change", "infrastructure"],
        output_schema={"type": "FeatureCollection", "features": "provider_specific"},
    )

    def run(self, scenes: list[dict[str, Any]], roi: dict[str, Any], analytic_types: list[str], params: dict[str, Any]) -> list[dict[str, Any]]:
        _ = (scenes, roi, analytic_types, params)
        return []


class GeoWorkbenchEngine:
    """In-process workflow/scheduling engine for GeoAgent workbench."""

    def __init__(
        self,
        root_dir: Path,
        search_items_fn: Callable[[dict[str, Any]], list[dict[str, Any]]],
        resolve_item_fn: Callable[[str, str | None], dict[str, Any] | None],
        download_bytes_fn: Callable[[str, str | None], bytes] | None = None,
        on_run_status: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.root_dir = root_dir
        self.search_items_fn = search_items_fn
        self.resolve_item_fn = resolve_item_fn
        self.download_bytes_fn = download_bytes_fn
        self.on_run_status = on_run_status

        self.workbench_dir = self.root_dir / "workbench"
        self.runs_dir = self.workbench_dir / "runs"
        self.state_file = self.workbench_dir / "state.json"

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self.workflows: dict[str, list[dict[str, Any]]] = {}
        self.skills: list[dict[str, Any]] = []
        self.schedules: dict[str, dict[str, Any]] = {}
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.poi_sets: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.idempotency_index: dict[str, str] = {}
        self.stage_cache: dict[str, dict[str, Any]] = {}

        self.providers: dict[str, BaseProvider] = {
            MockThirdPartyProvider.manifest.provider_id: MockThirdPartyProvider(),
            ProviderScaffold.manifest.provider_id: ProviderScaffold(),
        }

        self._init_storage()
        self._load_state()
        self._ensure_defaults()

    def _init_storage(self) -> None:
        self.workbench_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _state_payload(self) -> dict[str, Any]:
        return {
            "workflows": self.workflows,
            "skills": self.skills,
            "schedules": self.schedules,
            "subscriptions": self.subscriptions,
            "poi_sets": self.poi_sets,
            "runs": self.runs,
            "events": self.events[-500:],
            "idempotency_index": self.idempotency_index,
            "stage_cache": self.stage_cache,
            "saved_at": utc_now_iso(),
        }

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("workbench state load failed; starting fresh")
            return
        self.workflows = payload.get("workflows") or {}
        self.skills = payload.get("skills") or []
        self.schedules = payload.get("schedules") or {}
        self.subscriptions = payload.get("subscriptions") or {}
        self.poi_sets = payload.get("poi_sets") or {}
        self.runs = payload.get("runs") or {}
        self.events = [
            ev for ev in (payload.get("events") or [])
            if isinstance(ev, dict) and not str(ev.get("type") or "").startswith("case.")
        ]
        self.idempotency_index = payload.get("idempotency_index") or {}
        self.stage_cache = payload.get("stage_cache") or {}

    def _save_state(self) -> None:
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(canonical_json(self._state_payload()), encoding="utf-8")
        tmp.replace(self.state_file)

    def _ensure_defaults(self) -> None:
        default_skills = [
            {
                "skill_id": "evidence_bundle",
                "version": "1.0.0",
                "input_schema": {"type": "object", "required": ["inputs_payload"]},
                "output_schema": {"type": "object", "required": ["roi", "scene_set", "evidence_bundle"]},
                "runtime": "async",
                "ui_schema": {"title": "Evidence Bundle"},
            },
            {
                "skill_id": "analytics_provider",
                "version": "1.0.0",
                "input_schema": {"type": "object", "required": ["scene_set", "roi"]},
                "output_schema": {"type": "object", "required": ["detections", "provider"]},
                "runtime": "async",
                "ui_schema": {"title": "Analytics Provider"},
            },
            {
                "skill_id": "scene_metrics",
                "version": "1.0.0",
                "input_schema": {"type": "object", "required": ["detections"]},
                "output_schema": {"type": "object", "required": ["scene_metrics"]},
                "runtime": "sync",
                "ui_schema": {"title": "Scene Metrics"},
            },
            {
                "skill_id": "change_pol",
                "version": "1.0.0",
                "input_schema": {"type": "object", "required": ["scene_metrics"]},
                "output_schema": {"type": "object", "required": ["change_notes", "pattern_of_life"]},
                "runtime": "sync",
                "ui_schema": {"title": "Change + Pattern Of Life"},
            },
            {
                "skill_id": "ai_scene_change_agent",
                "version": "1.0.0",
                "input_schema": {"type": "object", "required": ["scene_set", "change_notes"]},
                "output_schema": {"type": "object", "required": ["ai_narrative"]},
                "runtime": "async",
                "ui_schema": {"title": "AI Scene/Change Agent"},
            },
            {
                "skill_id": "report_writer",
                "version": "1.0.0",
                "input_schema": {"type": "object", "required": ["evidence_bundle", "scene_metrics", "change_notes"]},
                "output_schema": {"type": "object", "required": ["report_md", "report_json"]},
                "runtime": "sync",
                "ui_schema": {"title": "Evidence Report Writer"},
            },
        ]
        if not self.skills:
            self.skills = default_skills
        else:
            merged: dict[str, dict[str, Any]] = {}
            for skill in self.skills:
                sid = (skill.get("skill_id") or "").strip()
                if sid:
                    merged[sid] = dict(skill)
            for skill in default_skills:
                sid = skill["skill_id"]
                merged[sid] = {**merged.get(sid, {}), **skill}
            ordered = [merged[s["skill_id"]] for s in default_skills]
            extras = [s for sid, s in merged.items() if sid not in {d["skill_id"] for d in default_skills}]
            self.skills = ordered + extras

        default_graph = {
            "nodes": [
                {"id": "evidence", "skill": "evidence_bundle"},
                {"id": "analytics", "skill": "analytics_provider", "depends_on": ["evidence"]},
                {"id": "metrics", "skill": "scene_metrics", "depends_on": ["analytics"]},
                {"id": "change", "skill": "change_pol", "depends_on": ["metrics"]},
                {"id": "ai", "skill": "ai_scene_change_agent", "depends_on": ["evidence", "change"]},
                {"id": "report", "skill": "report_writer", "depends_on": ["evidence", "metrics", "change", "ai"]},
            ]
        }
        default_workflows = [
            {
                "workflow_id": "airbase_time_series_analyst",
                "version": "1.0.0",
                "graph_json": default_graph,
                "default_params": {
                    "profile": "airbase",
                    "provider_id": "thirdparty.mock",
                    "analytic_types": ["aircraft", "infrastructure", "change"],
                    "max_scenes": 24,
                },
            },
            {
                "workflow_id": "land_use_deforestation_change",
                "version": "1.0.0",
                "graph_json": default_graph,
                "default_params": {
                    "profile": "landuse",
                    "provider_id": "thirdparty.mock",
                    "analytic_types": ["deforestation", "landuse", "change"],
                    "max_scenes": 60,
                },
            },
            {
                "workflow_id": "forest_urban_change_series",
                "version": "1.0.0",
                "graph_json": default_graph,
                "default_params": {
                    "profile": "forest_urban",
                    "provider_id": "thirdparty.mock",
                    "analytic_types": ["deforestation", "urban_change", "change"],
                    "max_scenes": 36,
                    "require_selected_scenes": True,
                },
            },
            {
                "workflow_id": "carousel_scene_change_report",
                "version": "1.0.0",
                "graph_json": default_graph,
                "default_params": {
                    "profile": "forest_urban",
                    "provider_id": "thirdparty.mock",
                    "analytic_types": ["deforestation", "urban_change", "change"],
                    "max_scenes": 24,
                    "require_selected_scenes": True,
                    "ai_prompt": "Describe the scene and summarize observed temporal changes over the selected viewport.",
                },
            },
        ]
        for wf in default_workflows:
            if not self.resolve_workflow(wf["workflow_id"], wf["version"]):
                self.create_or_update_workflow(wf)
        for versions in self.workflows.values():
            for wf in versions:
                defaults = wf.get("default_params")
                if not isinstance(defaults, dict):
                    continue
                defaults.pop("case_area_threshold", None)
                defaults.pop("case_confidence_threshold", None)
        self._save_state()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._scheduler_loop, daemon=True, name="workbench-scheduler")
            self._thread.start()
            logger.info("workbench scheduler started")

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.5)

    # ----- CRUD APIs -----
    def list_workflows(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with self._lock:
            for wid, versions in self.workflows.items():
                for item in sorted(versions, key=lambda x: x.get("version", ""), reverse=True):
                    out.append(item)
        return out

    def latest_workflow(self, workflow_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            if workflow_id:
                versions = self.workflows.get(workflow_id) or []
                if not versions:
                    return None
                return sorted(versions, key=lambda x: x.get("version", ""), reverse=True)[0]
            if not self.workflows:
                return None
            first_key = sorted(self.workflows.keys())[0]
            versions = self.workflows[first_key]
            return sorted(versions, key=lambda x: x.get("version", ""), reverse=True)[0]

    def resolve_workflow(self, workflow_id: str, version: str | None = None) -> dict[str, Any] | None:
        versions = self.workflows.get(workflow_id) or []
        if not versions:
            return None
        if version:
            for item in versions:
                if item.get("version") == version:
                    return item
            return None
        return sorted(versions, key=lambda x: x.get("version", ""), reverse=True)[0]

    def create_or_update_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_id = (payload.get("workflow_id") or "").strip()
        version = (payload.get("version") or "").strip()
        if not workflow_id or not version:
            raise ValueError("workflow_id and version are required")
        graph_nodes = self._normalize_graph_nodes(payload.get("graph_json") or {"nodes": []})
        self._validate_graph_connections(graph_nodes)
        item = {
            "workflow_id": workflow_id,
            "version": version,
            "graph_json": {"nodes": graph_nodes},
            "default_params": payload.get("default_params") or {},
            "created_at": utc_now_iso(),
        }
        with self._lock:
            versions = self.workflows.setdefault(workflow_id, [])
            versions = [v for v in versions if v.get("version") != version]
            versions.append(item)
            self.workflows[workflow_id] = versions
            self._save_state()
        return item

    def list_skills(self) -> list[dict[str, Any]]:
        return list(self.skills)

    def list_providers(self) -> list[dict[str, Any]]:
        out = []
        for provider in self.providers.values():
            out.append(
                {
                    "provider_id": provider.manifest.provider_id,
                    "provider_version": provider.manifest.provider_version,
                    "capabilities": provider.manifest.capabilities,
                    "output_schema": provider.manifest.output_schema,
                }
            )
        return out

    def _skill_by_id(self, skill_id: str) -> dict[str, Any] | None:
        for skill in self.skills:
            if (skill.get("skill_id") or "").strip() == skill_id:
                return skill
        return None

    def _skill_output_keys(self, skill_id: str, skill_def: dict[str, Any] | None = None) -> set[str]:
        builtin = {
            "evidence_bundle": {"roi", "scene_set", "evidence_bundle"},
            "analytics_provider": {"detections", "provider"},
            "scene_metrics": {"scene_metrics"},
            "change_pol": {"change_notes", "pattern_of_life"},
            "ai_scene_change_agent": {"ai_narrative"},
            "report_writer": {"report_md", "report_json"},
        }
        if skill_id in builtin:
            return set(builtin[skill_id])
        skill = skill_def or self._skill_by_id(skill_id) or {}
        output_schema = skill.get("output_schema") if isinstance(skill, dict) else {}
        required = output_schema.get("required") if isinstance(output_schema, dict) else []
        if isinstance(required, list):
            return {str(x).strip() for x in required if str(x).strip()}
        return set()

    def _normalize_graph_nodes(self, graph_json: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(graph_json, dict):
            raise ValueError("graph_json must be an object")
        raw_nodes = graph_json.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValueError("graph_json.nodes must be a non-empty array")

        known_skills = {(s.get("skill_id") or "").strip() for s in self.skills if (s.get("skill_id") or "").strip()}
        out: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for idx, raw in enumerate(raw_nodes):
            if not isinstance(raw, dict):
                raise ValueError(f"graph_json.nodes[{idx}] must be an object")
            node_id = str(raw.get("id") or "").strip()
            skill_id = str(raw.get("skill") or "").strip()
            if not node_id:
                raise ValueError(f"graph_json.nodes[{idx}] missing id")
            if node_id in seen_ids:
                raise ValueError(f"graph_json has duplicate node id: {node_id}")
            seen_ids.add(node_id)
            if not skill_id:
                raise ValueError(f"graph_json.nodes[{idx}] missing skill")
            if skill_id not in known_skills:
                raise ValueError(f"graph_json node {node_id} uses unknown skill: {skill_id}")

            deps_raw = raw.get("depends_on") or []
            if deps_raw and not isinstance(deps_raw, list):
                raise ValueError(f"graph_json node {node_id} depends_on must be an array")
            deps: list[str] = []
            seen_deps: set[str] = set()
            for dep in deps_raw:
                dep_id = str(dep).strip()
                if not dep_id or dep_id in seen_deps:
                    continue
                if dep_id == node_id:
                    raise ValueError(f"graph_json node {node_id} cannot depend on itself")
                deps.append(dep_id)
                seen_deps.add(dep_id)

            position = raw.get("position") if isinstance(raw.get("position"), dict) else {}
            x_raw = position.get("x", raw.get("x", idx * 210))
            y_raw = position.get("y", raw.get("y", 16))
            x = maybe_float(x_raw)
            y = maybe_float(y_raw)
            out.append(
                {
                    "id": node_id,
                    "skill": skill_id,
                    "depends_on": deps,
                    "position": {
                        "x": float(x if x is not None else (idx * 210)),
                        "y": float(y if y is not None else 16),
                    },
                }
            )

        node_ids = {n["id"] for n in out}
        for node in out:
            for dep in node["depends_on"]:
                if dep not in node_ids:
                    raise ValueError(f"graph_json node {node['id']} depends on unknown node: {dep}")
        if not any(n["skill"] == "evidence_bundle" for n in out):
            raise ValueError("graph_json must include at least one evidence_bundle node")
        if not any(n["skill"] == "report_writer" for n in out):
            raise ValueError("graph_json must include at least one report_writer node")
        return out

    def _topological_nodes(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {n["id"]: n for n in nodes}
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in by_id}
        in_degree: dict[str, int] = {node_id: 0 for node_id in by_id}
        for node in nodes:
            node_id = node["id"]
            for dep in node.get("depends_on") or []:
                adjacency.setdefault(dep, []).append(node_id)
                in_degree[node_id] += 1

        queue = sorted([node_id for node_id, degree in in_degree.items() if degree == 0])
        order: list[dict[str, Any]] = []
        while queue:
            node_id = queue.pop(0)
            order.append(by_id[node_id])
            for nxt in sorted(adjacency.get(node_id, [])):
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)
                    queue.sort()

        if len(order) != len(nodes):
            raise ValueError("graph_json contains a dependency cycle")
        return order

    def _validate_graph_connections(self, nodes: list[dict[str, Any]]) -> None:
        order = self._topological_nodes(nodes)
        external_inputs = {"inputs_payload", "roi", "viewport_geometry", "scene_ids", "params"}
        outputs_by_node: dict[str, set[str]] = {}

        for node in order:
            skill_id = node["skill"]
            skill_def = self._skill_by_id(skill_id)
            deps = node.get("depends_on") or []
            available_inputs = set(external_inputs)
            for dep in deps:
                available_inputs |= outputs_by_node.get(dep, set())
            required_inputs: set[str] = set()
            input_schema = skill_def.get("input_schema") if isinstance(skill_def, dict) else {}
            required_raw = input_schema.get("required") if isinstance(input_schema, dict) else []
            if isinstance(required_raw, list):
                required_inputs = {str(x).strip() for x in required_raw if str(x).strip()}
            missing = sorted([k for k in required_inputs if k not in available_inputs])
            if missing:
                raise ValueError(f"graph_json node {node['id']} missing required inputs: {', '.join(missing)}")
            outputs_by_node[node["id"]] = self._skill_output_keys(skill_id, skill_def)

    def create_poi_set(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = (payload.get("name") or "poi_set").strip()
        geometry = payload.get("geometry")
        features = payload.get("features")
        if not geometry and not features:
            raise ValueError("geometry or features is required")
        poi_set_id = f"poi.{uuid.uuid4()}"
        entry = {
            "poi_set_id": poi_set_id,
            "name": name,
            "geometry": normalize_geometry(geometry) if isinstance(geometry, dict) else None,
            "features": features if isinstance(features, list) else [],
            "created_at": utc_now_iso(),
        }
        with self._lock:
            self.poi_sets[poi_set_id] = entry
            self._save_state()
        return entry

    def list_poi_sets(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self.poi_sets.values(), key=lambda x: x.get("created_at", ""), reverse=True)

    def create_subscription(self, payload: dict[str, Any]) -> dict[str, Any]:
        sub_id = f"sub.{uuid.uuid4()}"
        geometry = payload.get("geometry")
        poi_set_id = payload.get("poi_set_id")
        if not geometry and not poi_set_id:
            raise ValueError("geometry or poi_set_id is required")
        entry = {
            "subscription_id": sub_id,
            "geometry": normalize_geometry(geometry) if isinstance(geometry, dict) else None,
            "poi_set_id": poi_set_id,
            "matching_rules": payload.get("matching_rules") or {},
            "filters": payload.get("filters") or {},
            "enabled": bool(payload.get("enabled", True)),
            "created_at": utc_now_iso(),
        }
        entry["tile_keys"] = sorted(list(geometry_quadkeys(entry["geometry"], zoom=6))) if entry.get("geometry") else []
        with self._lock:
            self.subscriptions[sub_id] = entry
            self._save_state()
        return entry

    def list_subscriptions(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self.subscriptions.values(), key=lambda x: x.get("created_at", ""), reverse=True)

    def create_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        schedule_id = f"trg.{uuid.uuid4()}"
        trigger_type = (payload.get("type") or "MANUAL").upper()
        workflow_id = payload.get("workflow_id")
        workflow_version = payload.get("workflow_version")
        if not workflow_id:
            default_workflow = self.latest_workflow()
            if not default_workflow:
                raise ValueError("No workflow available")
            workflow_id = default_workflow["workflow_id"]
            workflow_version = default_workflow["version"]

        resolved = self.resolve_workflow(workflow_id, workflow_version)
        if not resolved:
            raise ValueError("workflow_id/version not found")

        now = utc_now_iso()
        entry = {
            "trigger_id": schedule_id,
            "type": trigger_type,
            "workflow_id": resolved["workflow_id"],
            "workflow_version": resolved["version"],
            "scope": payload.get("scope") or {},
            "filters": payload.get("filters") or {},
            "batching": payload.get("batching") or {
                "policy": "per_day_per_region",
                "max_scenes_per_run": 24,
                "coalesce_minutes": 30,
            },
            "caps": payload.get("caps") or {"max_runs_per_day": 12},
            "subscription_id": payload.get("subscription_id"),
            "cron": payload.get("cron"),
            "interval_seconds": int(payload.get("interval_seconds") or 0),
            "enabled": bool(payload.get("enabled", True)),
            "last_checked_at": None,
            "last_fired_at": None,
            "seen_scene_ids": [],
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self.schedules[schedule_id] = entry
            self._save_state()
        return entry

    def patch_schedule(self, schedule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            entry = self.schedules.get(schedule_id)
            if not entry:
                raise KeyError("Schedule not found")
            for key in ("enabled", "cron", "interval_seconds", "batching", "caps", "filters", "scope", "subscription_id"):
                if key in payload:
                    entry[key] = payload[key]
            entry["updated_at"] = utc_now_iso()
            self._save_state()
            return entry

    def list_schedules(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self.schedules.values(), key=lambda x: x.get("created_at", ""), reverse=True)

    def list_runs(self, limit: int = 100, status: str | None = None, workflow_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = sorted(self.runs.values(), key=lambda x: x.get("created_at", ""), reverse=True)
            if status:
                rows = [r for r in rows if (r.get("status") or "").lower() == status.lower()]
            if workflow_id:
                rows = [r for r in rows if r.get("workflow_id") == workflow_id]
            return rows[: max(1, min(limit, 500))]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self.runs.get(run_id)

    def run_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            run = self.runs.get(run_id)
            if not run:
                return []
            return run.get("artifacts", [])

    # ----- Run execution -----
    def create_run(
        self,
        workflow_id: str | None,
        workflow_version: str | None,
        inputs_payload: dict[str, Any],
        trigger_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        workflow = self.resolve_workflow(workflow_id, workflow_version) if workflow_id else self.latest_workflow()
        if not workflow:
            raise ValueError("Workflow not found")

        normalized_inputs = dict(inputs_payload or {})
        if isinstance(normalized_inputs.get("roi"), dict):
            normalized_inputs["roi"] = normalize_geometry(normalized_inputs["roi"])
        if isinstance(normalized_inputs.get("viewport_geometry"), dict):
            normalized_inputs["viewport_geometry"] = normalize_geometry(normalized_inputs["viewport_geometry"])

        if not idempotency_key:
            idempotency_key = sha256_json(
                {
                    "workflow_id": workflow["workflow_id"],
                    "workflow_version": workflow["version"],
                    "inputs": normalized_inputs,
                }
            )

        with self._lock:
            existing_id = self.idempotency_index.get(idempotency_key)
            if existing_id and existing_id in self.runs:
                return self.runs[existing_id]

            run_id = f"run.{uuid.uuid4()}"
            now = utc_now_iso()
            run = {
                "run_id": run_id,
                "trigger_id": trigger_id,
                "workflow_id": workflow["workflow_id"],
                "workflow_version": workflow["version"],
                "inputs_payload": normalized_inputs,
                "status": "queued",
                "stage_progress": [
                    {"stage": "queued", "status": "completed", "progress": 1.0, "message": "Queued", "at": now}
                ],
                "artifacts": [],
                "logs": [],
                "idempotency_key": idempotency_key,
                "cache_keys": [],
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "finished_at": None,
            }
            self.runs[run_id] = run
            self.idempotency_index[idempotency_key] = run_id
            self._save_state()

        worker = threading.Thread(target=self._execute_run, args=(run_id,), daemon=True, name=f"run-{run_id}")
        worker.start()
        return run

    def _log_run(self, run_id: str, message: str) -> None:
        with self._lock:
            run = self.runs.get(run_id)
            if not run:
                return
            run.setdefault("logs", []).append({"at": utc_now_iso(), "message": message})
            run["updated_at"] = utc_now_iso()
            self._save_state()

    def _set_run_status(self, run_id: str, status: str, message: str | None = None, stage: str | None = None, progress: float | None = None) -> None:
        with self._lock:
            run = self.runs.get(run_id)
            if not run:
                return
            run["status"] = status
            now = utc_now_iso()
            run["updated_at"] = now
            if status == "running" and not run.get("started_at"):
                run["started_at"] = now
            if status in {"failed", "completed"}:
                run["finished_at"] = now
            if stage:
                run.setdefault("stage_progress", []).append(
                    {
                        "stage": stage,
                        "status": status,
                        "progress": float(progress if progress is not None else 0.0),
                        "message": message or "",
                        "at": now,
                    }
                )
            if message:
                run.setdefault("logs", []).append({"at": now, "message": message})
            self._save_state()
            snapshot = dict(run)
        if self.on_run_status:
            try:
                self.on_run_status(snapshot)
            except Exception:
                pass

    def _add_artifact(self, run_id: str, artifact_type: str, file_name: str, content: bytes, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        run_folder = self.runs_dir / run_id
        run_folder.mkdir(parents=True, exist_ok=True)
        output_path = run_folder / file_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        digest = sha256_bytes(content)
        artifact = {
            "artifact_id": f"art.{uuid.uuid4()}",
            "run_id": run_id,
            "type": artifact_type,
            "uri": str(output_path),
            "sha256": digest,
            "created_at": utc_now_iso(),
            "metadata": metadata or {},
        }
        with self._lock:
            run = self.runs.get(run_id)
            if run:
                run.setdefault("artifacts", []).append(artifact)
                run["updated_at"] = utc_now_iso()
                self._save_state()
        return artifact

    def _json_artifact(self, run_id: str, artifact_type: str, file_name: str, payload: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = (json.dumps(payload, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
        return self._add_artifact(run_id, artifact_type, file_name, raw, metadata=metadata)

    def _stage_cache_get(self, cache_key: str) -> dict[str, Any] | None:
        with self._lock:
            return self.stage_cache.get(cache_key)

    def _stage_cache_put(self, cache_key: str, output: dict[str, Any]) -> None:
        with self._lock:
            self.stage_cache[cache_key] = {
                "cache_key": cache_key,
                "saved_at": utc_now_iso(),
                "output": output,
            }
            self._save_state()

    def _append_cache_key(self, run_id: str, cache_key: str) -> None:
        with self._lock:
            run = self.runs.get(run_id)
            if not run:
                return
            keys = run.setdefault("cache_keys", [])
            if cache_key not in keys:
                keys.append(cache_key)
                self._save_state()

    def _dependency_payload(self, node: dict[str, Any], node_outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for dep in node.get("depends_on") or []:
            merged.update(node_outputs.get(dep) or {})
        return merged

    def _execute_skill_node(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        node: dict[str, Any],
        dep_payload: dict[str, Any],
        stage_data: dict[str, Any],
    ) -> dict[str, Any]:
        skill_id = node.get("skill")
        if skill_id == "evidence_bundle":
            return self._stage_evidence_bundle(run, workflow)

        if skill_id == "analytics_provider":
            evidence = {
                "scene_set": dep_payload.get("scene_set") or stage_data.get("scene_set") or [],
                "roi": dep_payload.get("roi") or stage_data.get("roi") or {},
            }
            if not evidence["scene_set"] or not isinstance(evidence["roi"], dict):
                raise ValueError(f"node {node.get('id')} missing evidence inputs")
            return self._stage_analytics(run, workflow, evidence)

        if skill_id == "scene_metrics":
            detections = dep_payload.get("detections") or stage_data.get("detections")
            if not isinstance(detections, dict):
                raise ValueError(f"node {node.get('id')} missing detections input")
            return self._stage_metrics(run, detections)

        if skill_id == "change_pol":
            metrics_payload = dep_payload.get("scene_metrics") or stage_data.get("scene_metrics")
            if not isinstance(metrics_payload, dict):
                raise ValueError(f"node {node.get('id')} missing scene_metrics input")
            return self._stage_change_and_pol(run, metrics_payload)

        if skill_id == "ai_scene_change_agent":
            evidence_stage = {
                "scene_set": dep_payload.get("scene_set") or stage_data.get("scene_set") or [],
                "evidence_bundle": dep_payload.get("evidence_bundle") or stage_data.get("evidence_bundle") or {},
            }
            change_notes = dep_payload.get("change_notes") or stage_data.get("change_notes") or {}
            if not evidence_stage["scene_set"]:
                raise ValueError(f"node {node.get('id')} missing scene_set input")
            return self._stage_ai_scene_change(run, workflow, evidence_stage, change_notes)

        if skill_id == "report_writer":
            report_stage = dict(stage_data)
            report_stage.update(dep_payload)
            required = ("evidence_bundle", "scene_metrics", "change_notes")
            missing = [k for k in required if not isinstance(report_stage.get(k), dict)]
            if missing:
                raise ValueError(f"node {node.get('id')} missing inputs for report_writer: {', '.join(missing)}")
            report_md, report_json = self._build_report(workflow, run, report_stage)
            self._add_artifact(
                run["run_id"],
                "md",
                "report.md",
                report_md.encode("utf-8"),
                metadata={"profile": report_json.get("profile")},
            )
            self._json_artifact(run["run_id"], "json", "report.json", report_json)
            return {"report_md": report_md, "report_json": report_json}

        raise ValueError(f"node {node.get('id')} uses skill with no runtime handler: {skill_id}")

    def _stage_evidence_bundle(self, run: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
        params = dict(workflow.get("default_params") or {})
        params.update(run.get("inputs_payload", {}).get("params") or {})
        inputs = run.get("inputs_payload") or {}

        roi = inputs.get("roi") or inputs.get("viewport_geometry")
        if not isinstance(roi, dict):
            raise ValueError("Run inputs missing roi/viewport_geometry")
        roi = normalize_geometry(roi)

        contract_id = inputs.get("contract_id")
        scene_ids = inputs.get("scene_ids") or []
        start_date = inputs.get("start_date")
        end_date = inputs.get("end_date")
        require_selected_scenes = bool(params.get("require_selected_scenes", False))

        if require_selected_scenes and not scene_ids:
            raise ValueError("This workflow requires selected carousel scenes (scene_ids)")

        scenes: list[dict[str, Any]] = []
        if scene_ids:
            for scene_id in scene_ids:
                scene_id_s = str(scene_id)
                if not scene_id_s:
                    continue
                item = self.resolve_item_fn(scene_id_s, contract_id)
                if not item:
                    continue
                scenes.append(scene_from_item(item))
        else:
            start_dt = parse_dt(start_date) or (utc_now() - timedelta(days=45))
            end_dt = parse_dt(end_date) or utc_now()
            search_payload = {
                "geometry": roi,
                "start_date": to_iso_date(start_dt),
                "end_date": to_iso_date(end_dt),
                "collection_id": (inputs.get("collection_id") or "l1d-sr"),
                "contract_id": contract_id,
                "limit": int(params.get("max_scenes") or 24),
                "max_cloud_cover": inputs.get("max_cloud_cover", 60),
                "satellite_name": inputs.get("satellite_name"),
                "min_gsd": inputs.get("min_gsd"),
                "max_gsd": inputs.get("max_gsd"),
            }
            items = self.search_items_fn(search_payload)
            scenes = [scene_from_item(i) for i in items]

        scenes = [s for s in scenes if s.get("scene_id")]
        scenes.sort(key=lambda x: x.get("captured_at") or "")
        max_scenes = int(params.get("max_scenes") or 24)
        if max_scenes > 0:
            scenes = scenes[-max_scenes:]
        if len(scenes) < 1:
            raise ValueError("No scenes resolved for run")

        cache_key = sha256_json(
            {
                "stage": "evidence_bundle",
                "workflow": f"{workflow['workflow_id']}@{workflow['version']}",
                "roi_hash": sha256_json(roi),
                "scene_ids": [s.get("scene_id") for s in scenes],
                "params": params,
            }
        )
        self._append_cache_key(run["run_id"], cache_key)
        cached = self._stage_cache_get(cache_key)
        if cached:
            output = cached.get("output") or {}
            if output:
                self._log_run(run["run_id"], f"evidence_bundle cache hit key={cache_key[:12]}")
                return output

        evidence = {
            "report_context": {
                "roi": roi,
                "time_span": {
                    "start": scenes[0].get("captured_at"),
                    "end": scenes[-1].get("captured_at"),
                },
                "filters": inputs.get("filters") or {},
                "trigger_id": run.get("trigger_id"),
                "workflow": f"{workflow['workflow_id']}@{workflow['version']}",
            },
            "scenes": [],
        }

        for scene in scenes:
            evidence["scenes"].append(
                {
                    "scene_id": scene.get("scene_id"),
                    "captured_at": scene.get("captured_at"),
                    "quality": scene.get("quality"),
                    "chip_uris": {
                        "thumbnail": scene.get("assets", {}).get("thumbnail"),
                        "preview": scene.get("assets", {}).get("preview"),
                        "visual": scene.get("assets", {}).get("visual"),
                    },
                    "analytics_uris": [],
                }
            )

        art_bundle = self._json_artifact(
            run["run_id"],
            "json",
            "evidence_bundle.json",
            evidence,
            metadata={"scene_count": len(scenes)},
        )

        output = {
            "roi": roi,
            "scene_set": scenes,
            "evidence_bundle": evidence,
            "evidence_artifact": art_bundle,
        }
        self._stage_cache_put(cache_key, output)
        return output

    def _normalize_provider_output(self, features: list[dict[str, Any]], provider: BaseProvider) -> dict[str, Any]:
        normalized = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            geom = feature.get("geometry")
            props = feature.get("properties") or {}
            if not isinstance(geom, dict):
                continue
            normalized.append(
                {
                    "type": "Feature",
                    "geometry": normalize_geometry(geom),
                    "properties": {
                        "scene_id": props.get("scene_id"),
                        "captured_at": props.get("captured_at"),
                        "class_label": props.get("label") or props.get("class") or "unknown",
                        "analytic_type": props.get("analytic_type") or "unknown",
                        "confidence": maybe_float(props.get("confidence")) or 0.0,
                        "provider_id": provider.manifest.provider_id,
                        "provider_version": provider.manifest.provider_version,
                        "model_version": props.get("model") or "unknown",
                        "processed_at": props.get("processed_at") or utc_now_iso(),
                    },
                }
            )
        return {"type": "FeatureCollection", "features": normalized}

    def _stage_analytics(self, run: dict[str, Any], workflow: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
        params = dict(workflow.get("default_params") or {})
        params.update(run.get("inputs_payload", {}).get("params") or {})

        provider_id = str(params.get("provider_id") or "thirdparty.mock")
        provider = self.providers.get(provider_id)
        if not provider:
            raise ValueError(f"Unknown provider: {provider_id}")

        analytic_types = params.get("analytic_types") or ["change"]
        if not isinstance(analytic_types, list):
            analytic_types = [str(analytic_types)]

        scene_ids = [s.get("scene_id") for s in evidence.get("scene_set", []) if s.get("scene_id")]
        cache_key = sha256_json(
            {
                "stage": "analytics",
                "provider": f"{provider.manifest.provider_id}@{provider.manifest.provider_version}",
                "scenes": scene_ids,
                "roi_hash": sha256_json(evidence.get("roi") or {}),
                "analytic_types": analytic_types,
                "params": params,
            }
        )
        self._append_cache_key(run["run_id"], cache_key)
        cached = self._stage_cache_get(cache_key)
        if cached:
            output = cached.get("output") or {}
            if output:
                self._log_run(run["run_id"], f"analytics cache hit key={cache_key[:12]}")
                return output

        provider_features = provider.run(
            scenes=evidence.get("scene_set") or [],
            roi=evidence.get("roi") or {},
            analytic_types=[str(a) for a in analytic_types],
            params=params,
        )
        detections = self._normalize_provider_output(provider_features, provider)
        art = self._json_artifact(
            run["run_id"],
            "geojson",
            "detections.geojson",
            detections,
            metadata={
                "provider_id": provider.manifest.provider_id,
                "provider_version": provider.manifest.provider_version,
                "analytic_types": analytic_types,
            },
        )
        output = {
            "detections": detections,
            "provider": {
                "provider_id": provider.manifest.provider_id,
                "provider_version": provider.manifest.provider_version,
                "capabilities": provider.manifest.capabilities,
            },
            "detections_artifact": art,
        }
        self._stage_cache_put(cache_key, output)
        return output

    def _feature_area(self, feature: dict[str, Any]) -> float:
        geom = feature.get("geometry")
        if not isinstance(geom, dict):
            return 0.0
        try:
            return abs(float(shape(geom).area))
        except Exception:
            return 0.0

    def _stage_metrics(self, run: dict[str, Any], detections_fc: dict[str, Any]) -> dict[str, Any]:
        features = detections_fc.get("features") or []
        metrics_by_scene: dict[str, dict[str, Any]] = {}
        class_totals: dict[str, int] = {}
        for ft in features:
            props = ft.get("properties") or {}
            scene_id = props.get("scene_id") or ""
            label = props.get("class_label") or "unknown"
            conf = maybe_float(props.get("confidence")) or 0.0
            area = self._feature_area(ft)
            class_totals[label] = class_totals.get(label, 0) + 1

            row = metrics_by_scene.setdefault(
                scene_id,
                {
                    "scene_id": scene_id,
                    "captured_at": props.get("captured_at"),
                    "detection_count": 0,
                    "total_area": 0.0,
                    "by_class": {},
                    "confidence": {"sum": 0.0, "count": 0},
                },
            )
            row["detection_count"] += 1
            row["total_area"] += area
            row["by_class"][label] = row["by_class"].get(label, 0) + 1
            row["confidence"]["sum"] += conf
            row["confidence"]["count"] += 1

        scenes = []
        for scene_id, row in metrics_by_scene.items():
            count = max(1, int(row["confidence"]["count"]))
            scenes.append(
                {
                    "scene_id": scene_id,
                    "captured_at": row.get("captured_at"),
                    "detection_count": int(row["detection_count"]),
                    "total_area": round(float(row["total_area"]), 8),
                    "by_class": row.get("by_class") or {},
                    "mean_confidence": round(float(row["confidence"]["sum"]) / count, 4),
                }
            )
        scenes.sort(key=lambda x: x.get("captured_at") or "")

        summary = {
            "scene_count": len(scenes),
            "total_detections": sum(s["detection_count"] for s in scenes),
            "total_area": round(sum(s["total_area"] for s in scenes), 8),
            "class_totals": class_totals,
        }

        metrics_payload = {"summary": summary, "scenes": scenes}
        art = self._json_artifact(run["run_id"], "json", "scene_metrics.json", metrics_payload)
        return {"scene_metrics": metrics_payload, "metrics_artifact": art}

    def _stage_change_and_pol(self, run: dict[str, Any], metrics_payload: dict[str, Any]) -> dict[str, Any]:
        scenes = metrics_payload.get("scenes") or []
        if len(scenes) < 2:
            change = {"notes": [], "deltas": {}, "status": "insufficient_frames"}
            pol = {"baseline": {}, "deviations": [], "status": "insufficient_frames"}
        else:
            first = scenes[0]
            last = scenes[-1]
            first_counts = first.get("by_class") or {}
            last_counts = last.get("by_class") or {}
            labels = sorted(set(first_counts.keys()) | set(last_counts.keys()))
            deltas = {
                label: int(last_counts.get(label, 0)) - int(first_counts.get(label, 0))
                for label in labels
            }
            notes = []
            for label in labels:
                delta = deltas[label]
                if delta > 0:
                    notes.append(f"{label} increased by {delta}")
                elif delta < 0:
                    notes.append(f"{label} decreased by {abs(delta)}")
            if not notes:
                notes = ["No class-level detection count change observed"]

            baseline = {}
            for label in labels:
                series = [int((s.get("by_class") or {}).get(label, 0)) for s in scenes]
                mean = sum(series) / max(1, len(series))
                baseline[label] = {
                    "mean": round(mean, 4),
                    "latest": int(series[-1]),
                    "deviation": round(series[-1] - mean, 4),
                }
            pol = {
                "baseline": baseline,
                "deviations": [
                    {"label": label, **vals}
                    for label, vals in baseline.items()
                    if abs(float(vals.get("deviation", 0.0))) >= 1.0
                ],
                "status": "ok",
            }
            change = {
                "notes": notes,
                "deltas": deltas,
                "first_scene": first.get("scene_id"),
                "last_scene": last.get("scene_id"),
                "status": "ok",
            }

        change_art = self._json_artifact(run["run_id"], "json", "change_notes.json", change)
        pol_art = self._json_artifact(run["run_id"], "json", "pattern_of_life.json", pol)
        return {
            "change_notes": change,
            "pattern_of_life": pol,
            "change_artifact": change_art,
            "pol_artifact": pol_art,
        }

    def _stage_ai_scene_change(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        evidence: dict[str, Any],
        change_notes: dict[str, Any],
    ) -> dict[str, Any]:
        params = dict(workflow.get("default_params") or {})
        params.update(run.get("inputs_payload", {}).get("params") or {})
        base_prompt = str(
            params.get("ai_prompt")
            or "Describe the scene and summarize observed changes between the selected captures."
        ).strip()
        additional_prompt = str(params.get("additional_prompt") or "").strip()
        if additional_prompt:
            prompt = f"{base_prompt}\n\nAdditional analyst prompt:\n{additional_prompt}"
        else:
            prompt = base_prompt

        scene_set = evidence.get("scene_set") or []
        frames = []
        for scene in scene_set:
            assets = scene.get("assets") or {}
            quality = scene.get("quality") or {}
            frames.append(
                {
                    "id": scene.get("scene_id"),
                    "datetime": scene.get("captured_at"),
                    "cloud_cover": quality.get("cloud_cover"),
                    "assets": {
                        "thumbnail": assets.get("thumbnail") or "",
                        "preview": assets.get("preview") or "",
                        "visual": assets.get("visual") or "",
                    },
                }
            )
        latest = frames[-1] if frames else None

        contract_id = (run.get("inputs_payload") or {}).get("contract_id")

        def _download(url: str) -> bytes:
            parsed = urlparse(url)
            host = (parsed.netloc or "").lower()
            if host.endswith("example.com"):
                raise RuntimeError("sample URL skipped")
            if not self.download_bytes_fn:
                raise RuntimeError("download callback unavailable")
            return self.download_bytes_fn(url, contract_id)

        report_markdown, insights = generate_geo_report(
            prompt=prompt,
            frames=frames,
            latest_item=latest,
            downloader=_download,
        )
        ai_payload = {
            "prompt": prompt,
            "narrative_markdown": report_markdown,
            "insights": insights,
            "scene_count": len(frames),
            "change_notes": change_notes or {},
        }
        art_md = self._add_artifact(
            run["run_id"],
            "md",
            "ai_scene_change.md",
            report_markdown.encode("utf-8"),
            metadata={"scene_count": len(frames)},
        )
        art_json = self._json_artifact(
            run["run_id"],
            "json",
            "ai_scene_change.json",
            ai_payload,
            metadata={"scene_count": len(frames)},
        )
        return {
            "ai_narrative": ai_payload,
            "ai_narrative_artifact": art_md,
            "ai_narrative_json_artifact": art_json,
        }

    def _docx_paragraph_xml(self, text: str, style: str | None = None, bold: bool = False) -> str:
        value = xml_escape((text or "").replace("\r", ""))
        if not value:
            return "<w:p/>"
        style_xml = f'<w:pPr><w:pStyle w:val="{xml_escape(style)}"/></w:pPr>' if style else ""
        run_prop = "<w:rPr><w:b/></w:rPr>" if bold else ""
        return f'<w:p>{style_xml}<w:r>{run_prop}<w:t xml:space="preserve">{value}</w:t></w:r></w:p>'

    def _docx_image_xml(self, rid: str, docpr_id: int, name: str, cx: int, cy: int) -> str:
        safe_name = xml_escape(name or f"Image {docpr_id}")
        return (
            "<w:p><w:r><w:drawing>"
            '<wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{docpr_id}" name="{safe_name}"/>'
            "<wp:cNvGraphicFramePr/>"
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            "<pic:nvPicPr>"
            f'<pic:cNvPr id="{docpr_id}" name="{safe_name}"/>'
            "<pic:cNvPicPr/>"
            "</pic:nvPicPr>"
            "<pic:blipFill>"
            f'<a:blip r:embed="{xml_escape(rid)}"/>'
            '<a:stretch><a:fillRect/></a:stretch>'
            "</pic:blipFill>"
            "<pic:spPr>"
            '<a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            "</pic:spPr>"
            "</pic:pic>"
            "</a:graphicData>"
            "</a:graphic>"
            "</wp:inline>"
            "</w:drawing></w:r></w:p>"
        )

    def _download_docx_inset_images(self, run: dict[str, Any], report_json: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
        if not self.download_bytes_fn:
            return []
        contract_id = (run.get("inputs_payload") or {}).get("contract_id")
        image_insets = report_json.get("image_insets") or []
        out: list[dict[str, Any]] = []
        for idx, scene in enumerate(image_insets):
            if idx >= limit:
                break
            uri = (scene.get("chip_uri") or "").strip()
            if not uri:
                continue
            try:
                parsed = urlparse(uri)
                host = (parsed.netloc or "").lower()
                if host.endswith("example.com"):
                    continue
            except Exception:
                pass
            try:
                raw = self.download_bytes_fn(uri, contract_id)
                with Image.open(BytesIO(raw)) as img:
                    rgb = img.convert("RGB")
                    if rgb.width > 1800:
                        ratio = 1800.0 / float(rgb.width)
                        rgb = rgb.resize((1800, max(1, int(round(rgb.height * ratio)))), resample=Image.Resampling.BICUBIC)
                    buf = BytesIO()
                    rgb.save(buf, format="JPEG", quality=88)
                    data = buf.getvalue()
                    out.append(
                        {
                            "scene_id": scene.get("scene_id") or f"scene_{idx + 1}",
                            "captured_at": scene.get("captured_at") or "",
                            "file_name": f"image_{idx + 1}.jpg",
                            "bytes": data,
                            "width": int(rgb.width),
                            "height": int(rgb.height),
                        }
                    )
            except Exception:
                continue
        return out

    def _build_report_docx_bytes(
        self,
        workflow: dict[str, Any],
        run: dict[str, Any],
        report_json: dict[str, Any],
        report_md: str,
        ai_narrative: dict[str, Any] | None,
    ) -> bytes:
        images = self._download_docx_inset_images(run, report_json, limit=6)

        paragraphs: list[str] = []
        title = str(report_json.get("profile") or "GeoAgent Evidence Report")
        paragraphs.append(self._docx_paragraph_xml(title, style="Heading1"))
        paragraphs.append(
            self._docx_paragraph_xml(
                f"Workflow: {workflow.get('workflow_id')}@{workflow.get('version')}  |  Run: {run.get('run_id')}",
                style="Normal",
            )
        )
        paragraphs.append(self._docx_paragraph_xml(""))

        summary = (report_json.get("summary") or {}).get("text") or ""
        paragraphs.append(self._docx_paragraph_xml("Executive Summary", style="Heading2"))
        for line in str(summary).splitlines() or [""]:
            paragraphs.append(self._docx_paragraph_xml(line or " "))

        findings = report_json.get("findings") or []
        paragraphs.append(self._docx_paragraph_xml("Findings", style="Heading2"))
        if findings:
            for idx, finding in enumerate(findings, start=1):
                claim = str((finding or {}).get("claim") or "").strip() or "No claim text."
                paragraphs.append(self._docx_paragraph_xml(f"{idx}. {claim}"))
        else:
            paragraphs.append(self._docx_paragraph_xml("No findings generated."))

        if ai_narrative and ai_narrative.get("narrative_markdown"):
            paragraphs.append(self._docx_paragraph_xml("AI Scene-Change Narrative", style="Heading2"))
            for raw_line in str(ai_narrative.get("narrative_markdown") or "").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                paragraphs.append(self._docx_paragraph_xml(line))

        limitations = report_json.get("limitations") or []
        paragraphs.append(self._docx_paragraph_xml("Confidence and Limitations", style="Heading2"))
        conf = report_json.get("confidence") or {}
        paragraphs.append(self._docx_paragraph_xml(f"Overall confidence: {conf.get('overall', 'unknown')}"))
        rationale = str(conf.get("rationale") or "").strip()
        if rationale:
            paragraphs.append(self._docx_paragraph_xml(f"Rationale: {rationale}"))
        for line in limitations:
            paragraphs.append(self._docx_paragraph_xml(f"- {line}"))

        if images:
            paragraphs.append(self._docx_paragraph_xml("Imagery Insets", style="Heading2"))

        image_doc_xml: list[str] = []
        image_rels_xml: list[str] = []
        next_rel_index = 2  # rId1 reserved for styles relation.
        next_docpr_id = 10
        for image in images:
            rid = f"rId{next_rel_index}"
            next_rel_index += 1
            scene_id = image.get("scene_id") or "scene"
            captured_at = image.get("captured_at") or "unknown"
            paragraphs.append(self._docx_paragraph_xml(f"{scene_id} ({captured_at})"))

            width_px = max(1, int(image.get("width") or 1))
            height_px = max(1, int(image.get("height") or 1))
            max_width_emu = int(6.2 * 914400)
            cx = min(max_width_emu, width_px * 9525)
            cy = max(1, int(round((height_px / float(width_px)) * cx)))
            image_doc_xml.append(
                self._docx_image_xml(
                    rid=rid,
                    docpr_id=next_docpr_id,
                    name=scene_id,
                    cx=cx,
                    cy=cy,
                )
            )
            next_docpr_id += 1
            image_rels_xml.append(
                f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{xml_escape(image["file_name"])}"/>'
            )

        appendix = report_json.get("appendix") or {}
        scene_list = appendix.get("scene_list") or []
        if scene_list:
            paragraphs.append(self._docx_paragraph_xml("Scene List", style="Heading2"))
            for scene in scene_list[:40]:
                sid = scene.get("scene_id") or "scene"
                captured = scene.get("captured_at") or "unknown"
                paragraphs.append(self._docx_paragraph_xml(f"- {sid} ({captured})"))

        doc_body = "".join(paragraphs + image_doc_xml)
        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f"<w:body>{doc_body}"
            '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>'
            "</w:body></w:document>"
        )

        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
            '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/>'
            '<w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/>'
            '<w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>'
            "</w:styles>"
        )

        content_types_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="jpg" ContentType="image/jpeg"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            "</Types>"
        )

        package_rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            "</Relationships>"
        )

        doc_rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            f"{''.join(image_rels_xml)}"
            "</Relationships>"
        )

        created = xml_escape(utc_now_iso())
        core_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{xml_escape(title)}</dc:title>"
            "<dc:creator>GeoAgent</dc:creator>"
            "<cp:lastModifiedBy>GeoAgent</cp:lastModifiedBy>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>'
            "</cp:coreProperties>"
        )

        out = BytesIO()
        with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types_xml.encode("utf-8"))
            zf.writestr("_rels/.rels", package_rels_xml.encode("utf-8"))
            zf.writestr("word/document.xml", document_xml.encode("utf-8"))
            zf.writestr("word/styles.xml", styles_xml.encode("utf-8"))
            zf.writestr("word/_rels/document.xml.rels", doc_rels_xml.encode("utf-8"))
            zf.writestr("docProps/core.xml", core_xml.encode("utf-8"))
            for image in images:
                zf.writestr(f"word/media/{image['file_name']}", image["bytes"])
        return out.getvalue()

    def _build_report(self, workflow: dict[str, Any], run: dict[str, Any], stage_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        params = dict(workflow.get("default_params") or {})
        params.update(run.get("inputs_payload", {}).get("params") or {})
        profile = str(params.get("profile") or "airbase")

        evidence = stage_data["evidence_bundle"]
        scenes = evidence.get("scenes") or []
        metrics = stage_data["scene_metrics"]
        change = stage_data["change_notes"]
        pol = stage_data["pattern_of_life"]
        ai_narrative = stage_data.get("ai_narrative") if isinstance(stage_data.get("ai_narrative"), dict) else {}

        scene_refs = []
        for scene in scenes:
            sid = scene.get("scene_id") or ""
            captured = scene.get("captured_at") or ""
            chip_uri = (scene.get("chip_uris") or {}).get("preview") or (scene.get("chip_uris") or {}).get("thumbnail") or ""
            scene_refs.append({"scene_id": sid, "captured_at": captured, "chip_uri": chip_uri})
        inset_refs = [s for s in scene_refs if s.get("chip_uri")][-8:]

        findings: list[str] = []
        findings_json: list[dict[str, Any]] = []
        if profile == "forest_urban":
            deltas = change.get("deltas") or {}
            forest_delta = int(deltas.get("forest_loss", 0))
            urban_delta = int(deltas.get("urban_expansion", deltas.get("urban_change", 0)))
            anchor_scene = scene_refs[-1] if scene_refs else {"scene_id": "unknown", "captured_at": "unknown", "chip_uri": ""}
            token = (
                f"[EVIDENCE scene_id={anchor_scene['scene_id']} captured_at={anchor_scene['captured_at']} "
                f"artifact=metrics uri=scene_metrics.json]"
            )
            if forest_delta > 0:
                forest_claim = f"Forest-loss detections increased by {forest_delta} across the selected scene series"
            elif forest_delta < 0:
                forest_claim = f"Forest-loss detections decreased by {abs(forest_delta)} across the selected scene series"
            else:
                forest_claim = "No net forest-loss detection change was observed across the selected scene series"
            if urban_delta > 0:
                urban_claim = f"Urban-expansion detections increased by {urban_delta} across the selected scene series"
            elif urban_delta < 0:
                urban_claim = f"Urban-expansion detections decreased by {abs(urban_delta)} across the selected scene series"
            else:
                urban_claim = "No net urban-expansion detection change was observed across the selected scene series"
            for claim in (forest_claim, urban_claim):
                findings.append(f"- {claim}. {token}")
                findings_json.append(
                    {
                        "claim": claim,
                        "evidence": {
                            "scene_id": anchor_scene["scene_id"],
                            "captured_at": anchor_scene["captured_at"],
                            "artifact": "metrics",
                            "uri": "scene_metrics.json",
                        },
                    }
                )
        else:
            for idx, note in enumerate((change.get("notes") or [])[:8]):
                scene = scene_refs[min(idx, max(0, len(scene_refs) - 1))] if scene_refs else {"scene_id": "unknown", "captured_at": "unknown", "chip_uri": ""}
                token = (
                    f"[EVIDENCE scene_id={scene['scene_id']} captured_at={scene['captured_at']} "
                    f"artifact=metrics uri=scene_metrics.json]"
                )
                findings.append(f"- {note}. {token}")
                findings_json.append(
                    {
                        "claim": note,
                        "evidence": {
                            "scene_id": scene["scene_id"],
                            "captured_at": scene["captured_at"],
                            "artifact": "metrics",
                            "uri": "scene_metrics.json",
                        },
                    }
                )

        if not findings and scene_refs:
            s = scene_refs[0]
            token = f"[EVIDENCE scene_id={s['scene_id']} captured_at={s['captured_at']} artifact=chip uri={s['chip_uri']}]"
            findings = [f"- No robust change signal exceeded configured thresholds. {token}"]
            findings_json = [
                {
                    "claim": "No robust change signal exceeded configured thresholds.",
                    "evidence": {
                        "scene_id": s["scene_id"],
                        "captured_at": s["captured_at"],
                        "artifact": "chip",
                        "uri": s["chip_uri"],
                    },
                }
            ]

        summary_text = (
            "Observed temporal activity and infrastructure indicators are summarized with explicit evidence references."
            if profile == "airbase"
            else "Observed land-use and vegetation change signals are summarized with explicit evidence references."
        )
        if profile == "landuse":
            summary_text = (
                "Observed land-cover change signals are reported conservatively for follow-up review; "
                "this report does not assert legal conclusions."
            )
        if profile == "forest_urban":
            summary_text = (
                "Observed forest-loss and urban-expansion change signals are summarized over the selected scene series "
                "with explicit evidence references and inset imagery."
            )

        limitations = [
            "Findings depend on available scene quality (cloud/shadow/geometry).",
            "Automated detections are model outputs and require analyst review for high-impact conclusions.",
            "Area values are geometric approximations in source CRS units.",
        ]
        confidence = {
            "overall": "moderate" if metrics.get("summary", {}).get("total_detections", 0) else "low",
            "rationale": "Confidence is based on scene count, mean model confidence, and temporal consistency.",
        }

        report_title = "Land Use / Deforestation Change Evidence Report"
        if profile == "airbase":
            report_title = "Airbase Time Series Analyst Report"
        elif profile == "forest_urban":
            report_title = "Forest and Urban Change Time Series Evidence Report"

        report_json = {
            "profile": report_title,
            "summary": {
                "text": summary_text,
                "scene_count": len(scene_refs),
                "time_span": evidence.get("report_context", {}).get("time_span") or {},
            },
            "findings": findings_json,
            "image_insets": inset_refs,
            "ai_narrative": {
                "prompt": ai_narrative.get("prompt"),
                "insights": ai_narrative.get("insights") or [],
                "artifact_uri": "ai_scene_change.md" if ai_narrative.get("narrative_markdown") else None,
            },
            "confidence": confidence,
            "limitations": limitations,
            "appendix": {
                "scene_list": scene_refs,
                "artifacts": [
                    {"type": "evidence_bundle", "uri": "evidence_bundle.json"},
                    {"type": "detections", "uri": "detections.geojson"},
                    {"type": "metrics", "uri": "scene_metrics.json"},
                ],
                "provenance": {
                    "workflow": f"{workflow['workflow_id']}@{workflow['version']}",
                    "provider": stage_data.get("provider") or {},
                    "parameters": params,
                },
            },
        }
        ok, reason = report_json_schema_check(report_json)
        if not ok:
            raise ValueError(reason)

        md_lines = [
            f"# {report_json['profile']}",
            "",
            "## Scope",
            f"- Workflow: `{workflow['workflow_id']}@{workflow['version']}`",
            f"- Trigger: `{run.get('trigger_id') or 'manual'}`",
            f"- Time span: `{(evidence.get('report_context') or {}).get('time_span', {}).get('start')}` to `{(evidence.get('report_context') or {}).get('time_span', {}).get('end')}`",
            "",
            "## Executive Summary",
            report_json["summary"]["text"],
            "",
            "## Findings",
        ]
        md_lines.extend(findings)
        if ai_narrative.get("narrative_markdown"):
            md_lines.extend(["", "## AI Scene-Change Narrative"])
            for raw_line in str(ai_narrative.get("narrative_markdown") or "").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                md_lines.append(line)
        if inset_refs:
            md_lines.extend(["", "## Image Insets"])
            for scene in inset_refs:
                token = (
                    f"[EVIDENCE scene_id={scene['scene_id']} captured_at={scene['captured_at']} "
                    f"artifact=chip uri={scene['chip_uri']}]"
                )
                md_lines.append(f"- {scene['scene_id']} ({scene['captured_at']}) {token}")
                md_lines.append(f"  ![{scene['scene_id']}]({scene['chip_uri']})")
        md_lines.extend(
            [
                "",
                "## Pattern Of Life",
                f"- Baseline classes tracked: {', '.join(sorted((pol.get('baseline') or {}).keys())) or 'none'}",
                f"- Deviation alerts: {len(pol.get('deviations') or [])}",
                "",
                "## Confidence & Limitations",
                f"- Overall confidence: **{confidence['overall']}**",
                f"- Rationale: {confidence['rationale']}",
            ]
        )
        for line in limitations:
            md_lines.append(f"- {line}")
        md_lines.extend(
            [
                "",
                "## Appendix",
                "### Scene List",
            ]
        )
        for scene in scene_refs:
            token = (
                f"[EVIDENCE scene_id={scene['scene_id']} captured_at={scene['captured_at']} "
                f"artifact=chip uri={scene['chip_uri']}]"
            )
            md_lines.append(f"- {scene['scene_id']} ({scene['captured_at']}) {token}")

        md_lines.extend(
            [
                "",
                "### Provenance",
                f"- Workflow: `{workflow['workflow_id']}@{workflow['version']}`",
                f"- Provider: `{(stage_data.get('provider') or {}).get('provider_id', 'unknown')}@{(stage_data.get('provider') or {}).get('provider_version', 'unknown')}`",
                "- Artifact hash manifest: `hashes.txt`",
            ]
        )

        report_md = "\n".join(md_lines).strip() + "\n"
        lint_ok, lint_reason, lint_lines = lint_citations(report_md)
        if not lint_ok:
            raise ValueError(f"citation_linter_failed: {lint_reason}; lines={lint_lines[:3]}")
        return report_md, report_json

    def _git_commit(self) -> str:
        try:
            import subprocess

            repo_dir: Path | None = None
            for parent in Path(__file__).resolve().parents:
                if (parent / ".git").exists():
                    repo_dir = parent
                    break
            if repo_dir is None:
                return "unknown"
            out = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_dir,
                timeout=1.5,
                stderr=subprocess.DEVNULL,
            )
            return out.decode("utf-8").strip() or "unknown"
        except Exception:
            return "unknown"

    def _write_provenance(self, run: dict[str, Any], workflow: dict[str, Any], stage_data: dict[str, Any]) -> dict[str, Any]:
        params = dict(workflow.get("default_params") or {})
        params.update(run.get("inputs_payload", {}).get("params") or {})
        provenance = {
            "run_id": run["run_id"],
            "created_at": run.get("created_at"),
            "workflow": {
                "id": workflow.get("workflow_id"),
                "version": workflow.get("version"),
                "graph_json": workflow.get("graph_json"),
            },
            "skills": [{"skill_id": s.get("skill_id"), "version": s.get("version")} for s in self.skills],
            "provider": stage_data.get("provider") or {},
            "parameters": params,
            "idempotency_key": run.get("idempotency_key"),
            "cache_keys": run.get("cache_keys") or [],
            "environment": {
                "pipeline_version": "geoagent-workbench-v1",
                "git_commit": self._git_commit(),
                "python": os.sys.version,
            },
            "timestamps": {
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
            },
        }
        return provenance

    def _write_hashes_manifest(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id) or {}
        lines = []
        for art in run.get("artifacts", []):
            lines.append(f"{art.get('sha256')}  {Path(str(art.get('uri'))).name}")
        payload = "\n".join(lines).strip() + "\n"
        art = self._add_artifact(run_id, "txt", "hashes.txt", payload.encode("utf-8"), metadata={"count": len(lines)})
        return art

    def _execute_run(self, run_id: str) -> None:
        run = self.get_run(run_id)
        if not run:
            return
        workflow = self.resolve_workflow(run.get("workflow_id"), run.get("workflow_version"))
        if not workflow:
            self._set_run_status(run_id, "failed", message="Workflow missing", stage="failed", progress=1.0)
            return

        try:
            self._set_run_status(run_id, "running", message="Run started", stage="started", progress=0.02)
            graph_nodes = self._normalize_graph_nodes(workflow.get("graph_json") or {"nodes": []})
            self._validate_graph_connections(graph_nodes)
            ordered_nodes = self._topological_nodes(graph_nodes)

            node_outputs: dict[str, dict[str, Any]] = {}
            stage_data: dict[str, Any] = {}
            total_nodes = max(1, len(ordered_nodes))

            for idx, node in enumerate(ordered_nodes, start=1):
                stage_start = 0.08 + ((idx - 1) / total_nodes) * 0.72
                message = f"Running node {node.get('id')} ({node.get('skill')})"
                self._set_run_status(
                    run_id,
                    "running",
                    message=message,
                    stage=str(node.get("id") or node.get("skill") or f"stage_{idx}"),
                    progress=min(0.85, stage_start),
                )
                dep_payload = self._dependency_payload(node, node_outputs)
                output = self._execute_skill_node(run, workflow, node, dep_payload, stage_data)
                if not isinstance(output, dict):
                    output = {}
                node_outputs[node["id"]] = output
                stage_data.update(output)

            if "report_json" not in stage_data:
                raise ValueError("Workflow graph did not produce report output (missing report_writer stage)")

            self._set_run_status(run_id, "running", message="Rendering DOCX report artifact", stage="publish_docx", progress=0.9)
            docx_bytes = self._build_report_docx_bytes(
                workflow=workflow,
                run=run,
                report_json=stage_data.get("report_json") or {},
                report_md=stage_data.get("report_md") or "",
                ai_narrative=stage_data.get("ai_narrative") if isinstance(stage_data.get("ai_narrative"), dict) else None,
            )
            self._add_artifact(
                run_id,
                "docx",
                "report.docx",
                docx_bytes,
                metadata={"profile": (stage_data.get("report_json") or {}).get("profile")},
            )

            self._set_run_status(run_id, "running", message="Writing provenance and integrity manifests", stage="publish", progress=0.94)
            provenance = self._write_provenance(run, workflow, stage_data)
            self._json_artifact(run_id, "json", "provenance.json", provenance)
            self._write_hashes_manifest(run_id)

            self._set_run_status(run_id, "completed", message="Run completed", stage="completed", progress=1.0)
        except Exception as exc:
            logger.exception("workbench run failed run_id=%s", run_id)
            self._set_run_status(run_id, "failed", message=f"Run failed: {exc}", stage="failed", progress=1.0)

    # ----- Scheduler / trigger loop -----
    def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick_schedules()
            except Exception:
                logger.exception("workbench scheduler tick failed")
            self._stop.wait(20.0)

    def _token_matches(self, token: str, value: int) -> bool:
        token = token.strip()
        if token == "*":
            return True
        if token.startswith("*/"):
            step = int(token[2:])
            if step <= 0:
                return False
            return value % step == 0
        parts = [p.strip() for p in token.split(",") if p.strip()]
        for p in parts:
            if p.isdigit() and int(p) == value:
                return True
        return False

    def _cron_due(self, expr: str, now: datetime) -> bool:
        parts = expr.split()
        if len(parts) != 5:
            return False
        minute, hour, dom, month, dow = parts
        # Python weekday: Mon=0..Sun=6; cron: Sun=0/7..Sat=6
        cron_dow = (now.weekday() + 1) % 7
        return (
            self._token_matches(minute, now.minute)
            and self._token_matches(hour, now.hour)
            and self._token_matches(dom, now.day)
            and self._token_matches(month, now.month)
            and self._token_matches(dow, cron_dow)
        )

    def _tick_schedules(self) -> None:
        now = utc_now()
        schedules = self.list_schedules()
        for schedule in schedules:
            if not schedule.get("enabled", True):
                continue
            trigger_type = (schedule.get("type") or "").upper()
            try:
                if trigger_type in {"CRON", "MANUAL"}:
                    self._tick_periodic(schedule, now)
                elif trigger_type in {"IMAGERY_ARRIVAL", "STACK_ARRIVAL"}:
                    self._tick_arrival(schedule, now)
            except Exception as exc:
                logger.warning("schedule tick failed trigger_id=%s error=%s", schedule.get("trigger_id"), exc)

    def _tick_periodic(self, schedule: dict[str, Any], now: datetime) -> None:
        trigger_id = schedule["trigger_id"]
        last_fired = parse_dt(schedule.get("last_fired_at"))
        due = False

        interval_seconds = int(schedule.get("interval_seconds") or 0)
        if interval_seconds > 0:
            if not last_fired or (now - last_fired).total_seconds() >= interval_seconds:
                due = True

        cron_expr = (schedule.get("cron") or "").strip()
        if cron_expr:
            if self._cron_due(cron_expr, now):
                if not last_fired or (now - last_fired).total_seconds() >= 55:
                    due = True

        if not due:
            return

        inputs = {
            "roi": (schedule.get("scope") or {}).get("geometry"),
            "start_date": to_iso_date(now - timedelta(days=7)),
            "end_date": to_iso_date(now),
            "filters": schedule.get("filters") or {},
            "params": {
                "max_scenes": int(((schedule.get("batching") or {}).get("max_scenes_per_run") or 24)),
            },
        }
        run = self.create_run(
            workflow_id=schedule.get("workflow_id"),
            workflow_version=schedule.get("workflow_version"),
            inputs_payload=inputs,
            trigger_id=trigger_id,
        )
        with self._lock:
            row = self.schedules.get(trigger_id)
            if row:
                row["last_fired_at"] = utc_now_iso()
                row["updated_at"] = utc_now_iso()
                self.events.append({"type": "run.created", "run_id": run["run_id"], "trigger_id": trigger_id, "at": utc_now_iso()})
                self._save_state()

    def _subscription_geometry(self, schedule: dict[str, Any]) -> dict[str, Any] | None:
        sub_id = schedule.get("subscription_id")
        if not sub_id:
            return (schedule.get("scope") or {}).get("geometry")
        sub = self.subscriptions.get(sub_id)
        if not sub:
            return None
        if sub.get("geometry"):
            return sub.get("geometry")
        poi_id = sub.get("poi_set_id")
        if poi_id and poi_id in self.poi_sets:
            poi = self.poi_sets[poi_id]
            if poi.get("geometry"):
                return poi.get("geometry")
            features = poi.get("features") or []
            if features:
                geoms = []
                for ft in features:
                    if isinstance(ft, dict) and isinstance(ft.get("geometry"), dict):
                        geoms.append(shape(ft["geometry"]))
                if geoms:
                    merged = geoms[0]
                    for g in geoms[1:]:
                        merged = merged.union(g)
                    return mapping(merged.envelope)
        return None

    def _tick_arrival(self, schedule: dict[str, Any], now: datetime) -> None:
        trigger_id = schedule["trigger_id"]
        geometry = self._subscription_geometry(schedule)
        if not isinstance(geometry, dict):
            return

        last_checked = parse_dt(schedule.get("last_checked_at")) or (now - timedelta(hours=6))
        # coalescing: poll at most every 120s by default
        if (now - last_checked).total_seconds() < 120:
            return

        filters = schedule.get("filters") or {}
        collection_id = filters.get("collection_id") or "l1d-sr"
        max_limit = int(((schedule.get("batching") or {}).get("max_scenes_per_run") or 24))
        search_payload = {
            "geometry": normalize_geometry(geometry),
            "start_date": to_iso_date(last_checked - timedelta(minutes=5)),
            "end_date": to_iso_date(now),
            "collection_id": collection_id,
            "contract_id": filters.get("contract_id"),
            "limit": max(50, max_limit * 3),
            "max_cloud_cover": filters.get("max_cloud_cover", 60),
            "satellite_name": filters.get("satellite_name"),
            "min_gsd": filters.get("min_gsd"),
            "max_gsd": filters.get("max_gsd"),
        }
        items = self.search_items_fn(search_payload)
        if not items:
            with self._lock:
                row = self.schedules.get(trigger_id)
                if row:
                    row["last_checked_at"] = utc_now_iso()
                    row["updated_at"] = utc_now_iso()
                    self._save_state()
            return

        tile_scope = set(geometry_quadkeys(geometry, zoom=6))
        seen = set(schedule.get("seen_scene_ids") or [])
        new_items: list[dict[str, Any]] = []
        for item in sorted(items, key=lambda x: x.get("datetime") or ""):
            sid = item.get("id")
            if not sid or sid in seen:
                continue
            fp = item.get("geometry")
            if not isinstance(fp, dict):
                continue
            # tile-index prefilter then geometry refine
            if tile_scope:
                scene_tiles = geometry_quadkeys(fp, zoom=6)
                if not scene_tiles.intersection(tile_scope):
                    continue
            try:
                if not shape(fp).intersects(shape(geometry)):
                    continue
            except Exception:
                continue
            new_items.append(item)

        if not new_items:
            with self._lock:
                row = self.schedules.get(trigger_id)
                if row:
                    row["last_checked_at"] = utc_now_iso()
                    row["updated_at"] = utc_now_iso()
                    self._save_state()
            return

        trigger_type = (schedule.get("type") or "").upper()
        if trigger_type == "STACK_ARRIVAL":
            by_stack: dict[str, list[dict[str, Any]]] = {}
            for item in new_items:
                key = str(item.get("outcome_id") or item.get("id") or "")
                by_stack.setdefault(key, []).append(item)
            # Coalesce to one representative scene per stack by latest datetime.
            reduced = []
            for _, rows in by_stack.items():
                rows.sort(key=lambda x: x.get("datetime") or "", reverse=True)
                reduced.append(rows[0])
            new_items = reduced

        # Cap and dedupe per run.
        new_items.sort(key=lambda x: x.get("datetime") or "", reverse=True)
        selected = new_items[:max_limit]

        run_inputs = {
            "roi": geometry,
            "scene_ids": [i.get("id") for i in selected if i.get("id")],
            "start_date": to_iso_date(parse_dt(selected[-1].get("datetime")) or (now - timedelta(days=1))),
            "end_date": to_iso_date(parse_dt(selected[0].get("datetime")) or now),
            "filters": filters,
            "params": {
                "max_scenes": max_limit,
            },
        }
        run = self.create_run(
            workflow_id=schedule.get("workflow_id"),
            workflow_version=schedule.get("workflow_version"),
            inputs_payload=run_inputs,
            trigger_id=trigger_id,
        )

        with self._lock:
            row = self.schedules.get(trigger_id)
            if row:
                existing = set(row.get("seen_scene_ids") or [])
                for item in new_items:
                    sid = item.get("id")
                    if sid:
                        existing.add(sid)
                row["seen_scene_ids"] = list(sorted(existing))[-5000:]
                row["last_checked_at"] = utc_now_iso()
                row["last_fired_at"] = utc_now_iso()
                row["updated_at"] = utc_now_iso()
                self.events.append({"type": "imagery.arrived", "trigger_id": trigger_id, "scene_count": len(new_items), "at": utc_now_iso()})
                self.events.append({"type": "run.created", "run_id": run["run_id"], "trigger_id": trigger_id, "at": utc_now_iso()})
                self._save_state()
