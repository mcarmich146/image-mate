#!/usr/bin/env python3
"""Build site-local L1D-SR time-series animations for the data-centre atlas.

This is the standalone Image Mate archive -> site-focus quality gate ->
temporal-stack renderer used by the publication map.  It deliberately works on
the provider's georeferenced L1D-SR ``visual`` and ``cloud`` GeoTIFF assets
rather than on browse thumbnails.  Each outcome becomes one frame, with all
spatial tiles for that outcome composed onto one fixed, north-up 2.0 km square
centered on the data-centre pin.

The L1D-SR cloud asset observed in the live archive is a categorical uint8
GeoTIFF: class 1 behaves as clear, class 2 is treated as haze, class 3 as
cloud, and class 0 is nodata.  The STAC collection does not publish a class
legend, so the manifest records this operational rule and the validation
evidence.  A frame is retained when the 2.0 km animation focus has at least
90% visual + cloud-mask coverage, allowing class-2 haze over the focus while
rejecting class-3 cloud there.  Cloud elsewhere in a tile does not affect the
decision.

The script never creates tasking or processing orders.  It writes a local,
reviewable weekly-tasking preview for sites without a capture in the last 14
days; final order submission remains an explicit, separately approved action.

Run from the repository root:

  .venv/bin/python scripts/build_data_center_animations.py

The output is written below ``docs/research/data-center-map/animations`` and
the local tasking preview is written below ``docs/research``.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import reproject
from shapely.geometry import Point, box, mapping, shape
from shapely.ops import transform as transform_geometry

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "docs/research"
AOI_PATH = RESEARCH / "data-center-search-aois-2026-09-09.geojson"
ANIMATION_ROOT = RESEARCH / "data-center-map/animations"
TASKING_PREVIEW_PATH = RESEARCH / "data-center-tasking-previews-2026-09-10.geojson"

COLLECTION = "l1d-sr"
ARCHIVE_START = "2024-09-09T00:00:00Z"
ARCHIVE_END = "2026-09-10T23:59:59Z"
ACTIVE_CUTOFF = "2026-08-27T00:00:00Z"
MAX_OUTPUT_SIDE = 4000
FOCUS_SIZE_M = 2000.0
MIN_FOCUS_COVERAGE = 0.90
CLEAR_CLASS = 1
HAZE_CLASSES = {2}
CLOUD_CLASSES = {3}
KNOWN_CLASSES = {1, 2, 3}


def _slug(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "site"


def _date_token(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown-date"
    return re.sub(r"[^0-9A-Za-z]+", "", text[:10]) or "unknown-date"


def _safe_id(value: str | None) -> str:
    return hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:10]


def _clear_rendered_animation(site_dir: Path, slug: str, *, clear_frames: bool = False) -> None:
    """Remove generated outputs that no longer correspond to a ready sequence."""
    for name in (f"{slug}.mp4", "poster.png", "animation.html"):
        path = site_dir / name
        if path.exists():
            path.unlink()
    if clear_frames and (site_dir / "frames").exists():
        shutil.rmtree(site_dir / "frames")


def _font(size: int):
    candidates = (
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _normalise_item(row: dict[str, Any]) -> dict[str, Any]:
    properties = row.get("properties") if isinstance(row.get("properties"), dict) else {}
    assets = row.get("assets") if isinstance(row.get("assets"), dict) else {}

    def asset_href(*keys: str) -> str | None:
        for key in keys:
            asset = assets.get(key)
            if isinstance(asset, dict) and str(asset.get("href") or "").strip():
                return str(asset["href"]).strip()
        return None

    outcome_id = properties.get("satl:outcome_id") or properties.get("outcome_id") or row.get("id")
    capture_datetime = properties.get("datetime") or properties.get("start_datetime")
    asset_summary = {
        str(key): {
            "type": str(value.get("type") or "") if isinstance(value, dict) else "",
            "roles": list(value.get("roles") or []) if isinstance(value, dict) else [],
        }
        for key, value in assets.items()
    }
    return {
        "id": str(row.get("id") or ""),
        "outcome_id": str(outcome_id or ""),
        "datetime": str(capture_datetime or ""),
        "geometry": row.get("geometry") or {},
        "gsd": properties.get("gsd"),
        "eo_cloud_cover": properties.get("eo:cloud_cover"),
        "platform": properties.get("platform"),
        "proj_epsg": properties.get("proj:epsg"),
        "asset_summary": asset_summary,
        # Kept in memory only.  URLs are intentionally excluded from manifests.
        "_visual_href": asset_href("visual"),
        "_cloud_href": asset_href("cloud", "cloud_mask", "cloudmask", "cloud-mask", "cmask", "clm"),
    }


def _target_grid(site: dict[str, Any], focus_size_m: float = FOCUS_SIZE_M) -> dict[str, Any]:
    if focus_size_m <= 0:
        raise ValueError("focus_size_m must be positive")
    center = site.get("center") or [0.0, 0.0]
    longitude = float(center[0])
    latitude = float(center[1])
    zone = int(math.floor((longitude + 180.0) / 6.0) + 1)
    epsg = (32600 if latitude >= 0 else 32700) + max(1, min(60, zone))
    target_crs = CRS.from_epsg(epsg)
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    pin_native = transform_geometry(transformer.transform, Point(longitude, latitude))
    half_size = float(focus_size_m) / 2.0
    focus_native = box(
        pin_native.x - half_size,
        pin_native.y - half_size,
        pin_native.x + half_size,
        pin_native.y + half_size,
    )
    display_x0, display_y0, display_x1, display_y1 = focus_native.bounds
    resolution = max(0.5, float(focus_size_m) / MAX_OUTPUT_SIDE)
    width = max(2, int(math.ceil(float(focus_size_m) / resolution)))
    height = max(2, int(math.ceil(float(focus_size_m) / resolution)))
    # H.264/yuv420p requires even frame dimensions.
    if width % 2:
        width += 1
    if height % 2:
        height += 1
    transform = from_origin(display_x0, display_y1, resolution, resolution)
    aoi_mask = geometry_mask(
        [mapping(focus_native)],
        out_shape=(height, width),
        transform=transform,
        invert=True,
    )
    return {
        "crs": target_crs,
        "crs_name": str(target_crs),
        "transform": transform,
        "width": width,
        "height": height,
        "resolution_m": resolution,
        "focus_size_m": float(focus_size_m),
        "focus_center": [longitude, latitude],
        "focus_bounds_m": [float(display_x0), float(display_y0), float(display_x1), float(display_y1)],
        "aoi_mask": aoi_mask,
        "aoi_pixels": int(np.count_nonzero(aoi_mask)),
        "bounds": [float(display_x0), float(display_y0), float(display_x0 + width * resolution), float(display_y1)],
    }


def _reproject_array(
    source: np.ndarray,
    source_dataset,
    grid: dict[str, Any],
    *,
    resampling: Resampling,
    dtype,
) -> np.ndarray:
    destination = np.zeros((grid["height"], grid["width"]), dtype=dtype)
    reproject(
        source=source,
        destination=destination,
        src_transform=source_dataset.transform,
        src_crs=source_dataset.crs,
        dst_transform=grid["transform"],
        dst_crs=grid["crs"],
        resampling=resampling,
        src_nodata=source_dataset.nodata,
        dst_nodata=0,
        init_dest_nodata=True,
    )
    return destination


def _quality_rank(valid: np.ndarray, mask_valid: np.ndarray, classes: np.ndarray) -> np.ndarray:
    """Prefer clear, then allowed haze, then cloud/unknown, then visual-only pixels."""
    rank = np.zeros(valid.shape, dtype=np.uint8)
    rank[valid & ~mask_valid] = 1
    rank[valid & mask_valid] = 2
    rank[valid & mask_valid & np.isin(classes, list(HAZE_CLASSES))] = 3
    rank[valid & mask_valid & (classes == CLEAR_CLASS)] = 4
    return rank


def _cloud_mask_precheck(items: list[dict[str, Any]], grid: dict[str, Any], downloader):
    """Reject cloudy site outcomes before downloading large visual assets."""
    selected_mask_valid = np.zeros((grid["height"], grid["width"]), dtype=bool)
    selected_classes = np.zeros((grid["height"], grid["width"]), dtype=np.uint8)
    cloud_bytes_by_item: dict[str, bytes] = {}
    errors: list[str] = []

    def fetch_cloud(item: dict[str, Any]):
        item_id = str(item.get("id") or "unknown-item")
        href = item.get("_cloud_href")
        if not href:
            return item_id, None, f"{item_id}: missing cloud asset"
        try:
            return item_id, downloader(href), None
        except Exception as exc:
            return item_id, None, f"{item_id}: {type(exc).__name__}: {str(exc)[:180]}"

    with ThreadPoolExecutor(max_workers=min(4, max(1, len(items)))) as pool:
        futures = [pool.submit(fetch_cloud, item) for item in items]
        fetched = [future.result() for future in futures]

    for item, (item_id, cloud_bytes, error) in zip(items, fetched):
        if error or cloud_bytes is None:
            errors.append(error or f"{item_id}: empty cloud asset")
            continue
        cloud_bytes_by_item[item_id] = cloud_bytes
        try:
            with MemoryFile(cloud_bytes) as cloud_mem:
                with cloud_mem.open() as cloud:
                    if cloud.crs is None or cloud.count < 1:
                        raise ValueError("cloud raster has no CRS or bands")
                    cloud_values = _reproject_array(
                        cloud.read(1), cloud, grid, resampling=Resampling.nearest, dtype=np.uint8
                    )
                    cloud_valid = _reproject_array(
                        cloud.dataset_mask(), cloud, grid, resampling=Resampling.nearest, dtype=np.uint8
                    ) > 0
                    rank = np.zeros(cloud_valid.shape, dtype=np.uint8)
                    rank[cloud_valid] = 2
                    rank[cloud_valid & np.isin(cloud_values, list(CLOUD_CLASSES))] = 1
                    rank[cloud_valid & np.isin(cloud_values, list(HAZE_CLASSES))] = 3
                    rank[cloud_valid & (cloud_values == CLEAR_CLASS)] = 4
                    current_rank = np.zeros(selected_mask_valid.shape, dtype=np.uint8)
                    current_rank[selected_mask_valid] = 2
                    current_rank[selected_mask_valid & np.isin(selected_classes, list(CLOUD_CLASSES))] = 1
                    current_rank[selected_mask_valid & np.isin(selected_classes, list(HAZE_CLASSES))] = 3
                    current_rank[selected_mask_valid & (selected_classes == CLEAR_CLASS)] = 4
                    replace = rank > current_rank
                    selected_mask_valid[replace] = cloud_valid[replace]
                    selected_classes[replace] = cloud_values[replace]
        except Exception as exc:
            errors.append(f"{item_id}: {type(exc).__name__}: {str(exc)[:180]}")

    aoi_mask = grid["aoi_mask"]
    aoi_pixels = max(1, int(grid["aoi_pixels"]))
    qa_site = aoi_mask & selected_mask_valid
    haze_site = qa_site & np.isin(selected_classes, list(HAZE_CLASSES))
    cloud_site = qa_site & np.isin(selected_classes, list(CLOUD_CLASSES))
    unknown_site = qa_site & ~np.isin(selected_classes, list(KNOWN_CLASSES))
    class_counts = Counter(int(value) for value in selected_classes[qa_site].tolist())
    coverage = float(np.count_nonzero(qa_site) / aoi_pixels)
    haze_fraction = float(np.count_nonzero(haze_site) / max(1, np.count_nonzero(qa_site)))
    cloud_fraction = float(np.count_nonzero(cloud_site) / max(1, np.count_nonzero(qa_site)))
    unknown_fraction = float(np.count_nonzero(unknown_site) / max(1, np.count_nonzero(qa_site)))
    if errors:
        decision, reason = "reject", "cloud_mask_download_or_decode_failed"
    elif coverage < MIN_FOCUS_COVERAGE:
        decision, reason = "reject", "cloud_mask_does_not_cover_focus"
    elif unknown_site.any():
        decision, reason = "reject", "unknown_cloud_mask_class_over_focus"
    elif cloud_site.any():
        decision, reason = "reject", "cloud_over_focus"
    elif haze_site.any():
        decision, reason = "keep", "haze_allowed_over_focus"
    else:
        decision, reason = "keep", "clear_focus"
    return cloud_bytes_by_item, {
        "cloud_mask_coverage_fraction": round(coverage, 6),
        "haze_fraction_over_focus": round(haze_fraction, 6),
        "cloud_fraction_over_focus": round(cloud_fraction, 6),
        "unknown_mask_fraction_over_focus": round(unknown_fraction, 6),
        "cloud_mask_class_counts_over_focus": dict(sorted(class_counts.items())),
        "cloud_mask_decision": decision,
        "cloud_mask_decision_reason": reason,
        "cloud_mask_errors": errors,
    }


def _compose_capture(
    items: list[dict[str, Any]],
    grid: dict[str, Any],
    downloader,
    cloud_bytes_by_item: dict[str, bytes] | None = None,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    rgb = np.zeros((3, grid["height"], grid["width"]), dtype=np.uint8)
    selected_valid = np.zeros((grid["height"], grid["width"]), dtype=bool)
    selected_mask_valid = np.zeros((grid["height"], grid["width"]), dtype=bool)
    selected_classes = np.zeros((grid["height"], grid["width"]), dtype=np.uint8)
    tile_details: list[dict[str, Any]] = []
    errors: list[str] = []

    cloud_bytes_by_item = dict(cloud_bytes_by_item or {})

    def fetch_assets(item: dict[str, Any]):
        item_id = item.get("id") or "unknown-item"
        visual_href = item.get("_visual_href")
        cloud_href = item.get("_cloud_href")
        if not visual_href or not cloud_href:
            return item, None, None, f"{item_id}: missing visual or cloud asset"
        try:
            cloud_bytes = cloud_bytes_by_item.get(str(item_id))
            if cloud_bytes is None:
                cloud_bytes = downloader(cloud_href)
            return item, downloader(visual_href), cloud_bytes, None
        except Exception as exc:
            return item, None, None, f"{item_id}: {type(exc).__name__}: {str(exc)[:180]}"

    # Visual assets are tens of megabytes each. Fetch the tiles of one outcome
    # concurrently, then decode/reproject them one at a time so peak raster
    # memory stays bounded.
    fetched_assets = []
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(items)))) as pool:
        futures = [pool.submit(fetch_assets, item) for item in items]
        for future in futures:
            fetched_assets.append(future.result())

    for item, visual_bytes, cloud_bytes, fetch_error in fetched_assets:
        item_id = item.get("id") or "unknown-item"
        if fetch_error:
            errors.append(fetch_error)
            continue
        try:
            with MemoryFile(visual_bytes) as visual_mem, MemoryFile(cloud_bytes) as cloud_mem:
                with visual_mem.open() as visual, cloud_mem.open() as cloud:
                    if visual.crs is None or cloud.crs is None:
                        raise ValueError("visual/cloud raster has no CRS")
                    if visual.count < 3 or cloud.count < 1:
                        raise ValueError("unexpected visual/cloud band count")
                    visual_data = np.stack(
                        [
                            _reproject_array(visual.read(index), visual, grid, resampling=Resampling.bilinear, dtype=np.uint8)
                            for index in range(1, 4)
                        ],
                        axis=0,
                    )
                    visual_valid = _reproject_array(
                        visual.dataset_mask(), visual, grid, resampling=Resampling.nearest, dtype=np.uint8
                    ) > 0
                    cloud_values = _reproject_array(
                        cloud.read(1), cloud, grid, resampling=Resampling.nearest, dtype=np.uint8
                    )
                    cloud_valid = _reproject_array(
                        cloud.dataset_mask(), cloud, grid, resampling=Resampling.nearest, dtype=np.uint8
                    ) > 0

                    new_rank = _quality_rank(visual_valid, cloud_valid, cloud_values)
                    current_rank = _quality_rank(selected_valid, selected_mask_valid, selected_classes)
                    replace = new_rank > current_rank
                    for band in range(3):
                        rgb[band, replace] = visual_data[band, replace]
                    selected_valid[replace] = visual_valid[replace]
                    selected_mask_valid[replace] = cloud_valid[replace]
                    selected_classes[replace] = cloud_values[replace]
                    tile_details.append(
                        {
                            "item_id": item_id,
                            "datetime": item.get("datetime"),
                            "crs": str(visual.crs),
                            "width": int(visual.width),
                            "height": int(visual.height),
                            "visual_bytes": len(visual_bytes),
                            "cloud_bytes": len(cloud_bytes),
                            "asset_keys": sorted(item.get("asset_summary", {}).keys()),
                        }
                    )
        except Exception as exc:
            errors.append(f"{item_id}: {type(exc).__name__}: {str(exc)[:180]}")

    aoi_mask = grid["aoi_mask"]
    aoi_pixels = max(1, int(grid["aoi_pixels"]))
    visual_site = aoi_mask & selected_valid
    qa_site = visual_site & selected_mask_valid
    haze_site = qa_site & np.isin(selected_classes, list(HAZE_CLASSES))
    cloud_site = qa_site & np.isin(selected_classes, list(CLOUD_CLASSES))
    unknown_site = qa_site & ~np.isin(selected_classes, list(KNOWN_CLASSES))
    class_counts = Counter(int(value) for value in selected_classes[qa_site].tolist())
    visual_coverage = float(np.count_nonzero(visual_site) / aoi_pixels)
    qa_coverage = float(np.count_nonzero(qa_site) / aoi_pixels)
    haze_fraction = float(np.count_nonzero(haze_site) / max(1, np.count_nonzero(qa_site)))
    cloud_fraction = float(np.count_nonzero(cloud_site) / max(1, np.count_nonzero(qa_site)))
    unknown_fraction = float(np.count_nonzero(unknown_site) / max(1, np.count_nonzero(qa_site)))

    if errors:
        decision, reason = "reject", "asset_download_or_decode_failed"
    elif visual_coverage < MIN_FOCUS_COVERAGE:
        decision, reason = "reject", "incomplete_visual_coverage_over_focus"
    elif qa_coverage < MIN_FOCUS_COVERAGE:
        decision, reason = "reject", "cloud_mask_does_not_cover_focus"
    elif unknown_site.any():
        decision, reason = "reject", "unknown_cloud_mask_class_over_focus"
    elif cloud_site.any():
        decision, reason = "reject", "cloud_over_focus"
    elif haze_site.any():
        decision, reason = "keep", "haze_allowed_over_focus"
    else:
        decision, reason = "keep", "clear_focus"

    metadata = {
        "item_ids": [str(item.get("id") or "") for item in items],
        "tile_count": len(items),
        "decoded_tile_count": len(tile_details),
        "tile_details": tile_details,
        "errors": errors,
        "visual_coverage_fraction": round(visual_coverage, 6),
        "cloud_mask_coverage_fraction": round(qa_coverage, 6),
        "haze_fraction_over_focus": round(haze_fraction, 6),
        "cloud_fraction_over_focus": round(cloud_fraction, 6),
        "unknown_mask_fraction_over_focus": round(unknown_fraction, 6),
        "cloud_mask_class_counts_over_focus": dict(sorted(class_counts.items())),
        "decision": decision,
        "decision_reason": reason,
        "cloud_mask_rule": "class 1 clear; class 2 haze allowed; class 3 cloud rejects; class 0/nodata ignored outside valid mask",
    }
    return (rgb if decision == "keep" else None), metadata


def _decorate_frame(
    rgb: np.ndarray,
    site_label: str,
    capture_datetime: str,
    tile_count: int,
    focus_size_m: float = FOCUS_SIZE_M,
) -> Image.Image:
    image = Image.fromarray(np.moveaxis(rgb, 0, -1))
    draw = ImageDraw.Draw(image)
    width, height = image.size
    banner_h = max(76, min(108, int(height * 0.10)))
    draw.rectangle((0, 0, width, banner_h), fill=(12, 29, 39))
    draw.rectangle((0, banner_h - 4, width, banner_h), fill=(8, 126, 139))
    title_font = _font(max(18, min(31, width // 50)))
    meta_font = _font(max(12, min(19, width // 80)))
    stamp = str(capture_datetime or "").replace("+00:00", "Z")
    if "T" in stamp:
        stamp = stamp.split("T", 1)[0]
    draw.text((24, 16), site_label, fill=(255, 255, 255), font=title_font)
    focus_label = f"{focus_size_m / 1000:.1f} km focus"
    draw.text((24, banner_h - 31), f"{stamp}  ·  L1D-SR Visual  ·  {tile_count} source tile(s)  ·  clear/haze accepted over {focus_label}", fill=(190, 219, 224), font=meta_font)
    return image


def _write_animation_page(site: dict[str, Any], site_result: dict[str, Any], site_dir: Path) -> str:
    video_name = Path(site_result["video"]).name
    poster_name = Path(site_result["poster"]).name
    dates = "".join(
        f'<li><time>{str(frame.get("datetime") or "")[:10]}</time><span>{frame.get("tile_count", 0)} tile(s)</span></li>'
        for frame in site_result.get("frames", [])
    )
    rejected = "".join(
        f'<li><time>{str(frame.get("datetime") or "")[:10]}</time><span>{frame.get("decision_reason", "rejected")}</span></li>'
        for frame in site_result.get("rejected_frames", [])
    )
    title = str(site.get("label") or site.get("name") or "Data centre")
    focus_size_m = float(site_result.get("focus_size_m", FOCUS_SIZE_M))
    focus_label = f"{focus_size_m / 1000:.1f} km × {focus_size_m / 1000:.1f} km"
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · L1D-SR time series</title>
<style>
:root{{--ink:#122b38;--muted:#647b84;--line:#d9e5e8;--accent:#087e8b;--panel:#fff;--bg:#f3f7f8}}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(135deg,#edf4f5,#f8fafb);font:14px/1.5 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink)}}
.shell{{max-width:1180px;margin:0 auto;padding:28px 24px 46px}} .eyebrow{{color:var(--accent);font-size:11px;font-weight:800;letter-spacing:1.6px;text-transform:uppercase}}
h1{{font-size:clamp(25px,4vw,42px);letter-spacing:-1px;line-height:1.1;margin:7px 0 8px}} .lede{{color:var(--muted);max-width:750px;margin:0 0 22px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:0 14px 40px #17384512;overflow:hidden}} video{{display:block;width:100%;max-height:76vh;background:#071117;object-fit:contain}}
.body{{padding:19px 21px}} .grid{{display:grid;grid-template-columns:1.1fr .9fr;gap:22px;margin-top:18px}} h2{{font-size:16px;margin:0 0 10px}} p{{margin:0 0 10px}} .muted{{color:var(--muted);font-size:12px}}
ol{{list-style:none;padding:0;margin:0;display:grid;gap:7px}} li{{display:flex;justify-content:space-between;gap:16px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:#fbfdfd}} time{{font-variant-numeric:tabular-nums;font-weight:700}} li span{{color:var(--muted);text-align:right;font-size:12px}} .note{{border-left:3px solid var(--accent);padding:10px 12px;background:#eff9fa;border-radius:4px;color:#315966;font-size:12px}}
@media(max-width:760px){{.shell{{padding:20px 14px 36px}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main class="shell">
<div class="eyebrow">Image Mate · Satellogic archive</div><h1>{title}</h1>
<p class="lede">A fixed-extent, north-up time series of L1D-SR Visual products centered on the site pin. Each frame represents one capture outcome; spatial tiles from the same outcome are composed together.</p>
<section class="card"><video controls autoplay muted loop playsinline poster="{poster_name}" src="{video_name}">Your browser does not support HTML5 video.</video><div class="body"><div class="note">Animation window: {focus_label}, centered on the data-centre pin. Quality gate: the focus must have at least {MIN_FOCUS_COVERAGE:.0%} visual and cloud-mask coverage; class-2 haze is retained, while class-3 cloud over the focus rejects the frame. Cloud elsewhere in a source tile does not remove the frame.</div></div></section>
<div class="grid"><section class="card"><div class="body"><h2>Included captures · {site_result.get("frame_count", 0)}</h2><ol>{dates or '<li><span>No clear multi-date sequence</span></li>'}</ol></div></section>
<section class="card"><div class="body"><h2>Quality exclusions · {len(site_result.get("rejected_frames", []))}</h2><ol>{rejected or '<li><span>No exclusions</span></li>'}</ol><p class="muted" style="margin-top:12px">Collection: {COLLECTION} · resolution: {site_result.get("resolution_m", 0):.2f} m output grid · source collection license: proprietary</p></div></section></div>
</main></body></html>'''
    page_path = site_dir / "animation.html"
    page_path.write_text(html, encoding="utf-8")
    return page_path.name


def _capture_groups(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(str(item.get("outcome_id") or item.get("id") or "unknown"), []).append(item)
    captures = [
        {
            "outcome_id": outcome_id,
            "datetime": sorted(group, key=lambda row: row.get("datetime") or "")[0].get("datetime"),
            "items": sorted(group, key=lambda row: row.get("id") or ""),
        }
        for outcome_id, group in groups.items()
    ]
    return sorted(captures, key=lambda row: row.get("datetime") or "")


def _site_animation(
    site: dict[str, Any],
    items: list[dict[str, Any]],
    client,
    output_root: Path,
    focus_size_m: float = FOCUS_SIZE_M,
) -> dict[str, Any]:
    slug = _slug(site.get("name") or site.get("id"))
    site_dir = output_root / slug
    frames_dir = site_dir / "frames"
    _clear_rendered_animation(site_dir, slug, clear_frames=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    grid = _target_grid(site, focus_size_m=focus_size_m)
    captures = _capture_groups(items)
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    downloader = lambda url: client.download_bytes(url, contract_id=None)

    for index, capture in enumerate(captures, start=1):
        print(f"  {site.get('label')}: capture {index}/{len(captures)} ({str(capture.get('datetime') or '')[:10]})", flush=True)
        cloud_bytes, cloud_quality = _cloud_mask_precheck(capture["items"], grid, downloader)
        if cloud_quality.get("cloud_mask_decision") != "keep":
            quality = {
                "item_ids": [str(item.get("id") or "") for item in capture["items"]],
                "tile_count": len(capture["items"]),
                "decoded_tile_count": len(cloud_bytes),
                "tile_details": [],
                "errors": cloud_quality.get("cloud_mask_errors") or [],
                "visual_coverage_fraction": None,
                **cloud_quality,
                "decision": "reject",
                "decision_reason": cloud_quality.get("cloud_mask_decision_reason"),
                "cloud_mask_rule": "class 1 clear; class 2 haze allowed; class 3 cloud rejects; class 0/nodata ignored outside valid mask",
            }
            rejected.append({"outcome_id": capture.get("outcome_id"), "datetime": capture.get("datetime"), **quality})
            continue
        rgb, quality = _compose_capture(capture["items"], grid, downloader, cloud_bytes_by_item=cloud_bytes)
        frame_record = {
            "outcome_id": capture.get("outcome_id"),
            "datetime": capture.get("datetime"),
            **quality,
        }
        if rgb is None:
            rejected.append(frame_record)
            continue
        image = _decorate_frame(
            rgb,
            str(site.get("label") or site.get("name")),
            str(capture.get("datetime") or ""),
            len(capture["items"]),
            focus_size_m=focus_size_m,
        )
        frame_name = f"{_date_token(capture.get('datetime'))}_{_safe_id(capture.get('outcome_id'))}.png"
        frame_path = frames_dir / frame_name
        image.save(frame_path, format="PNG", optimize=True)
        frame_record["path"] = str(frame_path.relative_to(output_root))
        kept.append(frame_record)

    result: dict[str, Any] = {
        "site_id": site.get("id"),
        "site_name": site.get("name"),
        "site_label": site.get("label"),
        "slug": slug,
        "collection": COLLECTION,
        "archive_window": [ARCHIVE_START, ARCHIVE_END],
        "active_cutoff": ACTIVE_CUTOFF,
        "total_items": len(items),
        "total_outcomes": len(captures),
        "frame_count": len(kept),
        "rejected_count": len(rejected),
        "frames": kept,
        "rejected_frames": rejected,
        "resolution_m": float(grid["resolution_m"]),
        "output_size": [grid["width"], grid["height"]],
        "focus_size_m": float(grid["focus_size_m"]),
        "focus_center": grid["focus_center"],
        "focus_bounds_m": grid["focus_bounds_m"],
        "target_crs": grid["crs_name"],
        "tasking_approved_in_source": bool(site.get("tasking_approved", False)),
        "quality_policy": {
            "min_focus_coverage_fraction": MIN_FOCUS_COVERAGE,
            "focus_size_m": float(grid["focus_size_m"]),
            "clear_class": CLEAR_CLASS,
            "haze_classes_allowed": sorted(HAZE_CLASSES),
            "cloud_classes_rejected": sorted(CLOUD_CLASSES),
            "known_classes": sorted(KNOWN_CLASSES),
            "scope": "fixed square centered on the site pin; class-2 haze is allowed in focus; scene-wide cloud does not reject a frame",
        },
    }
    if len(kept) >= 2:
        import imageio.v2 as imageio

        video_path = site_dir / f"{slug}.mp4"
        writer = imageio.get_writer(
            str(video_path),
            format="FFMPEG",
            fps=1.25,
            codec="libx264",
            quality=8,
            macro_block_size=1,
            ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        )
        try:
            for frame in kept:
                with Image.open(output_root / frame["path"]) as image:
                    writer.append_data(np.asarray(image.convert("RGB")))
        finally:
            writer.close()
        poster_path = site_dir / "poster.png"
        first_frame = output_root / kept[0]["path"]
        poster_path.write_bytes(first_frame.read_bytes())
        result["status"] = "ready"
        result["video"] = str(video_path.relative_to(RESEARCH / "data-center-map"))
        result["poster"] = str(poster_path.relative_to(RESEARCH / "data-center-map"))
        _write_animation_page(site, result, site_dir)
        result["html"] = str((site_dir / "animation.html").relative_to(RESEARCH / "data-center-map"))
    else:
        result["status"] = "no_clear_multi_date_sequence"
        result["video"] = None
        result["poster"] = None
        result["html"] = None

    (site_dir / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _tasking_preview(site: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    recent = result.get("latest_capture_datetime")
    active = bool(recent and str(recent) >= ACTIVE_CUTOFF)
    if active:
        return None
    # Lake Mariner has a provisional tenant attribution, but its physical
    # location is distinct from River Bend's explicitly unverified pin.
    provisional = not bool(site.get("tasking_location_verified", True))
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": list(site.get("center") or [None, None])},
        "properties": {
            "site_id": site.get("id"),
            "site": site.get("name"),
            "label": site.get("label"),
            "status": "blocked_unverified_location" if provisional else "preview_requires_confirmation",
            "reason": "No L1D-SR capture in the last 14 days",
            "last_archive_capture": recent,
            "proposed_target_type": "point",
            "proposed_sku": "TSKPOI-M",
            "proposed_revisit_period": "P7D",
            "proposed_processing_level": "L1D_SR",
            "proposed_project_name": "Image Mate Data Centre Monitoring",
            "proposed_order_name": f"image-mate-datacentre-weekly-{_slug(site.get('name'))}",
            "time_horizon": "90-day pilot (default proposal; must be confirmed)",
            "cloud_rule": "Tasking request cloud/quality terms require provider confirmation; post-capture animation applies site-local L1D-SR cloud mask QC.",
            "blocking_reasons": [
                "Source geometry is a research search rectangle/center, not a verified cadastral or facility polygon.",
                "Weekly P7D cadence and current SKU/price/entitlement must be confirmed with the Sales–Showcase contract before submission.",
                *(["River Bend location is explicitly provisional and must not be tasked without a verified site."] if provisional else []),
            ],
        },
    }


def _search_site(site: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    from backend.app.satellogic_client import SatellogicClient

    client = SatellogicClient()
    try:
        rows = client.search(site["geometry"], ARCHIVE_START, ARCHIVE_END, COLLECTION, None, 1000, None)
        if len(rows) >= 1000:
            return site, [], "search_limit_reached"
        return site, [_normalise_item(row) for row in rows], None
    except Exception as exc:
        return site, [], f"{type(exc).__name__}: {str(exc)[:240]}"


def run(args: argparse.Namespace) -> None:
    # When launched as ``python scripts/...py`` Python puts the scripts
    # directory on sys.path, but it is not a package in this repository.
    from build_data_center_map import prepare_sites
    from backend.app.satellogic_client import SatellogicClient

    geojson = json.loads(AOI_PATH.read_text(encoding="utf-8"))
    research_path = RESEARCH / "data-center-imagery-2026-09-09.json"
    research = json.loads(research_path.read_text(encoding="utf-8"))
    sites = prepare_sites(research, geojson)
    output_root = Path(args.output_dir).resolve() if args.output_dir else ANIMATION_ROOT
    output_root.mkdir(parents=True, exist_ok=True)
    focus_size_m = float(getattr(args, "focus_size_m", FOCUS_SIZE_M))
    if focus_size_m <= 0:
        raise ValueError("--focus-size-m must be positive")
    client = SatellogicClient()
    client.auth_headers()

    print(f"Refreshing {COLLECTION} archive for {len(sites)} site AOIs", flush=True)
    search_results: dict[str, list[dict[str, Any]]] = {}
    search_errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_search_site, site) for site in sites]
        for future in as_completed(futures):
            site, items, error = future.result()
            search_results[str(site["id"])] = items
            if error:
                search_errors[str(site["id"])] = error
            print(f"  {site['label']}: {len(items)} L1D-SR items" + (f" ({error})" if error else ""), flush=True)

    site_results: dict[str, dict[str, Any]] = {}
    tasking_features: list[dict[str, Any]] = []
    for site in sites:
        site_id = str(site["id"])
        items = search_results.get(site_id, [])
        existing_manifest = output_root / _slug(site.get("name")) / "manifest.json"
        result = None
        if existing_manifest.exists() and not args.force:
            try:
                candidate = json.loads(existing_manifest.read_text(encoding="utf-8"))
                candidate_focus_size = float(candidate.get("focus_size_m", -1))
                if (
                    candidate.get("status") in {"ready", "no_clear_multi_date_sequence"}
                    and math.isclose(candidate_focus_size, focus_size_m)
                ):
                    result = candidate
                    print(f"  {site['label']}: using existing {candidate.get('status')} render (use --force to rebuild)", flush=True)
            except (OSError, ValueError, TypeError):
                result = None
        if result is None:
            result = _site_animation(site, items, client, output_root, focus_size_m=focus_size_m)
        if result.get("status") != "ready":
            _clear_rendered_animation(output_root / _slug(site.get("name")), _slug(site.get("name")), clear_frames=True)
        result["search_error"] = search_errors.get(site_id)
        timestamps = [str(item.get("datetime") or "") for item in items if item.get("datetime")]
        result["latest_capture_datetime"] = max(timestamps) if timestamps else None
        result["active_last_14_days"] = bool(result["latest_capture_datetime"] and result["latest_capture_datetime"] >= ACTIVE_CUTOFF)
        result["tasking_preview"] = _tasking_preview(site, result) is not None
        site_results[site_id] = result
        preview = _tasking_preview(site, result)
        if preview:
            tasking_features.append(preview)
        (output_root / _slug(site.get("name")) / "manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "collection": COLLECTION,
        "archive_window": [ARCHIVE_START, ARCHIVE_END],
        "active_cutoff": ACTIVE_CUTOFF,
        "focus_size_m": focus_size_m,
        "focus_definition": "square centered on each data-centre pin; archive discovery still uses the research search AOI",
        "contract_name": "Sales - Showcase",
        "cloud_mask_validation": {
            "asset_key": "cloud",
            "observed_dtype": "uint8",
            "observed_classes": {"0": "nodata", "1": "clear", "2": "provider haze candidate (allowed)", "3": "provider cloud candidate (rejected)"},
            "stac_legend_published": False,
            "operational_rule": "keep class 1 clear and class 2 haze over the 2.0 km animation focus; reject class 3 cloud; ignore nodata outside the valid raster mask",
            "validation_note": "Class 1 occurred in a 0% scene-cloud capture; class 3 occupied a 100% scene-cloud capture; intermediate scenes were dominated by class 2/3. Class 2 is therefore allowed as haze for this requested exploratory animation, while class 3 remains a cloud rejection. This is an empirical QA rule because the live STAC collection does not publish a legend.",
        },
        "site_results": site_results,
        "tasking_preview_count": len(tasking_features),
        "tasking_preview_path": str(TASKING_PREVIEW_PATH.relative_to(RESEARCH)),
        "submission_status": "no taskings submitted; preview only",
    }
    (output_root / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    TASKING_PREVIEW_PATH.write_text(
        json.dumps({"type": "FeatureCollection", "name": "Image Mate weekly data-centre tasking previews", "features": tasking_features}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "sites": len(sites),
        "ready_animations": sum(row.get("status") == "ready" for row in site_results.values()),
        "tasking_previews": len(tasking_features),
        "active_last_14_days": [row.get("site_name") for row in site_results.values() if row.get("active_last_14_days")],
        "output": str(output_root),
    }, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None, help="Animation output directory")
    parser.add_argument("--force", action="store_true", help="Rebuild sites even when a manifest already exists")
    parser.add_argument("--focus-size-m", type=float, default=FOCUS_SIZE_M, help="Square animation width/height around each site pin in metres (default: 2000)")
    run(parser.parse_args())
