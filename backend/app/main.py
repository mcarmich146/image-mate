from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import logging
import time
import base64
import re
import threading
import uuid
import zipfile
from urllib.parse import urlparse
from io import BytesIO

import requests
from PIL import Image

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .geoagent import generate_geo_report
from .models import (
    AnimationSearchRequest,
    AnimationRequest,
    AnnotationRecord,
    CompareRequest,
    DownloadBundleRequest,
    GeoAgentRequest,
    GeoAgentResponse,
    HealthResponse,
    Mp4AnimationJobRequest,
    PoiSetCreateRequest,
    RunCreateRequest,
    ScheduleCreateRequest,
    SchedulePatchRequest,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
    SubscriptionCreateRequest,
    WorkflowDefinitionPayload,
)
from .satellogic_client import SatellogicClient, normalize_item
from .services import (
    build_stacks,
    compare_pair,
    list_annotations,
    make_animation_gif,
    make_capture_mosaic_animation,
    make_selected_extent_mp4,
    save_annotation,
)
from .workbench import GeoWorkbenchEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("image_mate")

app = FastAPI(title="image-mate", version="0.1.0")
client = SatellogicClient()
TRANSPARENT_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)

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
app.state.archive_search_stats = {"total": 0, "by_collection": {}}
app.state.mp4_jobs = {}
app.state.mp4_jobs_lock = threading.Lock()
app.state.workbench = None
app.state.workbench_lock = threading.Lock()


@app.on_event("startup")
def startup_event():
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.annotations_file.parent.mkdir(parents=True, exist_ok=True)
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
            downloader=lambda url: client.download_bytes(url, contract_id=contract_id),
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


def _prune_asset_cache(max_entries: int = 120):
    cache = app.state.asset_cache
    if len(cache) <= max_entries:
        return
    # Remove oldest by insertion order.
    overflow = len(cache) - max_entries
    for key in list(cache.keys())[:overflow]:
        cache.pop(key, None)


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


if settings.frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(settings.frontend_dir), html=True), name="app")


@app.get("/", include_in_schema=False)
def root():
    index = settings.frontend_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"status": "ok", "message": "frontend not found"})


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
        }
    }


@app.get("/api/contracts")
def contracts():
    try:
        raw_contracts = client.list_contracts()
        contracts_list = []
        for record in raw_contracts:
            contract_id = record.get("id") or record.get("contract_id")
            name = record.get("name") or record.get("title") or contract_id
            status = record.get("status")
            if contract_id:
                contracts_list.append({"id": contract_id, "name": name, "status": status, "raw": record})

        default_contract_id = settings.satellogic_contract_id or (contracts_list[0]["id"] if contracts_list else None)
        return {"count": len(contracts_list), "default_contract_id": default_contract_id, "contracts": contracts_list}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Contract discovery failed: {exc}") from exc


