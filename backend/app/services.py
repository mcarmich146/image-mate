from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import base64
import io
import json
import statistics
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import shape

from .config import settings
from .satellogic_client import normalize_item


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
