from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import base64
import io
import json
import logging
import math
import statistics
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import shape

from .config import settings
from .satellogic_client import normalize_item

logger = logging.getLogger("image_mate")


def build_stacks(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for feature in features:
        item = normalize_item(feature)
        key = item["outcome_id"] or item["id"]
        grouped.setdefault(key, []).append(item)

    stacks = []
    for outcome_id, items in grouped.items():
        sorted_items = sorted(items, key=lambda i: i.get("datetime") or "", reverse=True)
        cloud_values = [i.get("cloud_cover") for i in sorted_items if i.get("cloud_cover") is not None]
        stacks.append(
            {
                "outcome_id": outcome_id,
                "count": len(sorted_items),
                "latest_datetime": sorted_items[0].get("datetime") if sorted_items else None,
                "mean_cloud_cover": round(statistics.mean(cloud_values), 2) if cloud_values else None,
                "items": sorted_items,
            }
        )

    return sorted(stacks, key=lambda s: (s["latest_datetime"] or ""), reverse=True)


def _to_small_gray(image_bytes: bytes, size: int = 256) -> np.ndarray:
    img = Image.open(io.BytesIO(image_bytes)).convert("L").resize((size, size))
    return np.asarray(img, dtype=np.float32)


def compute_change_signals(frames: list[dict[str, Any]], downloader) -> list[dict[str, Any]]:
    arrays: list[tuple[str, np.ndarray]] = []
    for frame in frames:
        source_url = frame["assets"].get("preview") or frame["assets"].get("thumbnail") or frame["assets"].get("visual")
        if not source_url:
            continue
        try:
            arrays.append((frame["id"], _to_small_gray(downloader(source_url))))
        except Exception:
            continue

    insights = []
    for idx in range(1, len(arrays)):
        before_id, before_arr = arrays[idx - 1]
        after_id, after_arr = arrays[idx]
        mad = float(np.mean(np.abs(after_arr - before_arr)))
        insights.append({"before_item_id": before_id, "after_item_id": after_id, "mean_abs_delta": round(mad, 3)})

    return sorted(insights, key=lambda x: x["mean_abs_delta"], reverse=True)


def make_animation_gif(frames: list[dict[str, Any]], downloader, seconds_per_frame: float, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    pil_frames: list[Image.Image] = []
    for frame in frames:
        source_url = frame["assets"].get("preview") or frame["assets"].get("thumbnail") or frame["assets"].get("visual")
        if not source_url:
            continue
        try:
            img_bytes = downloader(source_url)
            pil_frames.append(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
        except Exception:
            continue

    if len(pil_frames) < 2:
        return {"created": False, "reason": "Not enough frames with accessible preview imagery"}

    output_name = f"animation_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.gif"
    output_path = output_dir / output_name
    pil_frames[0].save(
        output_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=int(seconds_per_frame * 1000),
        loop=0,
    )

    with open(output_path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")

    return {
        "created": True,
        "file": str(output_path),
        "gif_base64": encoded,
        "frame_count": len(pil_frames),
    }


def make_capture_mosaic_animation(
    items: list[dict[str, Any]],
    downloader,
    seconds_per_frame: float,
    output_dir: Path,
    max_frames: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = item.get("outcome_id") or item.get("id")
        grouped.setdefault(key, []).append(item)

    captures = []
    for outcome_id, group_items in grouped.items():
        sorted_group = sorted(group_items, key=lambda x: x.get("datetime") or "")
        capture_dt = sorted_group[0].get("datetime") if sorted_group else None
        captures.append({"outcome_id": outcome_id, "datetime": capture_dt, "items": sorted_group})

    captures.sort(key=lambda x: x.get("datetime") or "")
    if max_frames and len(captures) > max_frames:
        step = max(1, len(captures) // max_frames)
        captures = captures[::step][:max_frames]

    if len(captures) < 2:
        return {"created": False, "reason": "Need at least 2 captures for animation"}

    pil_frames: list[Image.Image] = []
    frame_meta: list[dict[str, Any]] = []
    for capture in captures:
        frame = _build_capture_mosaic_frame(capture["items"], capture.get("datetime"), downloader)
        if frame is None:
            continue
        pil_frames.append(frame)
        frame_meta.append(
            {
                "outcome_id": capture.get("outcome_id"),
                "datetime": capture.get("datetime"),
                "tile_count": len(capture["items"]),
            }
        )

    if len(pil_frames) < 2:
        return {"created": False, "reason": "Not enough successful capture mosaics to animate"}

    output_name = f"capture_animation_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.gif"
    output_path = output_dir / output_name
    pil_frames[0].save(
        output_path,
        save_all=True,
        append_images=pil_frames[1:],
        duration=int(seconds_per_frame * 1000),
        loop=0,
    )

    with open(output_path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")

    return {
        "created": True,
        "file": str(output_path),
        "gif_base64": encoded,
        "frame_count": len(pil_frames),
        "frames": frame_meta,
    }


def make_selected_extent_mp4(
    frames: list[dict[str, Any]],
    viewport_geometry: dict[str, Any],
    downloader,
    seconds_per_frame: float,
    output_dir: Path,
    filename_prefix: str = "selected_extent_animation",
    progress_callback=None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ordered_frames = sorted(frames, key=lambda f: f.get("datetime") or "")
    if len(ordered_frames) < 2:
        return {"created": False, "reason": "Need at least 2 selected captures for MP4 animation"}

    try:
        viewport = shape(viewport_geometry)
        vx0, vy0, vx1, vy1 = viewport.bounds
    except Exception:
        return {"created": False, "reason": "Invalid viewport geometry"}

    view_width = max(1e-9, vx1 - vx0)
    view_height = max(1e-9, vy1 - vy0)
    if view_width <= 1e-9 or view_height <= 1e-9:
        return {"created": False, "reason": "Viewport extent is empty"}

    canvas_size = _estimate_viewport_canvas_size(ordered_frames, (vx0, vy0, vx1, vy1), downloader)
    if not canvas_size:
        return {"created": False, "reason": "No accessible full-resolution tiles in the selected viewport"}
    canvas_w, canvas_h = canvas_size

    rendered_frames: list[Image.Image] = []
    total_frames = len(ordered_frames)
    for idx, frame in enumerate(ordered_frames, start=1):
        if callable(progress_callback):
            progress_callback(idx, total_frames, frame.get("datetime"))
        composed = _build_selected_extent_frame(
            frame=frame,
            viewport_bounds=(vx0, vy0, vx1, vy1),
            canvas_size=(canvas_w, canvas_h),
            downloader=downloader,
        )
        if composed is None:
            continue
        _draw_datetime_label(composed, frame.get("datetime"))
        rendered_frames.append(composed)

    if len(rendered_frames) < 2:
        return {"created": False, "reason": "Not enough frames with visible full-resolution tiles"}

    try:
        import imageio.v2 as imageio
    except Exception as exc:
        return {"created": False, "reason": f"MP4 encoder unavailable (install imageio + imageio-ffmpeg): {exc}"}

    safe_prefix = "".join(ch if ch.isalnum() or ch in ("_", "-", ".") else "_" for ch in (filename_prefix or "selected_extent_animation"))
    safe_prefix = safe_prefix.strip("._") or "selected_extent_animation"
    output_name = f"{safe_prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.mp4"
    output_path = output_dir / output_name

    fps = max(0.2, min(60.0, 1.0 / max(0.01, float(seconds_per_frame))))
    writer = imageio.get_writer(
        str(output_path),
        format="FFMPEG",
        fps=fps,
        codec="libx264",
        quality=8,
        macro_block_size=1,
        ffmpeg_params=["-pix_fmt", "yuv420p"],
    )
    try:
        for frame_img in rendered_frames:
            writer.append_data(np.asarray(frame_img))
    finally:
        writer.close()

    return {
        "created": True,
        "file": str(output_path),
        "frame_count": len(rendered_frames),
        "width": canvas_w,
        "height": canvas_h,
        "fps": round(fps, 3),
    }


def _estimate_viewport_canvas_size(frames: list[dict[str, Any]], viewport_bounds: tuple[float, float, float, float], downloader):
    vx0, vy0, vx1, vy1 = viewport_bounds
    view_w = max(1e-9, vx1 - vx0)
    view_h = max(1e-9, vy1 - vy0)

    for frame in frames:
        for tile in frame.get("tiles", []):
            tile_bounds = _geometry_bounds(tile.get("geometry"))
            if not tile_bounds:
                continue
            tx0, ty0, tx1, ty1 = tile_bounds
            tile_w = max(1e-9, tx1 - tx0)
            tile_h = max(1e-9, ty1 - ty0)
            if tile_w <= 1e-9 or tile_h <= 1e-9:
                continue
            if max(vx0, tx0) >= min(vx1, tx1) or max(vy0, ty0) >= min(vy1, ty1):
                continue

            source_url = (tile.get("url") or "").strip()
            if not source_url:
                continue
            try:
                image_bytes = downloader(source_url)
                img = Image.open(io.BytesIO(image_bytes))
                width, height = img.size
            except Exception:
                continue

            if width < 2 or height < 2:
                continue
            px_per_deg_x = width / tile_w
            px_per_deg_y = height / tile_h
            target_w = int(round(view_w * px_per_deg_x))
            target_h = int(round(view_h * px_per_deg_y))
            return _normalize_canvas_size(target_w, target_h)

    return None


def _normalize_canvas_size(width: int, height: int, max_side: int = 8192) -> tuple[int, int]:
    w = max(256, int(width or 0))
    h = max(256, int(height or 0))

    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        w = int(round(w * scale))
        h = int(round(h * scale))

    if w % 2:
        w += 1
    if h % 2:
        h += 1
    return max(2, w), max(2, h)


def _geometry_bounds(geometry: dict[str, Any] | None):
    if not geometry:
        return None
    try:
        geom = shape(geometry)
        minx, miny, maxx, maxy = geom.bounds
    except Exception:
        return None
    if maxx <= minx or maxy <= miny:
        return None
    return float(minx), float(miny), float(maxx), float(maxy)


def _extract_tile_quad_lonlat(geometry: dict[str, Any] | None) -> list[tuple[float, float]] | None:
    if not geometry:
        return None
    try:
        geom = shape(geometry)
    except Exception:
        return None
    if geom.is_empty:
        return None

    poly = None
    if geom.geom_type == "Polygon":
        poly = geom
    elif geom.geom_type == "MultiPolygon":
        parts = [g for g in getattr(geom, "geoms", []) if getattr(g, "geom_type", "") == "Polygon" and not g.is_empty]
        if parts:
            poly = max(parts, key=lambda g: g.area)
    if poly is None:
        return None

    def _clean_ring(coords) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for coord in coords:
            if len(coord) < 2:
                continue
            pt = (float(coord[0]), float(coord[1]))
            if out and abs(out[-1][0] - pt[0]) < 1e-12 and abs(out[-1][1] - pt[1]) < 1e-12:
                continue
            out.append(pt)
        if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-12 and abs(out[0][1] - out[-1][1]) < 1e-12:
            out.pop()
        return out

    def _drop_collinear(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(ring) <= 4:
            return ring
        points = ring[:]
        changed = True
        while changed and len(points) > 4:
            changed = False
            next_points: list[tuple[float, float]] = []
            size = len(points)
            for idx in range(size):
                p0 = points[(idx - 1) % size]
                p1 = points[idx]
                p2 = points[(idx + 1) % size]
                v1x = p1[0] - p0[0]
                v1y = p1[1] - p0[1]
                v2x = p2[0] - p1[0]
                v2y = p2[1] - p1[1]
                cross = (v1x * v2y) - (v1y * v2x)
                if abs(cross) < 1e-12:
                    changed = True
                    continue
                next_points.append(p1)
            if len(next_points) >= 3:
                points = next_points
            else:
                break
        return points

    ring = _clean_ring(list(poly.exterior.coords))
    ring = _drop_collinear(ring)
    if len(ring) == 4:
        return ring

    try:
        rect = poly.minimum_rotated_rectangle
        rect_ring = _clean_ring(list(rect.exterior.coords))
        if len(rect_ring) == 4:
            return rect_ring
    except Exception:
        return None
    return None


def _lonlat_to_canvas_point(
    lon: float,
    lat: float,
    viewport_bounds: tuple[float, float, float, float],
    canvas_size: tuple[int, int],
) -> tuple[float, float]:
    vx0, vy0, vx1, vy1 = viewport_bounds
    view_w = max(1e-9, vx1 - vx0)
    view_h = max(1e-9, vy1 - vy0)
    canvas_w, canvas_h = canvas_size
    x = ((lon - vx0) / view_w) * canvas_w
    y = ((vy1 - lat) / view_h) * canvas_h
    return float(x), float(y)


def _rotate_points(points: list[tuple[float, float]], start_idx: int) -> list[tuple[float, float]]:
    return points[start_idx:] + points[:start_idx]


def _score_ordered_quad(points: list[tuple[float, float]]) -> tuple[int, float]:
    # Expected order: TL, TR, BR, BL in canvas space (y-down).
    top_mid_y = (points[0][1] + points[1][1]) * 0.5
    bottom_mid_y = (points[2][1] + points[3][1]) * 0.5
    left_mid_x = (points[0][0] + points[3][0]) * 0.5
    right_mid_x = (points[1][0] + points[2][0]) * 0.5
    vertical = bottom_mid_y - top_mid_y
    horizontal = right_mid_x - left_mid_x
    valid = 1 if vertical > 0 and horizontal > 0 else 0
    return valid, float(vertical + horizontal)


def _ordered_tile_quad_canvas_points(
    geometry: dict[str, Any] | None,
    viewport_bounds: tuple[float, float, float, float],
    canvas_size: tuple[int, int],
) -> list[tuple[float, float]] | None:
    lonlat_quad = _extract_tile_quad_lonlat(geometry)
    if not lonlat_quad:
        return None
    canvas_ring = [_lonlat_to_canvas_point(lon, lat, viewport_bounds, canvas_size) for lon, lat in lonlat_quad]
    if len(canvas_ring) != 4:
        return None

    candidates: list[list[tuple[float, float]]] = []
    for ring in (canvas_ring, list(reversed(canvas_ring))):
        start = min(range(4), key=lambda i: ring[i][0] + ring[i][1])
        candidates.append(_rotate_points(ring, start))
    return max(candidates, key=_score_ordered_quad)


def _solve_perspective_coeffs(
    dst_points: list[tuple[float, float]],
    src_points: list[tuple[float, float]],
) -> tuple[float, float, float, float, float, float, float, float] | None:
    if len(dst_points) != 4 or len(src_points) != 4:
        return None
    rows: list[list[float]] = []
    values: list[float] = []
    for (xd, yd), (xs, ys) in zip(dst_points, src_points):
        rows.append([xd, yd, 1.0, 0.0, 0.0, 0.0, -xs * xd, -xs * yd])
        values.append(xs)
        rows.append([0.0, 0.0, 0.0, xd, yd, 1.0, -ys * xd, -ys * yd])
        values.append(ys)
    try:
        matrix = np.asarray(rows, dtype=np.float64)
        vector = np.asarray(values, dtype=np.float64)
        solved = np.linalg.solve(matrix, vector)
    except Exception:
        return None
    return tuple(float(x) for x in solved.tolist())


def _paste_tile_projective(
    canvas: Image.Image,
    tile_img: Image.Image,
    dst_quad: list[tuple[float, float]],
) -> bool:
    if len(dst_quad) != 4:
        return False
    canvas_w, canvas_h = canvas.size
    xs = [p[0] for p in dst_quad]
    ys = [p[1] for p in dst_quad]
    x0 = max(0, int(math.floor(min(xs))))
    y0 = max(0, int(math.floor(min(ys))))
    x1 = min(canvas_w, int(math.ceil(max(xs))))
    y1 = min(canvas_h, int(math.ceil(max(ys))))
    if x1 <= x0 or y1 <= y0:
        return False

    local_quad = [(x - x0, y - y0) for (x, y) in dst_quad]
    src_quad = [
        (0.0, 0.0),
        (float(max(1, tile_img.width - 1)), 0.0),
        (float(max(1, tile_img.width - 1)), float(max(1, tile_img.height - 1))),
        (0.0, float(max(1, tile_img.height - 1))),
    ]
    coeffs = _solve_perspective_coeffs(local_quad, src_quad)
    if coeffs is None:
        return False

    patch_w = x1 - x0
    patch_h = y1 - y0
    warped = tile_img.transform(
        (patch_w, patch_h),
        Image.Transform.PERSPECTIVE,
        coeffs,
        resample=Image.Resampling.BILINEAR,
    )
    mask = Image.new("L", (patch_w, patch_h), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(local_quad, fill=255)
    canvas.paste(warped, (x0, y0), mask)
    return True


def _build_selected_extent_frame(
    frame: dict[str, Any],
    viewport_bounds: tuple[float, float, float, float],
    canvas_size: tuple[int, int],
    downloader,
):
    vx0, vy0, vx1, vy1 = viewport_bounds
    view_w = max(1e-9, vx1 - vx0)
    view_h = max(1e-9, vy1 - vy0)
    canvas_w, canvas_h = canvas_size

    canvas = Image.new("RGB", (canvas_w, canvas_h), (7, 11, 16))
    pasted_count = 0
    projective_count = 0
    bbox_count = 0
    for tile in frame.get("tiles", []):
        tile_bounds = _geometry_bounds(tile.get("geometry"))
        if not tile_bounds:
            continue
        tx0, ty0, tx1, ty1 = tile_bounds

        ix0 = max(vx0, tx0)
        iy0 = max(vy0, ty0)
        ix1 = min(vx1, tx1)
        iy1 = min(vy1, ty1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue

        source_url = (tile.get("url") or "").strip()
        if not source_url:
            continue
        try:
            image_bytes = downloader(source_url)
            tile_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:
            continue
        if tile_img.width < 2 or tile_img.height < 2:
            continue

        dst_quad = _ordered_tile_quad_canvas_points(tile.get("geometry"), viewport_bounds, canvas_size)
        if dst_quad and _paste_tile_projective(canvas, tile_img, dst_quad):
            pasted_count += 1
            projective_count += 1
            continue

        tile_w_geo = max(1e-9, tx1 - tx0)
        tile_h_geo = max(1e-9, ty1 - ty0)
        left_ratio = (ix0 - tx0) / tile_w_geo
        right_ratio = (ix1 - tx0) / tile_w_geo
        top_ratio = (ty1 - iy1) / tile_h_geo
        bottom_ratio = (ty1 - iy0) / tile_h_geo

        src_x0 = max(0, min(tile_img.width - 1, int(round(left_ratio * tile_img.width))))
        src_x1 = max(src_x0 + 1, min(tile_img.width, int(round(right_ratio * tile_img.width))))
        src_y0 = max(0, min(tile_img.height - 1, int(round(top_ratio * tile_img.height))))
        src_y1 = max(src_y0 + 1, min(tile_img.height, int(round(bottom_ratio * tile_img.height))))
        if src_x1 <= src_x0 or src_y1 <= src_y0:
            continue

        dst_x0 = int(round(((ix0 - vx0) / view_w) * canvas_w))
        dst_x1 = int(round(((ix1 - vx0) / view_w) * canvas_w))
        dst_y0 = int(round(((vy1 - iy1) / view_h) * canvas_h))
        dst_y1 = int(round(((vy1 - iy0) / view_h) * canvas_h))
        if dst_x1 <= dst_x0 or dst_y1 <= dst_y0:
            continue

        src_crop = tile_img.crop((src_x0, src_y0, src_x1, src_y1))
        dst_w = max(1, dst_x1 - dst_x0)
        dst_h = max(1, dst_y1 - dst_y0)
        resized = src_crop.resize((dst_w, dst_h), resample=Image.Resampling.BILINEAR)
        canvas.paste(resized, (dst_x0, dst_y0))
        pasted_count += 1
        bbox_count += 1

    if pasted_count == 0:
        logger.warning(
            "mp4_frame_compose frame_id=%s pasted=0 projective=%s bbox=%s tiles=%s",
            frame.get("frame_id") or "",
            projective_count,
            bbox_count,
            len(frame.get("tiles", [])),
        )
        return None
    logger.info(
        "mp4_frame_compose frame_id=%s pasted=%s projective=%s bbox=%s tiles=%s",
        frame.get("frame_id") or "",
        pasted_count,
        projective_count,
        bbox_count,
        len(frame.get("tiles", [])),
    )
    return canvas


def _build_capture_mosaic_frame(group_items: list[dict[str, Any]], capture_datetime: str | None, downloader):
    if not group_items:
        return None

    geometries = []
    # Limit tiles per capture to keep runtime bounded for interactive workflows.
    for item in group_items[:12]:
        try:
            if item.get("geometry"):
                geometries.append(shape(item["geometry"]))
        except Exception:
            continue
    if not geometries:
        return None

    union_minx = min(g.bounds[0] for g in geometries)
    union_miny = min(g.bounds[1] for g in geometries)
    union_maxx = max(g.bounds[2] for g in geometries)
    union_maxy = max(g.bounds[3] for g in geometries)
    width_span = max(1e-9, union_maxx - union_minx)
    height_span = max(1e-9, union_maxy - union_miny)

    canvas_w = 1280
    canvas_h = 720
    canvas = Image.new("RGB", (canvas_w, canvas_h), (8, 14, 22))

    for item in group_items:
        assets = item.get("assets", {})
        source_url = assets.get("visual") or assets.get("analytic") or assets.get("preview") or assets.get("thumbnail")
        if not source_url:
            continue

        try:
            image_bytes = downloader(source_url)
            tile_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:
            continue

        try:
            tile_geom = shape(item["geometry"])
            minx, miny, maxx, maxy = tile_geom.bounds
        except Exception:
            continue

        x0 = int(((minx - union_minx) / width_span) * canvas_w)
        x1 = int(((maxx - union_minx) / width_span) * canvas_w)
        y0 = int(((union_maxy - maxy) / height_span) * canvas_h)
        y1 = int(((union_maxy - miny) / height_span) * canvas_h)
        if x1 <= x0 or y1 <= y0:
            continue

        region_w = max(1, x1 - x0)
        region_h = max(1, y1 - y0)
        tile_img = tile_img.resize((region_w, region_h))
        canvas.paste(tile_img, (x0, y0))

    _draw_frame_label(canvas, capture_datetime)
    return canvas


def _draw_frame_label(canvas: Image.Image, capture_datetime: str | None):
    draw = ImageDraw.Draw(canvas)
    text = f"Capture: {capture_datetime or 'unknown'}"
    try:
        font = ImageFont.truetype("Arial.ttf", 34)
    except Exception:
        font = ImageFont.load_default()

    x, y = 20, 14
    # shadow/stroke for readability
    for ox, oy in [(-1, -1), (1, -1), (-1, 1), (1, 1), (0, 0)]:
        fill = (0, 0, 0) if (ox, oy) != (0, 0) else (255, 255, 255)
        draw.text((x + ox, y + oy), text, font=font, fill=fill)


def _draw_datetime_label(canvas: Image.Image, capture_datetime: str | None):
    draw = ImageDraw.Draw(canvas)
    text = capture_datetime or "unknown datetime"
    try:
        font = ImageFont.truetype("Arial.ttf", 42)
    except Exception:
        font = ImageFont.load_default()

    x, y = 20, 16
    for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, 0)]:
        fill = (0, 0, 0) if (ox, oy) != (0, 0) else (255, 255, 255)
        draw.text((x + ox, y + oy), text, font=font, fill=fill)


def compare_pair(before_item: dict[str, Any], after_item: dict[str, Any]) -> dict[str, Any]:
    before_url = before_item["assets"].get("preview") or before_item["assets"].get("thumbnail") or before_item["assets"].get("visual")
    after_url = after_item["assets"].get("preview") or after_item["assets"].get("thumbnail") or after_item["assets"].get("visual")

    return {
        "before": {
            "id": before_item["id"],
            "datetime": before_item.get("datetime"),
            "url": before_url,
        },
        "after": {
            "id": after_item["id"],
            "datetime": after_item.get("datetime"),
            "url": after_url,
        },
    }


def _load_annotations(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def list_annotations(aoi_name: str | None = None) -> dict[str, Any]:
    payload = _load_annotations(settings.annotations_file)
    if not aoi_name:
        return payload

    features = [f for f in payload.get("features", []) if f.get("properties", {}).get("aoi_name") == aoi_name]
    return {"type": "FeatureCollection", "features": features}


def save_annotation(note: str, geometry: dict[str, Any], label: str = "observation", aoi_name: str = "default") -> dict[str, Any]:
    settings.annotations_file.parent.mkdir(parents=True, exist_ok=True)
    payload = _load_annotations(settings.annotations_file)

    feature = {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "id": str(uuid.uuid4()),
            "aoi_name": aoi_name,
            "label": label,
            "note": note,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    }

    payload.setdefault("features", []).append(feature)
    with open(settings.annotations_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    return feature
