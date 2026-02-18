from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import logging
import time
import base64
import re
import struct
import threading
import uuid
import zipfile
import xml.etree.ElementTree as ET
import zlib
from urllib.parse import parse_qs, quote, urlparse
from io import BytesIO

import requests
from PIL import Image

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .geoagent import generate_geo_report
from .models import (
    AnimationSearchRequest,
    AnimationRequest,
    CueCreateRequest,
    DownloadBundleRequest,
    GeoAgentRequest,
    GeoAgentResponse,
    HealthResponse,
    MonitoringEventAckRequest,
    MonitoringEventCreateRequest,
    MonitoringSubscriptionCreateRequest,
    Mp4AnimationJobRequest,
    PoiSetCreateRequest,
    RunCreateRequest,
    ScheduleCreateRequest,
    SchedulePatchRequest,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SubscriptionCreateRequest,
    TaskingOrderCreateRequest,
    WorkflowDefinitionPayload,
)
from .monitoring_store import MonitoringStore
from .merlin_sentinel2_client import MerlinSentinel2Client
from .satellogic_client import SatellogicClient
from .source_manager import DEFAULT_SOURCE_ID, SOURCE_MERLIN_S2, SOURCE_SATELLOGIC, SourceManager
from .services import (
    make_animation_gif,
    make_capture_mosaic_animation,
    make_selected_extent_mp4,
)
from .workbench import GeoWorkbenchEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("image_mate")

app = FastAPI(title="image-mate", version="0.1.0")
client = SatellogicClient()
merlin_client = MerlinSentinel2Client()
sources = SourceManager(client, merlin_client)
TRANSPARENT_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)
_TRANSPARENT_TILE_CACHE: dict[int, bytes] = {}
_TILE_CONTRACT_CACHE_LOCK = threading.Lock()
_TILE_CONTRACT_CACHE = {
    "value": "",
    "fetched_at": 0.0,
    "last_attempt": 0.0,
    "last_error": "",
}
_TILE_CONTRACT_CACHE_TTL_SECONDS = 1800.0
_TILE_CONTRACT_RETRY_SECONDS = 60.0


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    chunk_type = bytes(tag or b"")
    payload = bytes(data or b"")
    checksum = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack("!I", len(payload)) + chunk_type + payload + struct.pack("!I", checksum)


def _transparent_png_tile(size: int) -> bytes:
    tile_size = max(1, int(size or 256))
    cached = _TRANSPARENT_TILE_CACHE.get(tile_size)
    if cached is not None:
        return cached

    row = b"\x00" + (b"\x00\x00\x00\x00" * tile_size)
    raw = row * tile_size
    compressed = zlib.compress(raw, level=9)
    ihdr = struct.pack("!IIBBBBB", tile_size, tile_size, 8, 6, 0, 0, 0)
    payload = b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", compressed),
            _png_chunk(b"IEND", b""),
        ]
    )
    _TRANSPARENT_TILE_CACHE[tile_size] = payload
    return payload

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.state.item_cache = {}
app.state.asset_cache = {}
app.state.asset_cache_stats = {"hits": 0, "misses": 0}
app.state.tile_cache_stats = {"hits": 0, "misses": 0}
app.state.tile_delivery_stats = {
    "newsat": {"requests": 0, "errors": 0, "bytes": 0, "ms": 0},
    "merlin": {"requests": 0, "errors": 0, "bytes": 0, "ms": 0},
}
app.state.archive_search_stats = {"total": 0, "by_collection": {}}
app.state.mp4_jobs = {}
app.state.mp4_jobs_lock = threading.Lock()
app.state.workbench = None
app.state.workbench_lock = threading.Lock()
app.state.monitoring_store = MonitoringStore(settings.monitoring_db_path)


@app.on_event("startup")
def startup_event():
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    auth_mode = getattr(client, "auth_mode", "unknown")
    uses_oauth = auth_mode in {"oauth", "oauth_client_credentials", "auto"}
    has_client_credentials = bool(getattr(client, "key_id", "") and getattr(client, "key_secret", ""))
    if uses_oauth and has_client_credentials:
        try:
            refreshed, expiry = client.refresh_access_token()
            if refreshed:
                logger.info(
                    "startup token refresh ok auth_mode=%s expires_at=%s",
                    auth_mode,
                    expiry.isoformat() if expiry else "unknown",
                )
            else:
                logger.warning("startup token refresh returned no token auth_mode=%s", auth_mode)
        except Exception as exc:
            logger.warning("startup token refresh failed auth_mode=%s error=%s", auth_mode, exc)
    if settings.merlin_s2_enabled and settings.cdse_client_id and settings.cdse_client_secret:
        try:
            refreshed, expiry = merlin_client.refresh_access_token()
            if refreshed:
                logger.info(
                    "startup CDSE token refresh ok expires_at=%s",
                    expiry.isoformat() if expiry else "unknown",
                )
            else:
                logger.warning("startup CDSE token refresh returned no token")
        except Exception as exc:
            logger.warning("startup CDSE token refresh failed error=%s", exc)
    try:
        _ensure_workbench()
    except Exception as exc:
        logger.warning("workbench startup failed: %s", exc)


@app.on_event("shutdown")
def shutdown_event():
    wb = app.state.workbench
    if wb:
        try:
            wb.stop()
        except Exception:
            pass


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _mp4_job_public(job: dict[str, Any]) -> dict[str, Any]:
    out = {
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "progress_current": int(job.get("progress_current", 0)),
        "progress_total": int(job.get("progress_total", 0)),
        "frame_count": int(job.get("frame_count", 0)),
        "message": job.get("message"),
        "error": job.get("error"),
        "seconds_per_frame": job.get("seconds_per_frame"),
        "file_name": job.get("file_name"),
        "file_size_bytes": job.get("file_size_bytes"),
    }
    if out["status"] == "completed":
        out["download_url"] = f"/api/archive/animate/mp4/jobs/{job.get('job_id')}/download"
    return out


def _set_mp4_job(job_id: str, **updates):
    with app.state.mp4_jobs_lock:
        job = app.state.mp4_jobs.get(job_id)
        if not job:
            return
        prev_status = str(job.get("status") or "")
        job.update(updates)
        job["updated_at"] = _utc_now_iso()
        next_status = str(job.get("status") or "")
        if next_status and next_status != prev_status:
            logger.info(
                "mp4_job_status job_id=%s status=%s message=%s",
                job_id,
                next_status,
                job.get("message") or "",
            )
        elif updates.get("error"):
            logger.error(
                "mp4_job_error job_id=%s status=%s error=%s",
                job_id,
                next_status or prev_status,
                updates.get("error"),
            )


def _prune_mp4_jobs(max_jobs: int = 40):
    with app.state.mp4_jobs_lock:
        jobs = app.state.mp4_jobs
        if len(jobs) <= max_jobs:
            return
        removable = [
            j for j in jobs.values()
            if j.get("status") in {"completed", "failed"}
        ]
        removable.sort(key=lambda j: j.get("created_at") or "")
        overflow = max(0, len(jobs) - max_jobs)
        for old in removable[:overflow]:
            job_id = old.get("job_id")
            if not job_id:
                continue
            file_path = old.get("file")
            if file_path:
                try:
                    path = Path(file_path)
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass
            jobs.pop(job_id, None)


def _run_mp4_animation_job(job_id: str, payload: dict[str, Any]):
    try:
        _set_mp4_job(
            job_id,
            status="running",
            started_at=_utc_now_iso(),
            message="Preparing selected full-resolution frames...",
        )

        contract_id = payload.get("contract_id")

        def progress(current: int, total: int, frame_datetime: str | None):
            label = frame_datetime or "unknown datetime"
            _set_mp4_job(
                job_id,
                progress_current=int(current),
                progress_total=int(total),
                message=f"Rendering frame {current}/{total} ({label})",
            )

        result = make_selected_extent_mp4(
            frames=payload.get("frames", []),
            viewport_geometry=payload.get("viewport_geometry"),
            downloader=lambda url: _download_bytes_for_url(url, contract_id=contract_id),
            seconds_per_frame=float(payload.get("seconds_per_frame") or 0.8),
            output_dir=settings.output_dir,
            filename_prefix=payload.get("filename_prefix") or "selected_extent_animation",
            progress_callback=progress,
        )

        if not result.get("created"):
            reason = result.get("reason") or "MP4 render failed"
            logger.error("mp4 animation job result failed job_id=%s reason=%s", job_id, reason)
            _set_mp4_job(
                job_id,
                status="failed",
                finished_at=_utc_now_iso(),
                error=reason,
                message=reason,
            )
            return

        file_path = Path(str(result.get("file") or ""))
        file_size = file_path.stat().st_size if file_path.exists() else 0
        _set_mp4_job(
            job_id,
            status="completed",
            finished_at=_utc_now_iso(),
            message=f"MP4 ready ({result.get('frame_count', 0)} frames)",
            frame_count=int(result.get("frame_count", 0)),
            progress_current=int(result.get("frame_count", 0)),
            progress_total=int(result.get("frame_count", 0)),
            file=str(file_path),
            file_name=file_path.name,
            file_size_bytes=int(file_size),
        )
        logger.info(
            "mp4 animation job completed job_id=%s frames=%s file=%s bytes=%s",
            job_id,
            result.get("frame_count", 0),
            file_path.name,
            file_size,
        )
    except Exception as exc:
        logger.exception("mp4 animation job failed job_id=%s", job_id)
        _set_mp4_job(
            job_id,
            status="failed",
            finished_at=_utc_now_iso(),
            error=str(exc),
            message="MP4 render failed",
        )


def _asset_cache_key(url: str, contract_id: str | None, render: bool) -> str:
    return f"{contract_id or ''}|{int(render)}|{url}"


def _tile_cache_key(
    z: int,
    x: int,
    y: int,
    source_url: str,
    contract_id: str | None,
    scale: int,
    buffer: int,
    tile_matrix_set_id: str,
    image_format: str,
    bidx: list[int],
    render_layer: str,
    cloud_mask_url: str | None,
) -> str:
    return "|".join([
        contract_id or "",
        str(z),
        str(x),
        str(y),
        str(scale),
        str(buffer),
        tile_matrix_set_id,
        image_format,
        ",".join(str(v) for v in sorted(bidx)),
        render_layer,
        cloud_mask_url or "",
        source_url,
    ])


def _asset_kind(url: str) -> str:
    lowered = url.lower()
    if "quickview_visual_thumbnail" in lowered or "quickview-visual-thumb" in lowered:
        return "quickview"
    if "/l1d_sr/" in lowered or "/assets/l1d-sr/" in lowered:
        return "l1d-sr"
    return "other"


def _asset_short(url: str) -> str:
    parsed = urlparse(url)
    filename = parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
    if filename:
        return filename[:120]
    return parsed.netloc[:120]


def _normalize_source_id(source_id: str | None) -> str:
    return sources.normalize_source_id(source_id)


def _source_from_item_id(item_id: str, source_hint: str | None = None) -> tuple[str, str]:
    if source_hint:
        return _normalize_source_id(source_hint), item_id
    return sources.split_item_id(item_id)


def _source_from_url(url: str, source_hint: str | None = None) -> str:
    return sources.infer_source_id_from_url(url, source_hint=source_hint)


def _infer_mp4_tile_source_id(tile: dict[str, Any]) -> str | None:
    raw_item_id = str(tile.get("item_id") or "").strip()
    if raw_item_id:
        try:
            source_id, _ = _source_from_item_id(raw_item_id)
            return _normalize_source_id(source_id)
        except Exception:
            pass
    raw_url = str(tile.get("url") or "").strip()
    if raw_url:
        try:
            return _source_from_url(raw_url)
        except Exception:
            return None
    return None


def _download_bytes_for_url(url: str, contract_id: str | None = None, source_hint: str | None = None) -> bytes:
    return sources.download_bytes(url, contract_id=contract_id, source_hint=source_hint)


