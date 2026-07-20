#!/usr/bin/env python3
"""Probe streamed tile edges using the same URL builder as the QGIS plugin."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

# From qgis_plugin/test/streaming_gap_probe.py -> workspace root
workspace_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(workspace_root))

# Load .env for credentials and overrides (matches other test tools)
try:
    from dotenv import load_dotenv

    dotenv_path = workspace_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
except Exception:
    pass

from backend.app.workbench import _tile_xy_float, bounds_from_geometry
from qgis_plugin.image_mate_qgis_plugin.services.source_service import SourceService
from qgis_plugin.image_mate_qgis_plugin.services.streaming_utils import (
    build_satellogic_xyz_url,
    satellogic_item_cog_source_url,
)

try:
    from PIL import Image
    import io

    HAS_PIL = True
except Exception:
    HAS_PIL = False


@dataclass
class MockSettings:
    backend_api_base_url: str = os.getenv("BACKEND_API_BASE_URL", "http://localhost:8000")
    satellogic_auth_mode: str = os.getenv("SATELLOGIC_AUTH_MODE", "oauth_client_credentials")
    satellogic_contract_id: str = os.getenv("SATELLOGIC_CONTRACT_ID", "")
    satellogic_stac_url: str = os.getenv("SATELLOGIC_STAC_URL", "https://api.satellogic.com/archive/stac")
    satellogic_authcfg_id: str = os.getenv("SATELLOGIC_AUTHCFG_ID", "")
    cdse_enabled: bool = False
    cdse_stac_url: str = os.getenv("CDSE_STAC_URL", "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0")
    cdse_wmts_base_url: str = os.getenv("CDSE_WMTS_BASE_URL", "https://sh.dataspace.copernicus.eu/ogc/wmts")
    cdse_wmts_instance_id: str = os.getenv("CDSE_WMTS_INSTANCE_ID", "")
    cdse_wmts_layer_id: str = os.getenv("CDSE_WMTS_LAYER_ID", "TRUE-COLOR")
    cdse_authcfg_id: str = os.getenv("CDSE_AUTHCFG_ID", "")


def _latest_log_path() -> Path | None:
    base = Path.home() / "AppData" / "Roaming" / "QGIS" / "QGIS3" / "image_mate_logs"
    if not base.exists():
        return None
    logs = sorted(base.glob("image_mate_qgis_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _extract_last_payload(log_path: Path) -> dict[str, Any] | None:
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    marker = "Full request payload:"
    idx = text.rfind(marker)
    if idx == -1:
        return None
    payload_text = text[idx + len(marker) :].strip()
    if not payload_text.startswith("{"):
        payload_text = payload_text[payload_text.find("{") :]
    depth = 0
    start = payload_text.find("{")
    if start == -1:
        return None
    end = None
    for i, ch in enumerate(payload_text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return None
    try:
        return json.loads(payload_text[start:end])
    except Exception:
        return None


def _tile_bounds_for_bounds(bounds: tuple[float, float, float, float], zoom: int) -> tuple[int, int, int, int] | None:
    minx, miny, maxx, maxy = bounds
    x_min_f, y_min_f = _tile_xy_float(maxy, minx, zoom)
    x_max_f, y_max_f = _tile_xy_float(miny, maxx, zoom)
    x0 = int(math.floor(min(x_min_f, x_max_f)))
    x1 = int(math.ceil(max(x_min_f, x_max_f)) - 1)
    y0 = int(math.floor(min(y_min_f, y_max_f)))
    y1 = int(math.ceil(max(y_min_f, y_max_f)) - 1)
    n = 2 ** zoom
    x0 = max(0, min(n - 1, x0))
    x1 = max(0, min(n - 1, x1))
    y0 = max(0, min(n - 1, y0))
    y1 = max(0, min(n - 1, y1))
    return x0, x1, y0, y1


def _tile_bounds_for_geometry(geometry: dict[str, Any], zoom: int) -> tuple[int, int, int, int] | None:
    bounds = bounds_from_geometry(geometry)
    if not bounds:
        return None
    return _tile_bounds_for_bounds(bounds, zoom)


def _capture_group_key(item: dict[str, Any]) -> str:
    props = item.get("properties", {}) if isinstance(item, dict) else {}
    outcome = props.get("satl:outcome_id") or props.get("outcome_id") or item.get("outcome_id")
    if outcome:
        return f"outcome:{outcome}"

    item_id = str(item.get("id") or "")
    match = re.search(r"(\d{8}_\d{6}_\d+_SN\d+)", item_id)
    if match:
        return f"capture:{match.group(1)}"

    return f"fallback:{props.get('datetime') or item_id}"


def _bounds_intersect(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def _collect_capture_group_items(items: list[dict[str, Any]], target_item: dict[str, Any]) -> list[dict[str, Any]]:
    if not items or not isinstance(target_item, dict):
        return []
    key = _capture_group_key(target_item)
    grouped = [row for row in items if _capture_group_key(row) == key]
    return grouped if grouped else [target_item]


def _union_bounds(items: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    bounds_list = []
    for row in items:
        geom = row.get("geometry") if isinstance(row, dict) else None
        if not isinstance(geom, dict):
            continue
        bounds = bounds_from_geometry(geom)
        if bounds:
            bounds_list.append(bounds)
    if not bounds_list:
        return None
    minx = min(b[0] for b in bounds_list)
    miny = min(b[1] for b in bounds_list)
    maxx = max(b[2] for b in bounds_list)
    maxy = max(b[3] for b in bounds_list)
    return (minx, miny, maxx, maxy)


def _edge_miss_summary(results: dict[str, Any], x0: int, x1: int, y0: int, y1: int) -> dict[str, Any]:
    missing = results.get("missing") or []
    summary: dict[str, Any] = {"missing_edges": [], "only_min_edges": False}
    if not missing:
        return summary

    missing_edges = []
    only_min_edges = True
    for entry in missing:
        edge = entry.get("edge")
        tiles = entry.get("tiles") or []
        missing_edges.append(edge)
        if edge == "left":
            if not all(tile[0] == x0 for tile in tiles):
                only_min_edges = False
        elif edge == "right":
            if not all(tile[0] == x1 for tile in tiles):
                only_min_edges = False
        elif edge == "top":
            if not all(tile[1] == y0 for tile in tiles):
                only_min_edges = False
        elif edge == "bottom":
            if not all(tile[1] == y1 for tile in tiles):
                only_min_edges = False
        else:
            only_min_edges = False
    summary["missing_edges"] = missing_edges
    summary["only_min_edges"] = only_min_edges
    return summary


def _tile_index_diagnostics(bounds: tuple[float, float, float, float], zoom: int) -> dict[str, Any]:
    minx, miny, maxx, maxy = bounds
    x_min_f, y_min_f = _tile_xy_float(maxy, minx, zoom)
    x_max_f, y_max_f = _tile_xy_float(miny, maxx, zoom)
    return {
        "x_min_float": x_min_f,
        "x_max_float": x_max_f,
        "y_min_float": y_min_f,
        "y_max_float": y_max_f,
        "x_min_floor": int(math.floor(min(x_min_f, x_max_f))),
        "x_min_ceil": int(math.ceil(min(x_min_f, x_max_f))),
        "x_max_floor": int(math.floor(max(x_min_f, x_max_f))),
        "x_max_ceil_minus_1": int(math.ceil(max(x_min_f, x_max_f)) - 1),
        "y_min_floor": int(math.floor(min(y_min_f, y_max_f))),
        "y_min_ceil": int(math.ceil(min(y_min_f, y_max_f))),
        "y_max_floor": int(math.floor(max(y_min_f, y_max_f))),
        "y_max_ceil_minus_1": int(math.ceil(max(y_min_f, y_max_f)) - 1),
    }


def _is_empty_tile(resp: requests.Response) -> bool:
    if resp.headers.get("X-Tile-Empty") == "1":
        return True
    if resp.status_code != 200:
        return True
    if not HAS_PIL:
        return False
    try:
        with Image.open(io.BytesIO(resp.content)) as img:
            rgba = img.convert("RGBA")
            extrema = rgba.getextrema()
            if len(extrema) == 4 and extrema[3][1] == 0:
                return True
    except Exception:
        return False
    return False


def _build_tile_url(template: str, z: int, x: int, y: int) -> str:
    return template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))


def _edge_scan(
    *,
    tile_url_template: str,
    zoom: int,
    x0: int,
    x1: int,
    y0: int,
    y1: int,
    max_tiles: int,
    auth_headers: dict[str, str] | None,
    timeout: int,
) -> dict[str, Any]:
    edges = {
        "top": [(x, y0) for x in range(x0, x1 + 1)],
        "bottom": [(x, y1) for x in range(x0, x1 + 1)],
        "left": [(x0, y) for y in range(y0, y1 + 1)],
        "right": [(x1, y) for y in range(y0, y1 + 1)],
    }
    results: dict[str, Any] = {"edges": {}, "missing": []}
    for edge_name, tiles in edges.items():
        trimmed = tiles[: max_tiles or len(tiles)]
        misses = []
        for x, y in trimmed:
            url = _build_tile_url(tile_url_template, zoom, x, y)
            resp = requests.get(url, headers=auth_headers or {}, timeout=timeout)
            empty = _is_empty_tile(resp)
            results.setdefault("edges", {}).setdefault(edge_name, []).append(
                {
                    "z": zoom,
                    "x": x,
                    "y": y,
                    "status": resp.status_code,
                    "empty": empty,
                    "url": url,
                }
            )
            if empty:
                misses.append((x, y))
        if misses:
            results["missing"].append({"edge": edge_name, "tiles": misses})
    return results


def _center_probe(
    *,
    tile_url_template: str,
    zoom: int,
    x0: int,
    x1: int,
    y0: int,
    y1: int,
    auth_headers: dict[str, str] | None,
    timeout: int,
) -> dict[str, Any]:
    x_center = int((x0 + x1) // 2)
    y_center = int((y0 + y1) // 2)
    url = _build_tile_url(tile_url_template, zoom, x_center, y_center)
    resp = requests.get(url, headers=auth_headers or {}, timeout=timeout)
    empty = _is_empty_tile(resp)
    return {
        "z": zoom,
        "x": x_center,
        "y": y_center,
        "status": resp.status_code,
        "empty": empty,
        "url": url,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe streamed tiles using plugin URL builder")
    parser.add_argument("--log", help="Path to image_mate_qgis_*.log")
    parser.add_argument("--item-id", help="Specific item id to test")
    parser.add_argument("--zoom", type=int, default=15, help="Zoom level to probe")
    parser.add_argument("--stream-base", default="", help="Stream base URL (backend or local proxy)")
    parser.add_argument("--local-proxy", action="store_true", help="Use local proxy tile path")
    parser.add_argument("--max-tiles", type=int, default=40, help="Max tiles per edge to request")
    parser.add_argument("--timeout", type=int, default=25, help="HTTP timeout per tile")
    parser.add_argument("--output", default="stream_gap_report.json", help="Output report path")
    parser.add_argument("--auth", action="store_true", help="Attach Satellogic auth headers")
    parser.add_argument("--use-item-geometry", action="store_true", help="Use selected item geometry instead of search AOI")
    parser.add_argument("--buffer", type=int, default=1, help="Override tile buffer parameter")
    parser.add_argument("--probe-center", action="store_true", help="Also probe the center tile")
    parser.add_argument("--decode-query", action="store_true", help="Decode %26 into & for direct HTTP requests")
    parser.add_argument("--use-capture-group", action="store_true", help="Use capture group sources")
    parser.add_argument("--use-aoi-filter", action="store_true", help="Filter capture group items by AOI bounds")
    parser.add_argument("--items-cache", default="stream_gap_items_cache.json", help="Cache file for search results")
    args = parser.parse_args()

    log_path = Path(args.log) if args.log else _latest_log_path()
    if not log_path or not log_path.exists():
        raise SystemExit("No QGIS log found. Use --log to specify a log file.")

    payload = _extract_last_payload(log_path)
    if not payload:
        raise SystemExit("Failed to parse search payload from log.")

    source_id = str(payload.get("source_id") or "").strip().lower()
    if source_id != "satellogic":
        raise SystemExit(f"Only satellogic is supported (got {source_id}).")

    svc = SourceService(MockSettings())
    items = []
    cache_path = Path(args.items_cache)
    try:
        items = svc.search(payload) or []
        if items:
            cache_path.write_text(json.dumps(items, indent=2), encoding="utf-8")
    except Exception as exc:
        if cache_path.exists():
            try:
                items = json.loads(cache_path.read_text(encoding="utf-8"))
                print(f"Search failed ({exc}); using cached items from {cache_path}.")
            except Exception:
                items = []
        else:
            items = []

    if not items:
        raise SystemExit("Search returned no items (and no cache available).")

    item = None
    if args.item_id:
        for row in items:
            if str(row.get("id") or "") == args.item_id:
                item = row
                break
    if item is None:
        item = items[0]

    source_items = [item]
    if args.use_capture_group:
        group_items = _collect_capture_group_items(items, item)
        if args.use_aoi_filter:
            aoi_bounds = bounds_from_geometry(payload.get("geometry", {}))
            if aoi_bounds:
                group_items = [
                    row
                    for row in group_items
                    if bounds_from_geometry(row.get("geometry", {}))
                    and _bounds_intersect(bounds_from_geometry(row.get("geometry", {})), aoi_bounds)
                ]
        source_items = group_items if group_items else [item]

    sources = []
    for row in source_items:
        source = satellogic_item_cog_source_url(row)
        if source:
            sources.append(source)
    if not sources:
        raise SystemExit("Selected item has no COG source URL.")

    stream_base = args.stream_base or str(payload.get("backend_api_base_url") or "").strip()
    if not stream_base:
        stream_base = os.getenv("BACKEND_API_BASE_URL", "http://localhost:8000")

    contract_id = str(payload.get("contract_id") or "").strip() or None
    tile_template = build_satellogic_xyz_url(
        stream_base=stream_base,
        sources=sources,
        scale=1,
        contract_id=contract_id,
        is_local_proxy=bool(args.local_proxy),
        tile_matrix_set_id="WebMercatorQuad",
        image_format="png",
        buffer_size=int(args.buffer),
        render_layer="raw",
        bands=(1, 2, 3),
    )
    if not tile_template:
        raise SystemExit("Failed to build tile URL template.")
    if args.decode_query:
        tile_template = tile_template.replace("%26", "&")

    geometry = item.get("geometry") if args.use_item_geometry else payload.get("geometry")
    if not isinstance(geometry, dict):
        raise SystemExit("Geometry is missing for tile bounds.")

    tile_bounds = _tile_bounds_for_geometry(geometry, int(args.zoom))
    if not tile_bounds:
        raise SystemExit("Failed to compute tile bounds for geometry.")

    group_bounds = _union_bounds(source_items)
    group_tile_bounds = _tile_bounds_for_bounds(group_bounds, int(args.zoom)) if group_bounds else None
    geometry_bounds = bounds_from_geometry(geometry)

    x0, x1, y0, y1 = tile_bounds
    auth_headers = None
    if args.auth:
        sat_client = getattr(svc, "_manager", None)
        sat_client = getattr(sat_client, "satellogic_client", None) if sat_client else None
        if sat_client is not None:
            auth_headers = sat_client.auth_headers(contract_id=contract_id)

    started = time.time()
    results = _edge_scan(
        tile_url_template=tile_template,
        zoom=int(args.zoom),
        x0=x0,
        x1=x1,
        y0=y0,
        y1=y1,
        max_tiles=int(args.max_tiles or 0),
        auth_headers=auth_headers,
        timeout=int(args.timeout),
    )
    if args.probe_center:
        results["center"] = _center_probe(
            tile_url_template=tile_template,
            zoom=int(args.zoom),
            x0=x0,
            x1=x1,
            y0=y0,
            y1=y1,
            auth_headers=auth_headers,
            timeout=int(args.timeout),
        )
    elapsed = round(time.time() - started, 2)

    report = {
        "log": str(log_path),
        "item_id": str(item.get("id") or ""),
        "collection": str(item.get("collection") or ""),
        "stream_base": stream_base,
        "tile_template": tile_template,
        "zoom": int(args.zoom),
        "buffer": int(args.buffer),
        "tile_bounds": {"x0": x0, "x1": x1, "y0": y0, "y1": y1},
        "capture_group": _capture_group_key(item),
        "source_count": len(sources),
        "source_items": [str(row.get("id") or "") for row in source_items],
        "geometry_bounds": {
            "minx": geometry_bounds[0],
            "miny": geometry_bounds[1],
            "maxx": geometry_bounds[2],
            "maxy": geometry_bounds[3],
        }
        if geometry_bounds
        else None,
        "geometry_tile_diag": _tile_index_diagnostics(geometry_bounds, int(args.zoom)) if geometry_bounds else None,
        "group_bounds": {
            "minx": group_bounds[0],
            "miny": group_bounds[1],
            "maxx": group_bounds[2],
            "maxy": group_bounds[3],
        }
        if group_bounds
        else None,
        "group_tile_diag": _tile_index_diagnostics(group_bounds, int(args.zoom)) if group_bounds else None,
        "group_tile_bounds": {
            "x0": group_tile_bounds[0],
            "x1": group_tile_bounds[1],
            "y0": group_tile_bounds[2],
            "y1": group_tile_bounds[3],
        }
        if group_tile_bounds
        else None,
        "elapsed_seconds": elapsed,
        "results": results,
        "edge_miss_summary": _edge_miss_summary(results, x0, x1, y0, y1),
    }
    output_path = Path(args.output)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    missing = results.get("missing") or []
    print(f"Probe complete in {elapsed}s | missing_edges={len(missing)} | report={output_path}")
    if missing:
        for entry in missing:
            print(f"  - {entry['edge']}: {len(entry['tiles'])} empty tiles")
    if args.probe_center and results.get("center"):
        center = results["center"]
        status = center.get("status")
        empty = center.get("empty")
        print(f"  center: status={status} empty={empty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
