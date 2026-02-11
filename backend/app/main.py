from __future__ import annotations

from datetime import datetime
from typing import Any
import logging
import time
import base64
import re
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
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from .satellogic_client import SatellogicClient, normalize_item
from .services import (
    build_stacks,
    compare_pair,
    list_annotations,
    make_animation_gif,
    make_capture_mosaic_animation,
    save_annotation,
)

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


@app.on_event("startup")
def startup_event():
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.annotations_file.parent.mkdir(parents=True, exist_ok=True)


def _asset_cache_key(url: str, contract_id: str | None, render: bool) -> str:
    return f"{contract_id or ''}|{int(render)}|{url}"


def _tile_cache_key(
    z: int,
    x: int,
    y: int,
    source_url: str,
    contract_id: str | None,
    scale: int,
    tile_matrix_set_id: str,
    image_format: str,
    bidx: list[int],
) -> str:
    return "|".join([
        contract_id or "",
        str(z),
        str(x),
        str(y),
        str(scale),
        tile_matrix_set_id,
        image_format,
        ",".join(str(v) for v in sorted(bidx)),
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


@app.get("/api/raster/cog/tiles/{z}/{x}/{y}")
def raster_cog_tile_proxy(
    z: int,
    x: int,
    y: int,
    url: str = Query(..., alias="url"),
    contract_id: str | None = Query(default=None),
    scale: int = Query(default=2),
    tileMatrixSetId: str = Query(default="WebMercatorQuad"),
    format: str = Query(default="png"),
    bidx: list[int] = Query(default=[1, 2, 3]),
):
    try:
        if z < 0 or x < 0 or y < 0:
            raise HTTPException(status_code=400, detail="Invalid tile coordinates")
        parsed = urlparse(url)
        if not parsed.scheme:
            raise HTTPException(status_code=400, detail="COG source URL must include scheme")
        if parsed.scheme not in ("s3", "http", "https"):
            raise HTTPException(status_code=400, detail="COG source scheme not supported")

        started = time.perf_counter()
        cache_key = _tile_cache_key(
            z=z,
            x=x,
            y=y,
            source_url=url,
            contract_id=contract_id,
            scale=scale,
            tile_matrix_set_id=tileMatrixSetId,
            image_format=format,
            bidx=bidx,
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
        upstream_url = f"https://api.satellogic.com/raster/cog/tiles/{z}/{x}/{y}"
        params: list[tuple[str, str]] = [
            ("scale", str(scale)),
            ("tileMatrixSetId", tileMatrixSetId),
            ("url", url),
            ("format", format),
        ]
        for band in bidx:
            params.append(("bidx", str(band)))

        upstream = requests.get(
            upstream_url,
            headers=client.auth_headers(contract_id=contract_id),
            params=params,
            timeout=90,
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
            raise HTTPException(status_code=upstream.status_code, detail=f"Tile fetch failed upstream: {upstream.status_code}")

        media_type = upstream.headers.get("Content-Type", "image/png")
        content = upstream.content
        if len(content) <= 2_000_000:
            app.state.asset_cache[cache_key] = {
                "content": content,
                "media_type": media_type,
                "expires_at": now + 300,
            }
            _prune_asset_cache()

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "tile_proxy cache=miss zxy=%s/%s/%s bytes=%s ms=%s",
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
        "has_satl_credentials": bool(settings.satellogic_key_id and settings.satellogic_key_secret),
        "has_contract_id": bool(settings.satellogic_contract_id),
        "has_openai_key": bool(settings.openai_api_key),
        "collection_default": settings.satellogic_collection_id,
    }