def _prune_asset_cache(max_entries: int | None = None):
    if max_entries is None:
        max_entries = max(100, int(settings.asset_cache_max_entries or 1200))
    cache = app.state.asset_cache
    if len(cache) <= max_entries:
        return
    # Remove oldest by insertion order.
    overflow = len(cache) - max_entries
    for key in list(cache.keys())[:overflow]:
        cache.pop(key, None)


def _tile_delivery_bucket(source_key: str) -> dict[str, int]:
    key = (source_key or "unknown").strip().lower()
    if key not in app.state.tile_delivery_stats:
        app.state.tile_delivery_stats[key] = {"requests": 0, "errors": 0, "bytes": 0, "ms": 0}
    return app.state.tile_delivery_stats[key]


def _record_tile_delivery(source_key: str, byte_count: int, elapsed_ms: int, *, error: bool = False) -> None:
    bucket = _tile_delivery_bucket(source_key)
    bucket["requests"] = int(bucket.get("requests", 0)) + 1
    bucket["bytes"] = int(bucket.get("bytes", 0)) + max(0, int(byte_count or 0))
    bucket["ms"] = int(bucket.get("ms", 0)) + max(0, int(elapsed_ms or 0))
    if error:
        bucket["errors"] = int(bucket.get("errors", 0)) + 1


def _short_contract_id(contract_id: str | None) -> str:
    value = str(contract_id or "").strip()
    if not value:
        return ""
    if len(value) <= 18:
        return value
    return f"{value[:10]}...{value[-6:]}"


def _resolve_tile_contract_id(contract_id: str | None, *, force_refresh: bool = False) -> str | None:
    requested = str(contract_id or "").strip()
    if requested:
        return requested

    runtime_value = str(getattr(client, "contract_id", "") or "").strip()
    if runtime_value:
        return runtime_value

    configured_value = str(getattr(settings, "satellogic_contract_id", "") or "").strip()
    if configured_value:
        try:
            client.contract_id = configured_value
        except Exception:
            pass
        return configured_value

    now = time.time()
    with _TILE_CONTRACT_CACHE_LOCK:
        cached = str(_TILE_CONTRACT_CACHE.get("value") or "").strip()
        fetched_at = float(_TILE_CONTRACT_CACHE.get("fetched_at") or 0.0)
        last_attempt = float(_TILE_CONTRACT_CACHE.get("last_attempt") or 0.0)
        if cached and not force_refresh and (now - fetched_at) <= _TILE_CONTRACT_CACHE_TTL_SECONDS:
            return cached
        if not force_refresh and (now - last_attempt) < _TILE_CONTRACT_RETRY_SECONDS:
            return None
        _TILE_CONTRACT_CACHE["last_attempt"] = now

    resolved = ""
    try:
        rows = sources.list_contracts(SOURCE_SATELLOGIC)
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            candidate = str(row.get("id") or row.get("contract_id") or "").strip()
            if candidate:
                resolved = candidate
                break
    except Exception as exc:
        with _TILE_CONTRACT_CACHE_LOCK:
            _TILE_CONTRACT_CACHE["last_error"] = str(exc)
        logger.warning("tile_proxy contract auto-resolve failed error=%s", exc)
        return None

    with _TILE_CONTRACT_CACHE_LOCK:
        _TILE_CONTRACT_CACHE["value"] = resolved
        _TILE_CONTRACT_CACHE["fetched_at"] = now if resolved else 0.0
        _TILE_CONTRACT_CACHE["last_error"] = ""

    if not resolved:
        logger.warning("tile_proxy contract auto-resolve returned no contracts")
        return None

    try:
        client.contract_id = resolved
    except Exception:
        pass

    logger.info("tile_proxy contract auto-resolved contract=%s", _short_contract_id(resolved))
    return resolved


def _extract_embedded_tile_options(url_value: str) -> tuple[str, dict[str, list[str]]]:
    value = str(url_value or "").strip()
    if not value or "&" not in value or "=" not in value:
        return value, {}

    base_url, sep, tail = value.partition("&")
    if not sep or not tail or "=" not in tail:
        return value, {}

    parsed = parse_qs(tail, keep_blank_values=False)
    if not parsed:
        return value, {}

    recognized = {
        "tileMatrixSetId",
        "format",
        "scale",
        "buffer",
        "bidx",
        "contract_id",
        "render_layer",
        "cloud_mask_url",
    }
    embedded: dict[str, list[str]] = {}
    for key in recognized:
        values = parsed.get(key) or []
        cleaned = [str(item).strip() for item in values if str(item).strip()]
        if cleaned:
            embedded[key] = cleaned

    if not embedded:
        return value, {}
    return base_url, embedded


def _safe_filename(name: str, fallback: str = "asset.bin") -> str:
    cleaned = (name or "").strip().replace("\\", "_").replace("/", "_")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned).strip("._")
    return cleaned or fallback


def _filename_from_url(url: str, default_stem: str, default_ext: str = ".tif") -> str:
    try:
        parsed = urlparse(url)
        part = parsed.path.rsplit("/", 1)[-1]
        if part:
            base = _safe_filename(part)
            if "." in base:
                return base
            return f"{base}{default_ext}"
    except Exception:
        pass
    return f"{_safe_filename(default_stem, fallback='asset')}{default_ext}"