@app.get("/api/collections")
def collections(contract_id: str | None = Query(default=None)):
    try:
        raw_collections = client.list_collections(contract_id=contract_id)
        collection_list = []
        for record in raw_collections:
            if not isinstance(record, dict):
                continue
            collection_id = record.get("id")
            if not collection_id:
                continue
            title = record.get("title") or collection_id
            description = record.get("description")
            collection_list.append({
                "id": str(collection_id),
                "title": str(title),
                "description": str(description) if description else None,
            })

        collection_list.sort(key=lambda item: item["id"])
        default_collection_id = settings.satellogic_collection_id or (collection_list[0]["id"] if collection_list else None)
        return {
            "count": len(collection_list),
            "default_collection_id": default_collection_id,
            "collections": collection_list,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Collection discovery failed: {exc}") from exc


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
                    content = client.download_bytes(url, contract_id=request.contract_id)
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
    render: bool = Query(default=False),
):
    try:
        started = time.perf_counter()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise HTTPException(status_code=400, detail="Asset URL must use http/https")
        if not parsed.netloc:
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
                headers={"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "hit"},
            )
        if cache_entry:
            app.state.asset_cache.pop(cache_key, None)

        app.state.asset_cache_stats["misses"] += 1
        upstream = requests.get(url, headers=client.auth_headers(contract_id=contract_id), timeout=120)
        if upstream.status_code >= 400:
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
                "expires_at": now + 300,
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
            headers={"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "miss"},
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
    request_headers = client.auth_headers(
        contract_id=contract_id,
        prefer_oauth=True,
        ignore_static_bearer=True,
    )
    auth_header = (request_headers.get("authorizationToken") or "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=503, detail="OAuth client-credentials token is unavailable")

    upstream = requests.get(
        upstream_url,
        headers=request_headers,
        params=params,
        timeout=90,
    )
    if upstream.status_code == 400 and buffer > 0:
        retry_params = [entry for entry in params if entry[0] != "buffer"]
        upstream = requests.get(
            upstream_url,
            headers=request_headers,
            params=retry_params,
            timeout=90,
        )
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
    z: int,
    x: int,
    y: int,
    url: str = Query(..., alias="url"),
    contract_id: str | None = Query(default=None),
    scale: int = Query(default=2),
    buffer: int = Query(default=0),
    tileMatrixSetId: str = Query(default="WebMercatorQuad"),
    format: str = Query(default="png"),
    bidx: list[int] = Query(default=[1, 2, 3]),
    render_layer: str = Query(default="raw"),
    cloud_mask_url: str | None = Query(default=None),
):
    try:
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
                headers={"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "hit"},
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
            if upstream.status_code == 404:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                logger.info(
                    "tile_proxy empty zxy=%s/%s/%s ms=%s",
                    z,
                    x,
                    y,
                    elapsed_ms,
                )
                return Response(
                    content=TRANSPARENT_PNG_1X1,
                    media_type="image/png",
                    headers={
                        "Cache-Control": "public, max-age=60",
                        "X-Proxy-Cache": "miss",
                        "X-Tile-Empty": "1",
                    },
                )
            if upstream.status_code >= 400:
                detail = (upstream.text or "").strip().replace("\n", " ")[:220]
                logger.warning(
                    "tile_proxy upstream_error auth=%s zxy=%s/%s/%s status=%s detail=%s",
                    auth_mode,
                    z,
                    x,
                    y,
                    upstream.status_code,
                    detail,
                )
                raise HTTPException(status_code=upstream.status_code, detail=f"Tile fetch failed upstream: {upstream.status_code}")

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
                "expires_at": now + 300,
            }
            _prune_asset_cache()

        elapsed_ms = int((time.perf_counter() - started) * 1000)
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
            headers={"Cache-Control": "public, max-age=300", "X-Proxy-Cache": "miss"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Tile proxy failed: {exc}") from exc


def _cache_items(items: list[dict[str, Any]]):
    for item in items:
        app.state.item_cache[item["id"]] = item


def _resolve_item(item_id: str, contract_id: str | None = None) -> dict[str, Any] | None:
    cached = app.state.item_cache.get(item_id)
    if cached:
        return cached

    # STAC item-by-id fallback.
    item = client.item_by_id(item_id, contract_id=contract_id)
    if not item:
        return None
    normalized = normalize_item(item)
    _cache_items([normalized])
    return normalized


def _workbench_search_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features = client.search(
        geometry=payload.get("geometry"),
        start_date=payload.get("start_date"),
        end_date=payload.get("end_date"),
        collection_id=payload.get("collection_id") or "l1d-sr",
        contract_id=payload.get("contract_id"),
        limit=int(payload.get("limit") or 300),
        max_cloud_cover=payload.get("max_cloud_cover"),
        satellite_name=payload.get("satellite_name"),
        min_gsd=payload.get("min_gsd"),
        max_gsd=payload.get("max_gsd"),
    )
    items = [normalize_item(feature) for feature in features]
    _cache_items(items)
    return items


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
        )
        engine.start()
        app.state.workbench = engine
        return engine


@app.post("/api/archive/search", response_model=SearchResponse)
def archive_search(request: SearchRequest):
    try:
        started = time.perf_counter()
        features = client.search(
            geometry=request.geometry,
            start_date=request.start_date,
            end_date=request.end_date,
            collection_id=request.collection_id,
            contract_id=request.contract_id,
            limit=request.limit,
            max_cloud_cover=request.max_cloud_cover,
            satellite_name=request.satellite_name,
            min_gsd=request.min_gsd,
            max_gsd=request.max_gsd,
        )
        items = [normalize_item(feature) for feature in features]
        _cache_items(items)

        typed_items = [
            SearchResultItem(
                id=item["id"],
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
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "archive_search collection=%s count=%s limit=%s ms=%s cloud=%s sat=%s gsd=[%s,%s]",
            request.collection_id,
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
        collection_key = request.collection_id or "unknown"
        by_collection[collection_key] = int(by_collection.get(collection_key, 0)) + 1
        return SearchResponse(count=len(typed_items), items=typed_items)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Archive search failed: {exc}") from exc


@app.post("/api/archive/stacks")
def archive_stacks(request: SearchRequest):
    try:
        features = client.search(
            geometry=request.geometry,
            start_date=request.start_date,
            end_date=request.end_date,
            collection_id=request.collection_id,
            contract_id=request.contract_id,
            limit=request.limit,
            max_cloud_cover=request.max_cloud_cover,
            satellite_name=request.satellite_name,
            min_gsd=request.min_gsd,
            max_gsd=request.max_gsd,
        )
        stacks = build_stacks(features)
        for stack in stacks:
            _cache_items(stack["items"])
        return {"count": len(stacks), "stacks": stacks}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Stack discovery failed: {exc}") from exc


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
            downloader=lambda url: client.download_bytes(url, contract_id=request.contract_id),
            seconds_per_frame=request.seconds_per_frame,
            output_dir=settings.output_dir,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Animation build failed: {exc}") from exc


@app.post("/api/archive/animate/search")
def archive_animate_search(request: AnimationSearchRequest):
    try:
        features = []
        for lim in (1200, 600, 300, 200):
            try:
                features = client.search(
                    geometry=request.geometry,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    collection_id=request.collection_id,
                    contract_id=request.contract_id,
                    limit=lim,
                    max_cloud_cover=request.max_cloud_cover,
                    satellite_name=request.satellite_name,
                    min_gsd=request.min_gsd,
                    max_gsd=request.max_gsd,
                )
                break
            except Exception:
                features = []
                continue

        items = [normalize_item(feature) for feature in features]
        items = [item for item in items if item.get("id")]
        _cache_items(items)

        result = make_capture_mosaic_animation(
            items=items,
            downloader=lambda url: client.download_bytes(url, contract_id=request.contract_id),
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
        "mp4 animation job queued job_id=%s frames=%s total_tiles=%s seconds_per_frame=%.3f contract_id=%s",
        job_id,
        len(frames),
        total_tiles,
        float(request.seconds_per_frame),
        request.contract_id or "",
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


@app.post("/api/archive/compare")
def archive_compare(request: CompareRequest):
    before_item = _resolve_item(request.before_item_id, contract_id=request.contract_id)
    after_item = _resolve_item(request.after_item_id, contract_id=request.contract_id)

    if not before_item or not after_item:
        raise HTTPException(status_code=404, detail="One or both comparison items were not found")

    return compare_pair(before_item, after_item)


@app.get("/api/annotations")
def get_annotations(aoi_name: str | None = None):
    return list_annotations(aoi_name)


@app.post("/api/annotations")
def post_annotation(record: AnnotationRecord):
    feature = save_annotation(
        note=record.note,
        geometry=record.geometry,
        label=record.label,
        aoi_name=record.aoi_name,
    )
    return {"saved": True, "feature": feature}


@app.post("/api/geoagent/report", response_model=GeoAgentResponse)
def geoagent_report(request: GeoAgentRequest):
    try:
        features = client.search(
            geometry=request.geometry,
            start_date=request.start_date,
            end_date=request.end_date,
            collection_id=request.collection_id,
            contract_id=request.contract_id,
            limit=300,
            max_cloud_cover=80,
            satellite_name=request.satellite_name,
            min_gsd=request.min_gsd,
            max_gsd=request.max_gsd,
        )
        items = [normalize_item(feature) for feature in features]
        items = [item for item in items if item.get("id")]
        _cache_items(items)

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
            downloader=lambda url: client.download_bytes(url, contract_id=request.contract_id),
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
        "has_satl_credentials": bool(settings.satellogic_key_id and settings.satellogic_key_secret),
        "has_contract_id": bool(settings.satellogic_contract_id),
        "has_bearer_token": bool(settings.satellogic_bearer_token),
        "has_openai_key": bool(settings.openai_api_key),
        "collection_default": settings.satellogic_collection_id,
    }


@app.post("/api/auth/refresh-token")
def refresh_auth_token():
    try:
        refreshed, expiry = client.refresh_access_token()
        if not refreshed:
            raise HTTPException(status_code=503, detail="Token refresh returned empty token")
        return {
            "refreshed": True,
            "auth_mode": getattr(client, "auth_mode", "unknown"),
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