def _dedupe_name(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name
    stem, dot, ext = name.partition(".")
    i = 2
    while True:
        candidate = f"{stem}_{i}{dot}{ext}" if dot else f"{stem}_{i}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        i += 1


TASKING_PRODUCTS = [
    {
        "sku": "TSKPOI-M",
        "label": "Point Target (single attempt)",
        "target_types": ["point"],
        "notes": "Single point-target acquisition attempt.",
    },
    {
        "sku": "TSKRSH-M.15.01",
        "label": "Point Revisit 15-day (1 revisit)",
        "target_types": ["point"],
        "notes": "Point target with revisit schedule.",
    },
    {
        "sku": "TSKRSH-M.15.15",
        "label": "Point Revisit 15-day (15 revisits)",
        "target_types": ["point"],
        "notes": "Point target with revisit schedule.",
    },
    {
        "sku": "TSKRSH-M.30.30",
        "label": "Point Revisit 30-day (30 revisits)",
        "target_types": ["point"],
        "notes": "Point target with revisit schedule.",
    },
    {
        "sku": "TSKARE-M",
        "label": "Area Tasking (single attempt)",
        "target_types": ["area"],
        "notes": "Single area tasking request.",
    },
    {
        "sku": "TSKRRD-M.15.01",
        "label": "Area Revisit 15-day (1 revisit)",
        "target_types": ["area"],
        "notes": "Area tasking with remapping schedule.",
    },
    {
        "sku": "TSKRRD-M.15.15",
        "label": "Area Revisit 15-day (15 revisits)",
        "target_types": ["area"],
        "notes": "Area tasking with remapping schedule.",
    },
    {
        "sku": "TSKRRD-M.30.30",
        "label": "Area Revisit 30-day (30 revisits)",
        "target_types": ["area"],
        "notes": "Area tasking with remapping schedule.",
    },
]


def _normalize_tasking_order(raw: dict[str, Any]) -> dict[str, Any]:
    feature = raw.get("feature") if isinstance(raw.get("feature"), dict) else raw
    props = raw.get("properties")
    if not isinstance(props, dict):
        props = feature.get("properties") if isinstance(feature, dict) else None
    properties = props if isinstance(props, dict) else {}
    params = properties.get("parameters")
    if not isinstance(params, dict):
        params = feature.get("parameters") if isinstance(feature, dict) else None
    parameters = params if isinstance(params, dict) else {}
    geometry = raw.get("geometry")
    if not isinstance(geometry, dict):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
    geometry_obj = geometry if isinstance(geometry, dict) else {}
    order_id = (
        raw.get("id")
        or (feature.get("id") if isinstance(feature, dict) else None)
        or properties.get("order_id")
        or properties.get("id")
    )
    sku = (
        properties.get("sku")
        or properties.get("product")
        or properties.get("product_name")
        or properties.get("product_id")
    )
    return {
        "id": order_id,
        "status": properties.get("status") or raw.get("status") or "unknown",
        "order_name": properties.get("order_name") or properties.get("name") or "",
        "project_name": properties.get("project_name") or "",
        "sku": sku,
        "created_at": (
            properties.get("created_at")
            or properties.get("created")
            or raw.get("created_at")
            or raw.get("created")
        ),
        "updated_at": (
            properties.get("updated_at")
            or raw.get("updated_at")
            or raw.get("updated")
        ),
        "start": parameters.get("start") or parameters.get("from"),
        "end": parameters.get("end") or parameters.get("to"),
        "revisit_period": parameters.get("revisit_period"),
        "remapping_period": parameters.get("remapping_period"),
        "geometry_type": geometry_obj.get("type"),
        "geometry": geometry_obj,
        "parameters": parameters,
        "raw": raw,
    }


def _is_tasking_sku(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return text.startswith("TSK")


def _tasking_rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        features = payload.get("features")
        if isinstance(features, list):
            return [row for row in features if isinstance(row, dict)]
        results = payload.get("results")
        if isinstance(results, list):
            return [row for row in results if isinstance(row, dict)]
        if isinstance(payload.get("id"), str):
            return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def _collect_tasking_orders(contract_id: str | None, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    next_url: str | None = None
    pages = 0
    while len(rows) < limit and pages < 6:
        page_limit = min(100, max(1, limit - len(rows)))
        payload = client.list_orders(contract_id=contract_id, limit=page_limit, next_url=next_url)
        page_rows = _tasking_rows_from_payload(payload)
        if not page_rows:
            break
        for row in page_rows:
            normalized = _normalize_tasking_order(row)
            if _is_tasking_sku(normalized.get("sku")):
                rows.append(normalized)
                if len(rows) >= limit:
                    break
        next_val = payload.get("next")
        next_url = str(next_val) if next_val else None
        pages += 1
        if not next_url:
            break
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows[:limit]


if settings.frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(settings.frontend_dir), html=True), name="app")


@app.get("/", include_in_schema=False)
def root():
    index = settings.frontend_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"status": "ok", "message": "frontend not found"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    icon_path = settings.frontend_dir / "favicon.ico"
    if icon_path.exists():
        return FileResponse(icon_path)
    return Response(status_code=204)


@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse()


@app.get("/api/debug/stats")
def debug_stats():
    stats = app.state.asset_cache_stats
    total = int(stats.get("hits", 0)) + int(stats.get("misses", 0))
    hit_rate = (float(stats.get("hits", 0)) / total) if total else 0.0
    tile_stats = app.state.tile_cache_stats
    tile_total = int(tile_stats.get("hits", 0)) + int(tile_stats.get("misses", 0))
    tile_hit_rate = (float(tile_stats.get("hits", 0)) / tile_total) if tile_total else 0.0
    search_stats = app.state.archive_search_stats
    by_collection = search_stats.get("by_collection") if isinstance(search_stats, dict) else {}
    if not isinstance(by_collection, dict):
        by_collection = {}
    tile_delivery_raw = app.state.tile_delivery_stats if isinstance(app.state.tile_delivery_stats, dict) else {}
    tile_delivery: dict[str, dict[str, Any]] = {}
    for source_key, row in tile_delivery_raw.items():
        if not isinstance(row, dict):
            continue
        requests_count = int(row.get("requests", 0))
        errors_count = int(row.get("errors", 0))
        bytes_count = int(row.get("bytes", 0))
        ms_count = int(row.get("ms", 0))
        avg_ms = (ms_count / requests_count) if requests_count else 0.0
        mb_total = bytes_count / (1024 * 1024)
        mbps_avg = (mb_total / (ms_count / 1000.0)) if ms_count else 0.0
        tile_delivery[str(source_key)] = {
            "requests": requests_count,
            "errors": errors_count,
            "bytes": bytes_count,
            "ms": ms_count,
            "avg_ms": round(avg_ms, 2),
            "mb_total": round(mb_total, 3),
            "mbps_avg": round(mbps_avg, 3),
        }
    return {
        "archive_search": {
            "total": int(search_stats.get("total", 0)),
            "by_collection": {str(k): int(v) for k, v in by_collection.items()},
        },
        "asset_proxy": {
            "hits": int(stats.get("hits", 0)),
            "misses": int(stats.get("misses", 0)),
            "total": total,
            "hit_rate": round(hit_rate, 4),
            "cache_entries": len(app.state.asset_cache),
        },
        "tile_proxy": {
            "hits": int(tile_stats.get("hits", 0)),
            "misses": int(tile_stats.get("misses", 0)),
            "total": tile_total,
            "hit_rate": round(tile_hit_rate, 4),
            "cache_entries": len(app.state.asset_cache),
        },
        "tile_delivery": tile_delivery,
    }


@app.get("/api/contracts")
def contracts(source_id: str | None = Query(default=DEFAULT_SOURCE_ID)):
    try:
        source = _normalize_source_id(source_id)
        if not sources.has_source(source):
            raise HTTPException(status_code=400, detail=f"Unknown source_id '{source_id}'")

        raw_contracts = sources.list_contracts(source)
        contracts_list = []
        for record in raw_contracts:
            contract_id = record.get("id") or record.get("contract_id")
            name = record.get("name") or record.get("title") or contract_id
            status = record.get("status")
            if contract_id:
                contracts_list.append({"id": contract_id, "name": name, "status": status, "raw": record})

        default_contract_id = settings.satellogic_contract_id if source == SOURCE_SATELLOGIC else None
        if not default_contract_id and contracts_list:
            default_contract_id = contracts_list[0]["id"]
        return {
            "source_id": source,
            "count": len(contracts_list),
            "default_contract_id": default_contract_id,
            "contracts": contracts_list,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Contract discovery failed: {exc}") from exc


@app.get("/api/collections")
def collections(
    source_id: str | None = Query(default=DEFAULT_SOURCE_ID),
    contract_id: str | None = Query(default=None),
    sentinel_only: bool = Query(default=False),
):
    try:
        source = _normalize_source_id(source_id)
        if not sources.has_source(source):
            raise HTTPException(status_code=400, detail=f"Unknown source_id '{source_id}'")

        raw_collections = sources.list_collections(source, contract_id=contract_id)
        collection_list = []
        for record in raw_collections:
            if not isinstance(record, dict):
                continue
            collection_id = record.get("id")
            if not collection_id:
                continue
            if source == SOURCE_MERLIN_S2 and sentinel_only:
                cid_norm = str(collection_id).strip().lower()
                if not cid_norm.startswith("sentinel-2"):
                    continue
            title = record.get("title") or collection_id
            description = record.get("description")
            collection_list.append({
                "id": str(collection_id),
                "title": str(title),
                "description": str(description) if description else None,
            })

        collection_list.sort(key=lambda item: item["id"])
        if source == SOURCE_MERLIN_S2:
            default_collection_id = settings.cdse_sentinel2_collections[0] if settings.cdse_sentinel2_collections else None
        else:
            default_collection_id = settings.satellogic_collection_id or None
        if not default_collection_id and collection_list:
            default_collection_id = collection_list[0]["id"]
        return {
            "source_id": source,
            "count": len(collection_list),
            "default_collection_id": default_collection_id,
            "collections": collection_list,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Collection discovery failed: {exc}") from exc


@app.get("/api/sources")
def list_sources():
    rows = sources.list_sources()
    enabled = [row for row in rows if bool(row.get("enabled"))]
    return {
        "count": len(enabled),
        "default_source_id": DEFAULT_SOURCE_ID,
        "sources": enabled,
    }


WMTS_NAMESPACES = {
    "wmts": "http://www.opengis.net/wmts/1.0",
    "ows": "http://www.opengis.net/ows/1.1",
}


def _preferred_wmts_layer(available_layers: list[str], requested_layer_id: str) -> str:
    requested = (requested_layer_id or "").strip()
    if requested and requested in set(available_layers):
        return requested
    for candidate in ("NATURAL-COLOR", "TRUE-COLOR", "TRUE-COLOR-S2L2A"):
        if candidate in set(available_layers):
            return candidate
    return available_layers[0]


def _parse_wmts_capabilities(xml_text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "layers": [],
        "layer_tile_matrix_sets": {},
        "layer_time_defaults": {},
    }
    if not xml_text:
        return parsed
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return parsed

    layer_nodes = root.findall(".//wmts:Contents/wmts:Layer", WMTS_NAMESPACES)
    for layer_node in layer_nodes:
        identifier = layer_node.findtext("ows:Identifier", default="", namespaces=WMTS_NAMESPACES).strip()
        if not identifier:
            continue
        parsed["layers"].append(identifier)

        matrix_sets = []
        for link_node in layer_node.findall("wmts:TileMatrixSetLink", WMTS_NAMESPACES):
            matrix_id = link_node.findtext("wmts:TileMatrixSet", default="", namespaces=WMTS_NAMESPACES).strip()
            if matrix_id and matrix_id not in matrix_sets:
                matrix_sets.append(matrix_id)
        if matrix_sets:
            parsed["layer_tile_matrix_sets"][identifier] = matrix_sets

        for dimension in layer_node.findall("wmts:Dimension", WMTS_NAMESPACES):
            dim_id = dimension.findtext("ows:Identifier", default="", namespaces=WMTS_NAMESPACES).strip().lower()
            if dim_id != "time":
                continue
            default_time = dimension.findtext("wmts:Default", default="", namespaces=WMTS_NAMESPACES).strip()
            if default_time:
                parsed["layer_time_defaults"][identifier] = default_time
            break

    return parsed


def _extract_ows_exception_text(xml_text: str) -> str:
    match = re.search(
        r"<(?:ows:)?ExceptionText>\s*(.*?)\s*</(?:ows:)?ExceptionText>",
        xml_text or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return str(match.group(1)).strip()
    match = re.search(
        r"<ServiceException>\s*(.*?)\s*</ServiceException>",
        xml_text or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return str(match.group(1)).strip()
    return ""


@app.get("/api/layers/sentinel/wmts")
def sentinel_wmts_layer(layer_id: str | None = Query(default=None)):
    base_url = (settings.cdse_wmts_base_url or "").strip().rstrip("/")
    instance_id = (settings.cdse_wmts_instance_id or "").strip()
    configured_layer_id = (settings.cdse_wmts_layer_id or "TRUE-COLOR").strip()
    requested_layer_id = (layer_id or configured_layer_id or "TRUE-COLOR").strip()
    image_format = (settings.cdse_wmts_format or "image/png").strip()
    tile_matrix_set = (settings.cdse_wmts_tile_matrix_set or "PopularWebMercator256").strip()

    if not settings.merlin_s2_enabled:
        logger.info("sentinel_wmts unavailable reason=merlin_source_disabled")
        return {"available": False, "reason": "Merlin Sentinel-2 source is disabled."}
    if not base_url:
        logger.info("sentinel_wmts unavailable reason=missing_base_url")
        return {"available": False, "reason": "CDSE_WMTS_BASE_URL is not configured."}
    if not instance_id:
        logger.info("sentinel_wmts unavailable reason=missing_instance_id")
        return {"available": False, "reason": "CDSE_WMTS_INSTANCE_ID is not configured."}
    if not requested_layer_id:
        logger.info("sentinel_wmts unavailable reason=missing_layer_id")
        return {"available": False, "reason": "CDSE_WMTS_LAYER_ID is not configured."}

    selected_layer_id = requested_layer_id
    selected_tile_matrix_set = tile_matrix_set
    available_layers: list[str] = []
    layer_tile_matrix_sets: dict[str, list[str]] = {}
    layer_time_defaults: dict[str, str] = {}
    warning_parts: list[str] = []
    capabilities_url = (
        f"{base_url}/{quote(instance_id, safe='')}"
        "?SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0"
    )
    try:
        cap_resp = requests.get(capabilities_url, timeout=4)
        if cap_resp.status_code < 400:
            parsed = _parse_wmts_capabilities(cap_resp.text or "")
            available_layers = list(parsed.get("layers") or [])
            layer_tile_matrix_sets = dict(parsed.get("layer_tile_matrix_sets") or {})
            layer_time_defaults = dict(parsed.get("layer_time_defaults") or {})
            if available_layers and selected_layer_id not in set(available_layers):
                selected_layer_id = _preferred_wmts_layer(available_layers, requested_layer_id)
                warning_parts.append(
                    f"Configured layer '{requested_layer_id}' was not in WMTS capabilities. "
                    f"Using '{selected_layer_id}'."
                )
        else:
            warning_parts.append(f"WMTS capabilities probe returned status {cap_resp.status_code}.")
    except Exception as exc:
        warning_parts.append(f"WMTS capabilities probe skipped: {exc}")

    supported_matrix_sets = layer_tile_matrix_sets.get(selected_layer_id) or []
    if supported_matrix_sets and selected_tile_matrix_set not in set(supported_matrix_sets):
        fallback_matrix = (
            "PopularWebMercator256" if "PopularWebMercator256" in set(supported_matrix_sets)
            else ("PopularWebMercator512" if "PopularWebMercator512" in set(supported_matrix_sets) else supported_matrix_sets[0])
        )
        warning_parts.append(
            f"Configured tile matrix set '{tile_matrix_set}' not available for layer '{selected_layer_id}'. "
            f"Using '{fallback_matrix}'."
        )
        selected_tile_matrix_set = fallback_matrix
    default_time = layer_time_defaults.get(selected_layer_id)

    upstream_template_url = (
        f"{base_url}/{quote(instance_id, safe='')}"
        f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        f"&LAYER={quote(selected_layer_id, safe='')}"
        f"&TILEMATRIXSET={quote(selected_tile_matrix_set, safe='')}"
        f"&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}"
        f"&FORMAT={quote(image_format, safe='')}"
    )
    if default_time:
        upstream_template_url = f"{upstream_template_url}&TIME={quote(default_time, safe=':/')}"

    proxy_template_url = (
        f"/api/layers/sentinel/wmts/tiles/{{z}}/{{x}}/{{y}}"
        f"?layer_id={quote(selected_layer_id, safe='')}"
        f"&tile_matrix_set={quote(selected_tile_matrix_set, safe='')}"
        f"&format={quote(image_format, safe='')}"
    )
    if default_time:
        proxy_template_url = f"{proxy_template_url}&time={quote(default_time, safe=':/')}"

    probe_url = (
        upstream_template_url
        .replace("{z}", "1")
        .replace("{x}", "1")
        .replace("{y}", "1")
    )
    probe_failure_reason: str | None = None
    try:
        probe_resp = requests.get(probe_url, timeout=5)
        probe_ctype = (probe_resp.headers.get("content-type") or "").lower()
        if probe_resp.status_code >= 400 or "xml" in probe_ctype:
            extracted = _extract_ows_exception_text(probe_resp.text or "")
            probe_failure_reason = extracted or f"HTTP {probe_resp.status_code}"
    except Exception as exc:
        warning_parts.append(f"WMTS tile probe skipped: {exc}")

    warning = " ".join(part.strip() for part in warning_parts if part.strip()) or None
    if probe_failure_reason:
        reason = f"WMTS tile probe failed: {probe_failure_reason}"
        warning = f"{warning} {reason}".strip() if warning else reason
        logger.warning(
            "sentinel_wmts unavailable instance_id=%s requested_layer=%s resolved_layer=%s matrix=%s reason=%s",
            instance_id,
            requested_layer_id,
            selected_layer_id,
            selected_tile_matrix_set,
            reason,
        )
        return {
            "available": False,
            "reason": reason,
            "provider": "Copernicus Data Space Ecosystem",
            "layer_id": selected_layer_id,
            "requested_layer_id": requested_layer_id,
            "available_layers": available_layers,
            "tile_matrix_set": selected_tile_matrix_set,
            "requested_tile_matrix_set": tile_matrix_set,
            "format": image_format,
            "capabilities_url": capabilities_url,
            "default_time": default_time,
            "warning": warning,
            "template_url": proxy_template_url,
            "upstream_template_url": upstream_template_url,
            "attribution": "Copernicus Sentinel data via CDSE",
        }

    logger.info(
        "sentinel_wmts available instance_id=%s requested_layer=%s resolved_layer=%s matrix=%s warning=%s",
        instance_id,
        requested_layer_id,
        selected_layer_id,
        selected_tile_matrix_set,
        warning or "",
    )

    return {
        "available": True,
        "provider": "Copernicus Data Space Ecosystem",
        "layer_id": selected_layer_id,
        "requested_layer_id": requested_layer_id,
        "available_layers": available_layers,
        "tile_matrix_set": selected_tile_matrix_set,
        "requested_tile_matrix_set": tile_matrix_set,
        "format": image_format,
        "capabilities_url": capabilities_url,
        "default_time": default_time,
        "warning": warning,
        "template_url": proxy_template_url,
        "upstream_template_url": upstream_template_url,
        "attribution": "Copernicus Sentinel data via CDSE",
    }


@app.get("/api/layers/sentinel/wmts/tiles/{z}/{x}/{y}")
def sentinel_wmts_tile_proxy(
    z: int,
    x: int,
    y: int,
    layer_id: str = Query(..., min_length=1),
    tile_matrix_set: str | None = Query(default=None),
    format: str | None = Query(default=None),
    time_param: str | None = Query(default=None, alias="time"),
):
    if z < 0 or x < 0 or y < 0:
        raise HTTPException(status_code=400, detail="Invalid WMTS tile coordinates")
    if not settings.merlin_s2_enabled:
        raise HTTPException(status_code=404, detail="Merlin Sentinel-2 source is disabled")

    base_url = (settings.cdse_wmts_base_url or "").strip().rstrip("/")
    instance_id = (settings.cdse_wmts_instance_id or "").strip()
    if not base_url or not instance_id:
        raise HTTPException(status_code=400, detail="WMTS base URL or instance ID is not configured")

    selected_layer_id = (layer_id or "").strip()
    selected_matrix = (tile_matrix_set or settings.cdse_wmts_tile_matrix_set or "PopularWebMercator256").strip()
    selected_format = (format or settings.cdse_wmts_format or "image/png").strip()
    selected_time = (time_param or "").strip()

    upstream_url = (
        f"{base_url}/{quote(instance_id, safe='')}"
        f"?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
        f"&LAYER={quote(selected_layer_id, safe='')}"
        f"&TILEMATRIXSET={quote(selected_matrix, safe='')}"
        f"&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}"
        f"&FORMAT={quote(selected_format, safe='')}"
    )
    if selected_time:
        upstream_url = f"{upstream_url}&TIME={quote(selected_time, safe=':/')}"

    started = time.perf_counter()
    now = time.time()
    cache_key = (
        f"wmts:{selected_layer_id}:{selected_matrix}:{selected_format}:{selected_time}:{z}:{x}:{y}"
    )
    cache_entry = app.state.asset_cache.get(cache_key)
    if cache_entry and cache_entry["expires_at"] > now:
        app.state.tile_cache_stats["hits"] += 1
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        payload = cache_entry["content"]
        _record_tile_delivery("merlin", len(payload), elapsed_ms)
        logger.info(
            "wmts_tile_proxy cache=hit layer=%s zxy=%s/%s/%s bytes=%s ms=%s",
            selected_layer_id,
            z,
            x,
            y,
            len(payload),
            elapsed_ms,
        )
        return Response(
            content=payload,
            media_type=cache_entry.get("media_type", "image/png"),
            headers={"Cache-Control": f"public, max-age={int(settings.proxy_cache_ttl_seconds)}", "X-Proxy-Cache": "hit"},
        )
    if cache_entry:
        app.state.asset_cache.pop(cache_key, None)
    app.state.tile_cache_stats["misses"] += 1

    try:
        upstream = requests.get(upstream_url, timeout=12)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _record_tile_delivery("merlin", 0, elapsed_ms, error=True)
        raise HTTPException(status_code=502, detail=f"WMTS tile request failed: {exc}") from exc

    upstream_ctype = (upstream.headers.get("Content-Type") or "").lower()
    if upstream.status_code >= 400 or "xml" in upstream_ctype:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _record_tile_delivery("merlin", 0, elapsed_ms, error=True)
        detail = _extract_ows_exception_text(upstream.text or "")
        if not detail:
            detail = (upstream.text or "").strip().replace("\n", " ")[:220]
        raise HTTPException(
            status_code=upstream.status_code if upstream.status_code >= 400 else 502,
            detail=f"WMTS tile failed upstream: {detail or upstream.status_code}",
        )

    payload = upstream.content
    media_type = upstream.headers.get("Content-Type", selected_format or "image/png")
    if len(payload) <= 2_000_000:
        app.state.asset_cache[cache_key] = {
            "content": payload,
            "media_type": media_type,
            "expires_at": now + int(settings.proxy_cache_ttl_seconds),
        }
        _prune_asset_cache()

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _record_tile_delivery("merlin", len(payload), elapsed_ms)
    logger.info(
        "wmts_tile_proxy cache=miss layer=%s zxy=%s/%s/%s bytes=%s ms=%s",
        selected_layer_id,
        z,
        x,
        y,
        len(payload),
        elapsed_ms,
    )
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Cache-Control": f"public, max-age={int(settings.proxy_cache_ttl_seconds)}", "X-Proxy-Cache": "miss"},
    )


@app.get("/api/tasking/products")
def tasking_products():
    return {"count": len(TASKING_PRODUCTS), "products": TASKING_PRODUCTS}


@app.get("/api/tasking/projects")
def tasking_projects(
    contract_id: str | None = Query(default=None),
    limit: int = Query(default=120, ge=1, le=500),
):
    try:
        orders = _collect_tasking_orders(contract_id=contract_id, limit=limit)
        projects = sorted({
            str(order.get("project_name") or "").strip()
            for order in orders
            if str(order.get("project_name") or "").strip()
        })
        return {"count": len(projects), "projects": projects}
    except requests.HTTPError as exc:
        status_code = int(getattr(getattr(exc, "response", None), "status_code", 502) or 502)
        detail = (getattr(getattr(exc, "response", None), "text", "") or str(exc)).strip()
        raise HTTPException(status_code=status_code, detail=f"Tasking project list failed: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Tasking project list failed: {exc}") from exc


@app.get("/api/tasking/orders")
def tasking_orders(
    contract_id: str | None = Query(default=None),
    limit: int = Query(default=120, ge=1, le=500),
):
    try:
        orders = _collect_tasking_orders(contract_id=contract_id, limit=limit)
        return {"count": len(orders), "orders": orders}
    except requests.HTTPError as exc:
        status_code = int(getattr(getattr(exc, "response", None), "status_code", 502) or 502)
        detail = (getattr(getattr(exc, "response", None), "text", "") or str(exc)).strip()
        raise HTTPException(status_code=status_code, detail=f"Tasking order list failed: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Tasking order list failed: {exc}") from exc


@app.get("/api/tasking/orders/{order_id}")
def tasking_order_detail(
    order_id: str,
    contract_id: str | None = Query(default=None),
):
    try:
        row = client.get_order(order_id, contract_id=contract_id)
        return {"order": _normalize_tasking_order(row), "raw": row}
    except requests.HTTPError as exc:
        status_code = int(getattr(getattr(exc, "response", None), "status_code", 502) or 502)
        detail = (getattr(getattr(exc, "response", None), "text", "") or str(exc)).strip()
        raise HTTPException(status_code=status_code, detail=f"Tasking order fetch failed: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Tasking order fetch failed: {exc}") from exc


@app.post("/api/tasking/orders")
def tasking_orders_create(request: TaskingOrderCreateRequest):
    geometry_type = (request.geometry or {}).get("type") if isinstance(request.geometry, dict) else None
    if request.target_type == "point" and geometry_type != "Point":
        raise HTTPException(status_code=400, detail="Point target requires Point geometry")
    if request.target_type == "area" and geometry_type != "Polygon":
        raise HTTPException(status_code=400, detail="Area target requires Polygon geometry")

    parameters: dict[str, Any] = {
        "start": request.start_date,
        "end": request.end_date,
    }
    if request.target_type == "point" and request.revisit_period:
        parameters["revisit_period"] = request.revisit_period
    if request.target_type == "area" and request.remapping_period:
        parameters["remapping_period"] = request.remapping_period
    for key, value in (request.additional_parameters or {}).items():
        if value is None:
            continue
        parameters[str(key)] = value

    feature = {
        "type": "Feature",
        "geometry": request.geometry,
        "properties": {
            "order_name": request.order_name.strip(),
            "sku": request.sku.strip(),
            "parameters": parameters,
        },
    }
    project_name = (request.project_name or "").strip()
    if project_name:
        feature["properties"]["project_name"] = project_name

    try:
        created = client.create_order(feature, contract_id=request.contract_id)
        rows = _tasking_rows_from_payload(created)
        if rows:
            normalized = [_normalize_tasking_order(row) for row in rows]
            return {
                "accepted": bool(normalized),
                "count": len(normalized),
                "order": normalized[0],
                "orders": normalized,
                "raw": created,
            }
        return {"accepted": True, "order": _normalize_tasking_order(created), "raw": created}
    except requests.HTTPError as exc:
        status_code = int(getattr(getattr(exc, "response", None), "status_code", 502) or 502)
        detail = (getattr(getattr(exc, "response", None), "text", "") or str(exc)).strip()
        raise HTTPException(status_code=status_code, detail=f"Tasking create failed: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Tasking create failed: {exc}") from exc


@app.post("/api/download/zip")
def download_zip(request: DownloadBundleRequest):
    try:
        assets = request.assets or []
        if not assets:
            raise HTTPException(status_code=400, detail="No assets supplied for download")
        if len(assets) > 500:
            raise HTTPException(status_code=400, detail="Too many assets requested (max 500)")

        used_names: set[str] = set()
        downloaded_count = 0
        failed_rows: list[str] = []
        payload = BytesIO()

        with zipfile.ZipFile(payload, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for idx, asset in enumerate(assets, start=1):
                url = (asset.url or "").strip()
                if not url:
                    continue
                default_stem = asset.item_id or asset.outcome_id or f"asset_{idx:03d}"
                preferred_name = (asset.filename or "").strip()
                raw_name = preferred_name or _filename_from_url(url, default_stem=default_stem)
                safe_name = _safe_filename(raw_name, fallback=f"{default_stem}.bin")
                filename = _dedupe_name(safe_name, used_names)

                try:
                    content = _download_bytes_for_url(url, contract_id=request.contract_id)
                    zf.writestr(filename, content)
                    downloaded_count += 1
                except Exception as exc:
                    failed_rows.append(f"{filename},{str(exc).replace(',', ';')}")

            if failed_rows:
                failure_csv = "filename,error\n" + "\n".join(failed_rows) + "\n"
                zf.writestr("_failed_downloads.csv", failure_csv.encode("utf-8"))

        if downloaded_count == 0:
            raise HTTPException(status_code=400, detail="No assets were downloaded successfully")

        bundle = _safe_filename(request.bundle_name or "tiles_download", fallback="tiles_download")
        if not bundle.endswith(".zip"):
            bundle = f"{bundle}.zip"

        payload.seek(0)
        return Response(
            content=payload.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{bundle}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"ZIP download failed: {exc}") from exc


@app.get("/api/assets/proxy")
def asset_proxy(
    url: str = Query(...),
    contract_id: str | None = Query(default=None),
    source_hint: str | None = Query(default=None),
    render: bool = Query(default=False),
):
    try:
        started = time.perf_counter()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            logger.warning(
                "asset_proxy reject invalid_scheme source_hint=%s scheme=%s url=%s",
                source_hint or "",
                parsed.scheme or "",
                _asset_short(url),
            )
            raise HTTPException(status_code=400, detail="Asset URL must use http/https")
        if not parsed.netloc:
            logger.warning(
                "asset_proxy reject invalid_host source_hint=%s url=%s",
                source_hint or "",
                _asset_short(url),
            )
            raise HTTPException(status_code=400, detail="Asset URL host is invalid")

        cache_key = _asset_cache_key(url, contract_id, render)
        cache_entry = app.state.asset_cache.get(cache_key)
        now = time.time()
        if cache_entry and cache_entry["expires_at"] > now:
            app.state.asset_cache_stats["hits"] += 1
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "asset_proxy kind=%s cache=hit render=%s bytes=%s ms=%s url=%s",
                _asset_kind(url),
                int(render),
                len(cache_entry["content"]),
                elapsed_ms,
                _asset_short(url),
            )
            total = app.state.asset_cache_stats["hits"] + app.state.asset_cache_stats["misses"]
            if total % 25 == 0:
                logger.info(
                    "asset_proxy stats hits=%s misses=%s entries=%s",
                    app.state.asset_cache_stats["hits"],
                    app.state.asset_cache_stats["misses"],
                    len(app.state.asset_cache),
                )
            return Response(
                content=cache_entry["content"],
                media_type=cache_entry["media_type"],
                headers={"Cache-Control": f"public, max-age={int(settings.proxy_cache_ttl_seconds)}", "X-Proxy-Cache": "hit"},
            )
        if cache_entry:
            app.state.asset_cache.pop(cache_key, None)

        app.state.asset_cache_stats["misses"] += 1
        headers = sources.auth_headers_for_url(url, contract_id=contract_id, source_hint=source_hint)
        upstream = requests.get(url, headers=headers, timeout=120)
        if upstream.status_code == 401:
            inferred_source = sources.infer_source_id_from_url(url, source_hint=source_hint)
            if inferred_source == SOURCE_MERLIN_S2:
                try:
                    prefer_download = not merlin_client._requires_download_token_for_url(url)
                    retry_headers = merlin_client.auth_headers(download=prefer_download)
                    if retry_headers != headers:
                        retried = requests.get(url, headers=retry_headers, timeout=120)
                        retry_mode = "download" if prefer_download else "client_credentials"
                        if retried.status_code < 400:
                            logger.info(
                                "asset_proxy merlin_retry ok mode=%s status=%s url=%s",
                                retry_mode,
                                retried.status_code,
                                _asset_short(url),
                            )
                            upstream = retried
                        else:
                            logger.warning(
                                "asset_proxy merlin_retry failed mode=%s status=%s url=%s",
                                retry_mode,
                                retried.status_code,
                                _asset_short(url),
                            )
                except Exception as retry_exc:
                    logger.warning("asset_proxy merlin_retry error=%s url=%s", retry_exc, _asset_short(url))
        if upstream.status_code >= 400:
            logger.warning(
                "asset_proxy upstream_error source_hint=%s status=%s url=%s",
                source_hint or "",
                upstream.status_code,
                _asset_short(url),
            )
            raise HTTPException(
                status_code=upstream.status_code,
                detail=f"Asset fetch failed upstream: {upstream.status_code}",
            )

        media_type = upstream.headers.get("Content-Type", "application/octet-stream")
        content = upstream.content

        is_tiff = (
            "tif" in media_type.lower()
            or parsed.path.lower().endswith(".tif")
            or parsed.path.lower().endswith(".tiff")
            or ".tif" in url.lower()
        )
        if render and is_tiff:
            try:
                with Image.open(BytesIO(content)) as img:
                    rgb = img.convert("RGB")
                    max_side = 2048
                    if max(rgb.size) > max_side:
                        rgb.thumbnail((max_side, max_side))
                    buf = BytesIO()
                    rgb.save(buf, format="PNG")
                    content = buf.getvalue()
                    media_type = "image/png"
            except Exception:
                pass

        # Cache moderate-size image responses for repeated map redraws.
        if len(content) <= 8_000_000:
            app.state.asset_cache[cache_key] = {
                "content": content,
                "media_type": media_type,
                "expires_at": now + int(settings.proxy_cache_ttl_seconds),
            }
            _prune_asset_cache()

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "asset_proxy kind=%s cache=miss render=%s bytes=%s ms=%s url=%s",
            _asset_kind(url),
            int(render),
            len(content),
            elapsed_ms,
            _asset_short(url),
        )
        total = app.state.asset_cache_stats["hits"] + app.state.asset_cache_stats["misses"]
        if total % 25 == 0:
            logger.info(
                "asset_proxy stats hits=%s misses=%s entries=%s",
                app.state.asset_cache_stats["hits"],
                app.state.asset_cache_stats["misses"],
                len(app.state.asset_cache),
            )

        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": f"public, max-age={int(settings.proxy_cache_ttl_seconds)}", "X-Proxy-Cache": "miss"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Asset proxy failed: {exc}") from exc


_RENDER_LAYERS = {"raw", "natural", "false_color", "ndvi", "cloud_mask"}


def _cog_upstream_request(
    *,
    z: int,
    x: int,
    y: int,
    source_url: str,
    contract_id: str | None,
    scale: int,
    buffer: int,
    tile_matrix_set_id: str,
    image_format: str,
    bidx: list[int],
) -> tuple[requests.Response, str]:
    upstream_url = f"https://api.satellogic.com/raster/cog/tiles/{z}/{x}/{y}"
    params: list[tuple[str, str]] = [
        ("scale", str(scale)),
        ("buffer", str(max(0, buffer))),
        ("tileMatrixSetId", tile_matrix_set_id),
        ("url", source_url),
        ("format", image_format),
    ]
    for band in bidx:
        params.append(("bidx", str(band)))

    auth_mode = "oauth_client_credentials"
    effective_contract_id = _resolve_tile_contract_id(contract_id)
    request_headers = client.auth_headers(
        contract_id=effective_contract_id,
        prefer_oauth=True,
        ignore_static_bearer=True,
    )
    auth_header = (request_headers.get("authorizationToken") or "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=503, detail="OAuth client-credentials token is unavailable")

    def _request_with_retry(headers: dict[str, str]) -> requests.Response:
        response = requests.get(
            upstream_url,
            headers=headers,
            params=params,
            timeout=90,
        )
        if response.status_code == 400 and buffer > 0:
            retry_params = [entry for entry in params if entry[0] != "buffer"]
            response = requests.get(
                upstream_url,
                headers=headers,
                params=retry_params,
                timeout=90,
            )
        return response

    upstream = _request_with_retry(request_headers)
    if upstream.status_code == 401 and not str(contract_id or "").strip():
        detail = str(upstream.text or "").lower()
        if "contract" in detail:
            refreshed_contract_id = _resolve_tile_contract_id(None, force_refresh=True)
            if refreshed_contract_id and refreshed_contract_id != effective_contract_id:
                logger.info(
                    "tile_proxy retrying request after contract refresh old=%s new=%s zxy=%s/%s/%s",
                    _short_contract_id(effective_contract_id),
                    _short_contract_id(refreshed_contract_id),
                    z,
                    x,
                    y,
                )
                request_headers = client.auth_headers(
                    contract_id=refreshed_contract_id,
                    prefer_oauth=True,
                    ignore_static_bearer=True,
                )
                upstream = _request_with_retry(request_headers)
    return upstream, auth_mode


def _as_luma_png(content: bytes) -> Image.Image:
    with Image.open(BytesIO(content)) as img:
        return img.convert("L")


def _as_rgba_png(content: bytes) -> Image.Image:
    with Image.open(BytesIO(content)) as img:
        return img.convert("RGBA")


def _png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _compose_rgb_from_luma(red_l: Image.Image, green_l: Image.Image, blue_l: Image.Image) -> Image.Image:
    return Image.merge("RGB", (red_l.convert("L"), green_l.convert("L"), blue_l.convert("L"))).convert("RGBA")


def _cloud_presence_mask(mask_l: Image.Image) -> Image.Image:
    lo, hi = mask_l.getextrema()
    if hi <= 1:
        threshold = 1
    elif hi <= 100:
        threshold = 50
    elif hi <= 200:
        threshold = 100
    else:
        threshold = 160
    return mask_l.point(lambda v: 255 if v >= threshold else 0, mode="L")


def _apply_cloud_alpha(base_rgba: Image.Image, mask_l: Image.Image) -> Image.Image:
    out = base_rgba.copy().convert("RGBA")
    cloud = _cloud_presence_mask(mask_l)
    clear_alpha = cloud.point(lambda v: 0 if v > 0 else 255, mode="L")
    out.putalpha(clear_alpha)
    return out


def _render_cloud_mask_rgba(mask_l: Image.Image) -> Image.Image:
    cloud = _cloud_presence_mask(mask_l)
    alpha = cloud.point(lambda v: 185 if v > 0 else 0, mode="L")
    out = Image.new("RGBA", mask_l.size, (255, 255, 255, 0))
    out.putalpha(alpha)
    return out


def _render_ndvi_rgba(red_l: Image.Image, nir_l: Image.Image, cloud_mask_l: Image.Image | None = None) -> Image.Image:
    red = list(red_l.getdata())
    nir = list(nir_l.getdata())
    cloud = list(_cloud_presence_mask(cloud_mask_l).getdata()) if cloud_mask_l else None
    out = bytearray()

    def ndvi_color(value: float) -> tuple[int, int, int]:
        if value < 0.0:
            return (158, 126, 97)
        if value < 0.15:
            return (189, 171, 112)
        if value < 0.3:
            return (159, 184, 106)
        if value < 0.45:
            return (120, 171, 92)
        if value < 0.6:
            return (72, 145, 74)
        return (34, 112, 58)

    for idx, (r, n) in enumerate(zip(red, nir)):
        denom = int(n) + int(r)
        ndvi = (float(n) - float(r)) / float(denom) if denom > 0 else -1.0
        rgb = ndvi_color(ndvi)
        alpha = 255
        if cloud and cloud[idx] > 0:
            alpha = 0
        out.extend((rgb[0], rgb[1], rgb[2], alpha))
    return Image.frombytes("RGBA", red_l.size, bytes(out))


def _render_thematic_tile(
    *,
    z: int,
    x: int,
    y: int,
    source_url: str,
    cloud_mask_url: str | None,
    contract_id: str | None,
    scale: int,
    buffer: int,
    tile_matrix_set_id: str,
    render_layer: str,
) -> tuple[bytes, str]:
    def fetch_natural_rgba() -> tuple[Image.Image | None, str]:
        upstream, auth_mode = _cog_upstream_request(
            z=z,
            x=x,
            y=y,
            source_url=source_url,
            contract_id=contract_id,
            scale=scale,
            buffer=buffer,
            tile_matrix_set_id=tile_matrix_set_id,
            image_format="png",
            bidx=[1, 2, 3],
        )
        if upstream.status_code == 404:
            return None, auth_mode
        if upstream.status_code >= 400:
            detail = (upstream.text or "").strip().replace("\n", " ")[:220]
            raise HTTPException(status_code=upstream.status_code, detail=f"Natural tile failed upstream: {detail or upstream.status_code}")
        return _as_rgba_png(upstream.content), auth_mode

    def fetch_band_luma(band: int) -> tuple[Image.Image | None, str]:
        upstream, auth_mode = _cog_upstream_request(
            z=z,
            x=x,
            y=y,
            source_url=source_url,
            contract_id=contract_id,
            scale=scale,
            buffer=buffer,
            tile_matrix_set_id=tile_matrix_set_id,
            image_format="png",
            bidx=[band],
        )
        if upstream.status_code == 404:
            return None, auth_mode
        if upstream.status_code >= 400:
            detail = (upstream.text or "").strip().replace("\n", " ")[:220]
            raise HTTPException(status_code=upstream.status_code, detail=f"Band {band} fetch failed upstream: {detail or upstream.status_code}")
        return _as_luma_png(upstream.content), auth_mode

    if render_layer == "cloud_mask":
        mask_source = cloud_mask_url or source_url
        upstream, auth_mode = _cog_upstream_request(
            z=z,
            x=x,
            y=y,
            source_url=mask_source,
            contract_id=contract_id,
            scale=scale,
            buffer=buffer,
            tile_matrix_set_id=tile_matrix_set_id,
            image_format="png",
            bidx=[1],
        )
        if upstream.status_code == 404:
            return TRANSPARENT_PNG_1X1, auth_mode
        if upstream.status_code >= 400:
            detail = (upstream.text or "").strip().replace("\n", " ")[:220]
            raise HTTPException(status_code=upstream.status_code, detail=f"Cloud-mask tile failed upstream: {detail or upstream.status_code}")
        mask = _as_luma_png(upstream.content)
        return _png_bytes(_render_cloud_mask_rgba(mask)), auth_mode

    if render_layer == "ndvi":
        red_l, auth_mode = fetch_band_luma(3)
        if red_l is None:
            return TRANSPARENT_PNG_1X1, auth_mode
        nir_l, _ = fetch_band_luma(4)
        if nir_l is None:
            return TRANSPARENT_PNG_1X1, auth_mode

        cloud_mask = None
        if cloud_mask_url:
            mask_upstream, _ = _cog_upstream_request(
                z=z,
                x=x,
                y=y,
                source_url=cloud_mask_url,
                contract_id=contract_id,
                scale=scale,
                buffer=buffer,
                tile_matrix_set_id=tile_matrix_set_id,
                image_format="png",
                bidx=[1],
            )
            if mask_upstream.status_code < 400:
                cloud_mask = _as_luma_png(mask_upstream.content)

        return _png_bytes(_render_ndvi_rgba(red_l, nir_l, cloud_mask)), auth_mode

    if render_layer == "natural":
        base, auth_mode = fetch_natural_rgba()
        if base is None:
            return TRANSPARENT_PNG_1X1, auth_mode
    else:
        bands = (4, 1, 2)
        try:
            red_l, auth_mode = fetch_band_luma(bands[0])
            if red_l is None:
                return TRANSPARENT_PNG_1X1, auth_mode
            green_l, _ = fetch_band_luma(bands[1])
            if green_l is None:
                return TRANSPARENT_PNG_1X1, auth_mode
            blue_l, _ = fetch_band_luma(bands[2])
            if blue_l is None:
                return TRANSPARENT_PNG_1X1, auth_mode
            base = _compose_rgb_from_luma(red_l, green_l, blue_l)
        except HTTPException as exc:
            if exc.status_code not in {400, 404}:
                raise
            logger.info(
                "tile_proxy false_color fallback_to_natural zxy=%s/%s/%s reason=%s",
                z,
                x,
                y,
                exc.status_code,
            )
            base, auth_mode = fetch_natural_rgba()
            if base is None:
                return TRANSPARENT_PNG_1X1, auth_mode
    if cloud_mask_url:
        mask_upstream, _ = _cog_upstream_request(
            z=z,
            x=x,
            y=y,
            source_url=cloud_mask_url,
            contract_id=contract_id,
            scale=scale,
            buffer=buffer,
            tile_matrix_set_id=tile_matrix_set_id,
            image_format="png",
            bidx=[1],
        )
        if mask_upstream.status_code < 400:
            base = _apply_cloud_alpha(base, _as_luma_png(mask_upstream.content))
    return _png_bytes(base), auth_mode


@app.get("/api/raster/cog/tiles/{z}/{x}/{y}")
def raster_cog_tile_proxy(
    request: Request,
    z: int,
    x: int,
    y: int,
    url: str = Query(..., alias="url"),
    contract_id: str | None = Query(default=None),
    scale: int = Query(default=1),
    buffer: int = Query(default=1),
    tileMatrixSetId: str = Query(default="WebMercatorQuad"),
    format: str = Query(default="png"),
    bidx: list[int] = Query(default=[1, 2, 3]),
    render_layer: str = Query(default="raw"),
    cloud_mask_url: str | None = Query(default=None),
):
    try:
        query_keys = set(request.query_params.keys())
        extracted_url, embedded_options = _extract_embedded_tile_options(url)
        if embedded_options:
            url = extracted_url
            if "contract_id" not in query_keys:
                contract_values = embedded_options.get("contract_id") or []
                if contract_values:
                    contract_id = contract_values[0]
            if "scale" not in query_keys:
                scale_values = embedded_options.get("scale") or []
                if scale_values:
                    try:
                        scale = max(1, int(scale_values[0]))
                    except Exception:
                        pass
            if "buffer" not in query_keys:
                buffer_values = embedded_options.get("buffer") or []
                if buffer_values:
                    try:
                        buffer = max(0, int(buffer_values[0]))
                    except Exception:
                        pass
            if "tileMatrixSetId" not in query_keys:
                tile_values = embedded_options.get("tileMatrixSetId") or []
                if tile_values:
                    tileMatrixSetId = tile_values[0]
            if "format" not in query_keys:
                format_values = embedded_options.get("format") or []
                if format_values:
                    format = format_values[0]
            if "render_layer" not in query_keys:
                layer_values = embedded_options.get("render_layer") or []
                if layer_values:
                    render_layer = layer_values[0]
            if "cloud_mask_url" not in query_keys:
                mask_values = embedded_options.get("cloud_mask_url") or []
                if mask_values:
                    cloud_mask_url = mask_values[0]
            if "bidx" not in query_keys:
                band_values = embedded_options.get("bidx") or []
                parsed_bidx: list[int] = []
                for raw in band_values:
                    try:
                        parsed_bidx.append(int(raw))
                    except Exception:
                        continue
                if parsed_bidx:
                    bidx = parsed_bidx
            logger.info(
                "tile_proxy decoded_embedded_query zxy=%s/%s/%s keys=%s",
                z,
                x,
                y,
                ",".join(sorted(embedded_options.keys())),
            )

        if z < 0 or x < 0 or y < 0:
            raise HTTPException(status_code=400, detail="Invalid tile coordinates")
        parsed = urlparse(url)
        if not parsed.scheme:
            raise HTTPException(status_code=400, detail="COG source URL must include scheme")
        if parsed.scheme not in ("s3", "http", "https"):
            raise HTTPException(status_code=400, detail="COG source scheme not supported")
        if cloud_mask_url:
            parsed_mask = urlparse(cloud_mask_url)
            if not parsed_mask.scheme:
                raise HTTPException(status_code=400, detail="Cloud mask URL must include scheme")
            if parsed_mask.scheme not in ("s3", "http", "https"):
                raise HTTPException(status_code=400, detail="Cloud mask URL scheme not supported")

        layer = (render_layer or "raw").strip().lower()
        if layer not in _RENDER_LAYERS:
            raise HTTPException(status_code=400, detail=f"Unsupported render_layer '{render_layer}'")

        started = time.perf_counter()
        cache_key = _tile_cache_key(
            z=z,
            x=x,
            y=y,
            source_url=url,
            contract_id=contract_id,
            scale=scale,
            buffer=buffer,
            tile_matrix_set_id=tileMatrixSetId,
            image_format=format,
            bidx=bidx,
            render_layer=layer,
            cloud_mask_url=cloud_mask_url,
        )
        cache_entry = app.state.asset_cache.get(cache_key)
        now = time.time()
        if cache_entry and cache_entry["expires_at"] > now:
            app.state.tile_cache_stats["hits"] += 1
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            _record_tile_delivery("newsat", len(cache_entry["content"]), elapsed_ms)
            logger.info(
                "tile_proxy cache=hit zxy=%s/%s/%s bytes=%s ms=%s",
                z,
                x,
                y,
                len(cache_entry["content"]),
                elapsed_ms,
            )
            return Response(
                content=cache_entry["content"],
                media_type=cache_entry["media_type"],
                headers={"Cache-Control": f"public, max-age={int(settings.proxy_cache_ttl_seconds)}", "X-Proxy-Cache": "hit"},
            )
        if cache_entry:
            app.state.asset_cache.pop(cache_key, None)

        app.state.tile_cache_stats["misses"] += 1
        media_type = "image/png"
        if layer == "raw":
            upstream, auth_mode = _cog_upstream_request(
                z=z,
                x=x,
                y=y,
                source_url=url,
                contract_id=contract_id,
                scale=scale,
                buffer=buffer,
                tile_matrix_set_id=tileMatrixSetId,
                image_format=format,
                bidx=bidx,
            )
            if upstream.status_code >= 400:
                upstream_status = int(upstream.status_code)
                tile_size = 256 * max(1, int(scale or 1))
                empty_tile = _transparent_png_tile(tile_size)
                fallback_ttl = 60 if upstream_status == 404 else 20
                fallback_ttl = min(fallback_ttl, int(settings.proxy_empty_tile_ttl_seconds))
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                app.state.asset_cache[cache_key] = {
                    "content": empty_tile,
                    "media_type": "image/png",
                    "expires_at": now + fallback_ttl,
                }
                _prune_asset_cache()
                is_error = upstream_status != 404
                _record_tile_delivery("newsat", len(empty_tile), elapsed_ms, error=is_error)
                detail = (upstream.text or "").strip().replace("\n", " ")[:220]
                if upstream_status == 404:
                    logger.info("tile_proxy empty zxy=%s/%s/%s ms=%s", z, x, y, elapsed_ms)
                else:
                    logger.warning(
                        "tile_proxy upstream_error auth=%s zxy=%s/%s/%s status=%s detail=%s fallback=empty_png",
                        auth_mode,
                        z,
                        x,
                        y,
                        upstream_status,
                        detail,
                    )
                return Response(
                    content=empty_tile,
                    media_type="image/png",
                    headers={
                        "Cache-Control": f"public, max-age={fallback_ttl}",
                        "X-Proxy-Cache": "miss",
                        "X-Tile-Empty": "1",
                        "X-Tile-Size": str(tile_size),
                        "X-Upstream-Status": str(upstream_status),
                    },
                )

            media_type = upstream.headers.get("Content-Type", "image/png")
            content = upstream.content
        else:
            content, auth_mode = _render_thematic_tile(
                z=z,
                x=x,
                y=y,
                source_url=url,
                cloud_mask_url=cloud_mask_url,
                contract_id=contract_id,
                scale=scale,
                buffer=buffer,
                tile_matrix_set_id=tileMatrixSetId,
                render_layer=layer,
            )

        if len(content) <= 2_000_000:
            app.state.asset_cache[cache_key] = {
                "content": content,
                "media_type": media_type,
                "expires_at": now + int(settings.proxy_cache_ttl_seconds),
            }
            _prune_asset_cache()

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _record_tile_delivery("newsat", len(content), elapsed_ms)
        logger.info(
            "tile_proxy cache=miss auth=%s layer=%s zxy=%s/%s/%s bytes=%s ms=%s",
            auth_mode,
            layer,
            z,
            x,
            y,
            len(content),
            elapsed_ms,
        )
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": f"public, max-age={int(settings.proxy_cache_ttl_seconds)}", "X-Proxy-Cache": "miss"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Tile proxy failed: {exc}") from exc


def _cache_items(items: list[dict[str, Any]]):
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            continue
        app.state.item_cache[item_id] = item


def _resolve_item(
    item_id: str,
    contract_id: str | None = None,
    source_id: str | None = None,
    collection_id: str | None = None,
) -> dict[str, Any] | None:
    cached = app.state.item_cache.get(item_id)
    if cached:
        return cached

    source, native_item_id = _source_from_item_id(item_id, source_hint=source_id)
    item = sources.item_by_id(
        native_item_id,
        source_id=source,
        contract_id=contract_id,
        collection_id=collection_id,
    )
    if not item and collection_id:
        # Some providers/collections return incomplete results for strict collection + id lookups.
        # Retry once without collection pinning to reduce false 404s on previously-discovered ids.
        item = sources.item_by_id(
            native_item_id,
            source_id=source,
            contract_id=contract_id,
            collection_id=None,
        )
        if item:
            logger.info(
                "resolve_item fallback_without_collection source=%s item=%s requested_collection=%s resolved_collection=%s",
                source,
                native_item_id,
                collection_id,
                item.get("collection") if isinstance(item, dict) else "",
            )
    if not item:
        return None
    _cache_items([item])
    return item


def _search_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    source_id = _normalize_source_id(payload.get("source_id"))
    collection_id = str(payload.get("collection_id") or "").strip()
    if source_id == SOURCE_MERLIN_S2 and collection_id == settings.satellogic_collection_id:
        collection_id = ""
    if not collection_id:
        collection_id = settings.cdse_sentinel2_collections[0] if source_id == SOURCE_MERLIN_S2 and settings.cdse_sentinel2_collections else settings.satellogic_collection_id

    items = sources.search(
        source_id=source_id,
        geometry=payload.get("geometry"),
        start_date=payload.get("start_date"),
        end_date=payload.get("end_date"),
        collection_id=collection_id,
        contract_id=payload.get("contract_id"),
        limit=int(payload.get("limit") or 300),
        max_cloud_cover=payload.get("max_cloud_cover"),
        satellite_name=payload.get("satellite_name"),
        min_gsd=payload.get("min_gsd"),
        max_gsd=payload.get("max_gsd"),
    )
    _cache_items(items)
    return items


def _workbench_search_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _search_items(payload)


def _ensure_workbench() -> GeoWorkbenchEngine:
    existing = app.state.workbench
    if existing:
        return existing
    with app.state.workbench_lock:
        existing = app.state.workbench
        if existing:
            return existing
        engine = GeoWorkbenchEngine(
            root_dir=settings.output_dir,
            search_items_fn=_workbench_search_items,
            resolve_item_fn=_resolve_item,
            download_bytes_fn=lambda url, contract_id=None: _download_bytes_for_url(url, contract_id=contract_id),
        )
        engine.start()
        app.state.workbench = engine
        return engine


@app.post("/api/archive/search", response_model=SearchResponse)
def archive_search(request: SearchRequest):
    try:
        started = time.perf_counter()
        source_id = _normalize_source_id(request.source_id)
        collection_id = request.collection_id
        if source_id == SOURCE_MERLIN_S2 and collection_id == settings.satellogic_collection_id:
            collection_id = settings.cdse_sentinel2_collections[0] if settings.cdse_sentinel2_collections else "sentinel-2-l2a"
        items = _search_items(
            {
                "source_id": source_id,
                "geometry": request.geometry,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "collection_id": collection_id,
                "contract_id": request.contract_id,
                "limit": request.limit,
                "max_cloud_cover": request.max_cloud_cover,
                "satellite_name": request.satellite_name,
                "min_gsd": request.min_gsd,
                "max_gsd": request.max_gsd,
            }
        )

        typed_items = [
            SearchResultItem(
                id=item["id"],
                source_id=item.get("source_id") or source_id,
                collection=item.get("collection"),
                datetime=item.get("datetime"),
                outcome_id=item.get("outcome_id"),
                satellite_name=item.get("satellite_name"),
                gsd=item.get("gsd"),
                cloud_cover=item.get("cloud_cover"),
                valid_pixel_percent=item.get("valid_pixel_percent"),
                geometry=item.get("geometry"),
                assets=item.get("assets"),
            )
            for item in items
        ]
        if source_id == SOURCE_MERLIN_S2 and items:
            first = items[0] or {}
            first_assets = first.get("assets") or {}
            first_raw_assets = ((first.get("raw") or {}).get("assets") or {})
            logger.info(
                "merlin_asset_selection item=%s raw_keys=%s selected_visual=%s selected_visual_fullres=%s selected_preview=%s",
                first.get("id") or "",
                ",".join(sorted(str(k) for k in first_raw_assets.keys()))[:1000],
                _asset_short(first_assets.get("visual") or ""),
                _asset_short(first_assets.get("visual_fullres") or ""),
                _asset_short(first_assets.get("preview") or ""),
            )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "archive_search source=%s collection=%s count=%s limit=%s ms=%s cloud=%s sat=%s gsd=[%s,%s]",
            source_id,
            collection_id,
            len(typed_items),
            request.limit,
            elapsed_ms,
            request.max_cloud_cover,
            request.satellite_name or "",
            request.min_gsd,
            request.max_gsd,
        )
        search_stats = app.state.archive_search_stats
        search_stats["total"] = int(search_stats.get("total", 0)) + 1
        by_collection = search_stats.setdefault("by_collection", {})
        if source_id == SOURCE_SATELLOGIC:
            collection_key = collection_id or "unknown"
        else:
            collection_key = f"{source_id}:{collection_id or 'unknown'}"
        by_collection[collection_key] = int(by_collection.get(collection_key, 0)) + 1
        return SearchResponse(count=len(typed_items), items=typed_items)
    except Exception as exc:
        logger.exception(
            "archive_search failed source=%s collection=%s contract=%s error=%s",
            request.source_id,
            request.collection_id,
            request.contract_id or "",
            exc,
        )
        raise HTTPException(status_code=400, detail=f"Archive search failed: {exc}") from exc


@app.get("/api/archive/item-assets")
def archive_item_assets(
    item_id: str = Query(..., min_length=1),
    source_id: str | None = Query(default=None),
    collection_id: str | None = Query(default=None),
    contract_id: str | None = Query(default=None),
):
    try:
        item = _resolve_item(
            item_id=item_id,
            source_id=source_id,
            contract_id=contract_id,
            collection_id=collection_id,
        )
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        raw = item.get("raw") or {}
        raw_assets = raw.get("assets") if isinstance(raw, dict) else {}
        rows: list[dict[str, Any]] = []
        if isinstance(raw_assets, dict):
            for key, asset in raw_assets.items():
                if isinstance(asset, dict):
                    alt = asset.get("alternate")
                    alt_keys = sorted(str(k) for k in alt.keys()) if isinstance(alt, dict) else []
                    alternates: dict[str, str] = {}
                    if isinstance(alt, dict):
                        for alt_key, alt_row in alt.items():
                            if isinstance(alt_row, dict):
                                alt_href = str(alt_row.get("href") or "").strip()
                                if alt_href:
                                    alternates[str(alt_key)] = alt_href
                    rows.append(
                        {
                            "key": str(key),
                            "href": str(asset.get("href") or ""),
                            "type": str(asset.get("type") or ""),
                            "title": str(asset.get("title") or ""),
                            "roles": [str(r) for r in (asset.get("roles") or []) if str(r)],
                            "alternate_keys": alt_keys,
                            "alternates": alternates,
                        }
                    )
                else:
                    rows.append({"key": str(key), "value_type": type(asset).__name__})
        return {
            "id": item.get("id"),
            "collection": item.get("collection"),
            "source_id": item.get("source_id") or source_id,
            "selected_assets": item.get("assets") or {},
            "raw_asset_count": len(rows),
            "raw_assets": rows,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Item asset inspection failed: {exc}") from exc


@app.post("/api/archive/animate")
def archive_animate(request: AnimationRequest):
    frames = []
    for item_id in request.item_ids[: request.max_frames]:
        item = _resolve_item(item_id, contract_id=request.contract_id)
        if item:
            frames.append(item)

    if len(frames) < 2:
        raise HTTPException(status_code=400, detail="Need at least two valid frames for animation")

    try:
        result = make_animation_gif(
            frames=frames,
            downloader=lambda url: _download_bytes_for_url(url, contract_id=request.contract_id),
            seconds_per_frame=request.seconds_per_frame,
            output_dir=settings.output_dir,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Animation build failed: {exc}") from exc


@app.post("/api/archive/animate/search")
def archive_animate_search(request: AnimationSearchRequest):
    try:
        items: list[dict[str, Any]] = []
        source_id = _normalize_source_id(request.source_id)
        collection_id = request.collection_id
        if source_id == SOURCE_MERLIN_S2 and collection_id == settings.satellogic_collection_id:
            collection_id = settings.cdse_sentinel2_collections[0] if settings.cdse_sentinel2_collections else "sentinel-2-l2a"
        for lim in (1200, 600, 300, 200):
            try:
                items = _search_items(
                    {
                        "source_id": source_id,
                        "geometry": request.geometry,
                        "start_date": request.start_date,
                        "end_date": request.end_date,
                        "collection_id": collection_id,
                        "contract_id": request.contract_id,
                        "limit": lim,
                        "max_cloud_cover": request.max_cloud_cover,
                        "satellite_name": request.satellite_name,
                        "min_gsd": request.min_gsd,
                        "max_gsd": request.max_gsd,
                    }
                )
                break
            except Exception:
                items = []
                continue

        items = [item for item in items if item.get("id")]

        result = make_capture_mosaic_animation(
            items=items,
            downloader=lambda url: _download_bytes_for_url(url, contract_id=request.contract_id),
            seconds_per_frame=request.seconds_per_frame,
            output_dir=settings.output_dir,
            max_frames=request.max_frames,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Search animation failed: {exc}") from exc


@app.post("/api/archive/animate/mp4/jobs")
def archive_animate_mp4_create_job(request: Mp4AnimationJobRequest):
    frames = [frame.model_dump() for frame in request.frames if frame.tiles]
    if len(frames) < 2:
        raise HTTPException(status_code=400, detail="Select at least two images with visible full-resolution tiles")
    if len(frames) > 120:
        raise HTTPException(status_code=400, detail="Too many selected frames (max 120)")

    total_tiles = sum(len(frame.get("tiles", [])) for frame in frames)
    if total_tiles > 2400:
        raise HTTPException(status_code=400, detail="Too many selected tiles (max 2400)")

    frame_sources: set[str] = set()
    for frame in frames:
        for tile in frame.get("tiles", []):
            source_id = _infer_mp4_tile_source_id(tile)
            if source_id:
                frame_sources.add(source_id)
    if len(frame_sources) > 1:
        readable = ", ".join(sorted(frame_sources))
        raise HTTPException(
            status_code=400,
            detail=f"MP4 animation requires a single source per run; mixed sources detected: {readable}",
        )

    job_id = str(uuid.uuid4())
    created_at = _utc_now_iso()
    job = {
        "job_id": job_id,
        "status": "queued",
        "created_at": created_at,
        "updated_at": created_at,
        "started_at": None,
        "finished_at": None,
        "progress_current": 0,
        "progress_total": len(frames),
        "frame_count": 0,
        "message": "Queued for background render",
        "error": None,
        "seconds_per_frame": request.seconds_per_frame,
        "file": None,
        "file_name": None,
        "file_size_bytes": None,
    }

    with app.state.mp4_jobs_lock:
        app.state.mp4_jobs[job_id] = job
    _prune_mp4_jobs()
    logger.info(
        "mp4 animation job queued job_id=%s frames=%s total_tiles=%s seconds_per_frame=%.3f contract_id=%s source_scope=%s",
        job_id,
        len(frames),
        total_tiles,
        float(request.seconds_per_frame),
        request.contract_id or "",
        ",".join(sorted(frame_sources)) if frame_sources else "unknown",
    )

    payload = {
        "frames": frames,
        "viewport_geometry": request.viewport_geometry,
        "contract_id": request.contract_id,
        "seconds_per_frame": request.seconds_per_frame,
        "filename_prefix": request.filename_prefix,
    }
    worker = threading.Thread(target=_run_mp4_animation_job, args=(job_id, payload), daemon=True)
    worker.start()

    return _mp4_job_public(job)


@app.get("/api/archive/animate/mp4/jobs/{job_id}")
def archive_animate_mp4_job_status(job_id: str):
    with app.state.mp4_jobs_lock:
        job = app.state.mp4_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="MP4 animation job not found")
    return _mp4_job_public(job)


@app.get("/api/archive/animate/mp4/jobs/{job_id}/download")
def archive_animate_mp4_job_download(job_id: str):
    with app.state.mp4_jobs_lock:
        job = app.state.mp4_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="MP4 animation job not found")

    status = job.get("status")
    if status != "completed":
        raise HTTPException(status_code=409, detail=f"MP4 job is not ready (status={status})")

    raw_file = job.get("file")
    if not raw_file:
        raise HTTPException(status_code=410, detail="MP4 output file is unavailable")

    output_path = Path(raw_file).resolve()
    output_root = settings.output_dir.resolve()
    if output_root not in output_path.parents and output_path != output_root:
        raise HTTPException(status_code=400, detail="Invalid job output path")
    if not output_path.exists():
        raise HTTPException(status_code=410, detail="MP4 output file no longer exists")

    filename = job.get("file_name") or output_path.name
    return FileResponse(path=output_path, media_type="video/mp4", filename=filename)


@app.post("/api/geoagent/report", response_model=GeoAgentResponse)
def geoagent_report(request: GeoAgentRequest):
    try:
        source_id = _normalize_source_id(request.source_id)
        collection_id = request.collection_id
        if source_id == SOURCE_MERLIN_S2 and collection_id == settings.satellogic_collection_id:
            collection_id = settings.cdse_sentinel2_collections[0] if settings.cdse_sentinel2_collections else "sentinel-2-l2a"
        items = _search_items(
            {
                "source_id": source_id,
                "geometry": request.geometry,
                "start_date": request.start_date,
                "end_date": request.end_date,
                "collection_id": collection_id,
                "contract_id": request.contract_id,
                "limit": 300,
                "max_cloud_cover": 80,
                "satellite_name": request.satellite_name,
                "min_gsd": request.min_gsd,
                "max_gsd": request.max_gsd,
            }
        )
        items = [item for item in items if item.get("id")]

        if not items:
            raise HTTPException(status_code=404, detail="No imagery found for geoagent report")

        sorted_items = sorted(items, key=lambda x: x.get("datetime") or "", reverse=True)
        latest_item = None
        if request.latest_item_id:
            latest_item = next((x for x in sorted_items if x["id"] == request.latest_item_id), None)
        if latest_item is None:
            latest_item = sorted_items[0]

        # Sample frames over time for the narrative context.
        sample_step = max(1, len(sorted_items) // request.max_frames)
        frames = sorted_items[::sample_step][: request.max_frames]
        frames = list(reversed(frames))

        report_markdown, insights = generate_geo_report(
            prompt=request.prompt,
            frames=frames,
            latest_item=latest_item,
            downloader=lambda url: _download_bytes_for_url(url, contract_id=request.contract_id, source_hint=source_id),
        )

        return GeoAgentResponse(
            report_markdown=report_markdown,
            latest_item_id=latest_item.get("id") if latest_item else None,
            frame_count=len(frames),
            insights=insights,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Geoagent report failed: {exc}") from exc


@app.get("/api/runtime")
def runtime_info():
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "auth_mode": getattr(client, "auth_mode", "unknown"),
        "default_source_id": DEFAULT_SOURCE_ID,
        "available_sources": [row.get("source_id") for row in sources.list_sources() if row.get("enabled")],
        "has_satl_credentials": bool(settings.satellogic_key_id and settings.satellogic_key_secret),
        "has_contract_id": bool(settings.satellogic_contract_id),
        "has_bearer_token": bool(settings.satellogic_bearer_token),
        "merlin_s2_enabled": bool(settings.merlin_s2_enabled),
        "has_cdse_credentials": bool(settings.cdse_client_id and settings.cdse_client_secret),
        "has_openai_key": bool(settings.openai_api_key),
        "collection_default": settings.satellogic_collection_id,
    }


@app.post("/api/auth/refresh-token")
def refresh_auth_token(source_id: str | None = Query(default=DEFAULT_SOURCE_ID)):
    try:
        source = _normalize_source_id(source_id)
        if source == SOURCE_MERLIN_S2:
            refreshed, expiry = merlin_client.refresh_access_token()
            mode = "oauth_client_credentials"
        else:
            refreshed, expiry = client.refresh_access_token()
            mode = getattr(client, "auth_mode", "unknown")
        if not refreshed:
            raise HTTPException(status_code=503, detail="Token refresh returned empty token")
        return {
            "refreshed": True,
            "source_id": source,
            "auth_mode": mode,
            "expires_at": expiry.isoformat() if expiry else None,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Token refresh failed: {exc}") from exc


@app.get("/api/workflows")
def workflows_list():
    wb = _ensure_workbench()
    rows = wb.list_workflows()
    return {
        "count": len(rows),
        "workflows": rows,
        "skills": wb.list_skills(),
        "providers": wb.list_providers(),
    }


@app.post("/api/workflows")
def workflows_create_or_update(payload: WorkflowDefinitionPayload):
    wb = _ensure_workbench()
    try:
        row = wb.create_or_update_workflow(payload.model_dump())
        return row
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Workflow create/update failed: {exc}") from exc


@app.post("/api/runs")
def runs_create(payload: RunCreateRequest):
    wb = _ensure_workbench()
    try:
        run = wb.create_run(
            workflow_id=payload.workflow_id,
            workflow_version=payload.workflow_version,
            inputs_payload=payload.inputs_payload,
            trigger_id=payload.trigger_id,
            idempotency_key=payload.idempotency_key,
        )
        return run
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Run create failed: {exc}") from exc


@app.get("/api/runs")
def runs_list(
    limit: int = Query(default=100, ge=1, le=500),
    status: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
):
    wb = _ensure_workbench()
    rows = wb.list_runs(limit=limit, status=status, workflow_id=workflow_id)
    return {"count": len(rows), "runs": rows}


@app.get("/api/runs/{run_id}")
def runs_get(run_id: str):
    wb = _ensure_workbench()
    row = wb.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@app.get("/api/runs/{run_id}/artifacts")
def runs_artifacts(run_id: str):
    wb = _ensure_workbench()
    row = wb.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    artifacts = wb.run_artifacts(run_id)
    return {"count": len(artifacts), "artifacts": artifacts}


@app.get("/api/runs/{run_id}/artifacts/{artifact_id}/download")
def runs_artifact_download(run_id: str, artifact_id: str):
    wb = _ensure_workbench()
    row = wb.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    artifacts = row.get("artifacts") or []
    target = next((a for a in artifacts if a.get("artifact_id") == artifact_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact_path = Path(str(target.get("uri") or "")).resolve()
    workbench_root = (settings.output_dir / "workbench").resolve()
    if workbench_root not in artifact_path.parents:
        raise HTTPException(status_code=400, detail="Invalid artifact path")
    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(status_code=410, detail="Artifact file not found")
    return FileResponse(path=artifact_path, filename=artifact_path.name)


@app.post("/api/schedules")
def schedules_create(payload: ScheduleCreateRequest):
    wb = _ensure_workbench()
    try:
        row = wb.create_schedule(payload.model_dump())
        return row
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Schedule create failed: {exc}") from exc


@app.get("/api/schedules")
def schedules_list():
    wb = _ensure_workbench()
    rows = wb.list_schedules()
    return {"count": len(rows), "schedules": rows}


@app.patch("/api/schedules/{schedule_id}")
def schedules_patch(schedule_id: str, payload: SchedulePatchRequest):
    wb = _ensure_workbench()
    try:
        row = wb.patch_schedule(schedule_id, payload.model_dump(exclude_none=True))
        return row
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Schedule update failed: {exc}") from exc


@app.post("/api/poi_sets")
def poi_sets_create(payload: PoiSetCreateRequest):
    wb = _ensure_workbench()
    try:
        row = wb.create_poi_set(payload.model_dump())
        return row
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"POI set create failed: {exc}") from exc


@app.get("/api/poi_sets")
def poi_sets_list():
    wb = _ensure_workbench()
    rows = wb.list_poi_sets()
    return {"count": len(rows), "poi_sets": rows}


@app.post("/api/subscriptions")
def subscriptions_create(payload: SubscriptionCreateRequest):
    wb = _ensure_workbench()
    try:
        row = wb.create_subscription(payload.model_dump())
        return row
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Subscription create failed: {exc}") from exc


@app.get("/api/subscriptions")
def subscriptions_list():
    wb = _ensure_workbench()
    rows = wb.list_subscriptions()
    return {"count": len(rows), "subscriptions": rows}


@app.get("/api/events")
def events_feed(limit: int = Query(default=100, ge=1, le=1000)):
    wb = _ensure_workbench()
    rows = wb.events[-limit:]
    return {"count": len(rows), "events": rows}


@app.post("/api/monitoring/subscriptions")
def monitoring_subscriptions_create(payload: MonitoringSubscriptionCreateRequest):
    source_id = _normalize_source_id(payload.source_id)
    if source_id == SOURCE_MERLIN_S2 and not settings.merlin_s2_enabled:
        raise HTTPException(status_code=400, detail="Merlin Sentinel-2 source is disabled")
    if not sources.has_source(source_id):
        raise HTTPException(status_code=400, detail=f"Unknown source_id '{payload.source_id}'")
    try:
        row = app.state.monitoring_store.create_subscription(
            {
                "source_id": source_id,
                "name": payload.name,
                "collection_ids": payload.collection_ids,
                "geometry": payload.geometry,
                "filters": payload.filters,
                "enabled": payload.enabled,
                "external_subscription_id": payload.external_subscription_id,
                "cursor": payload.cursor,
            }
        )
        return row
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Monitoring subscription create failed: {exc}") from exc


@app.get("/api/monitoring/subscriptions")
def monitoring_subscriptions_list():
    rows = app.state.monitoring_store.list_subscriptions()
    return {"count": len(rows), "subscriptions": rows}


@app.post("/api/monitoring/events")
def monitoring_events_create(payload: MonitoringEventCreateRequest):
    source_id = _normalize_source_id(payload.source_id)
    if not sources.has_source(source_id):
        raise HTTPException(status_code=400, detail=f"Unknown source_id '{payload.source_id}'")
    try:
        row = app.state.monitoring_store.create_event(
            {
                "subscription_id": payload.subscription_id,
                "source_id": source_id,
                "scene_id": payload.scene_id,
                "event_type": payload.event_type,
                "status": payload.status,
                "payload": payload.payload,
            }
        )
        return row
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Monitoring event create failed: {exc}") from exc


@app.get("/api/monitoring/events")
def monitoring_events_list(
    limit: int = Query(default=100, ge=1, le=1000),
    status: str | None = Query(default=None),
):
    rows = app.state.monitoring_store.list_events(limit=limit, status=status)
    return {"count": len(rows), "events": rows}


@app.post("/api/monitoring/events/{event_id}/ack")
def monitoring_events_ack(event_id: str, payload: MonitoringEventAckRequest):
    row = app.state.monitoring_store.ack_event(event_id, status=payload.status)
    if not row:
        raise HTTPException(status_code=404, detail="Monitoring event not found")
    return row


@app.post("/api/cues")
def cues_create(payload: CueCreateRequest):
    source_id = _normalize_source_id(payload.source_id)
    if not sources.has_source(source_id):
        raise HTTPException(status_code=400, detail=f"Unknown source_id '{payload.source_id}'")
    try:
        row = app.state.monitoring_store.create_cue(
            {
                "event_id": payload.event_id,
                "source_id": source_id,
                "status": payload.status,
                "priority": payload.priority,
                "geometry": payload.geometry,
                "payload": payload.payload,
            }
        )
        return row
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cue create failed: {exc}") from exc


@app.get("/api/cues")
def cues_list(
    limit: int = Query(default=100, ge=1, le=1000),
    status: str | None = Query(default=None),
):
    rows = app.state.monitoring_store.list_cues(limit=limit, status=status)
    return {"count": len(rows), "cues": rows}
