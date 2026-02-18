#!/usr/bin/env python3
"""
WMS/Tile Search Diagnostic Tool
Performs actual searches and downloads to diagnose collection mixing, GSD inconsistencies, and tile connectivity issues.
"""

import sys
import math
import json
import os
import re
import io
from pathlib import Path
from typing import Any, List, Dict, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import argparse
from urllib.parse import urlencode, urlparse, parse_qs

import requests

# Add backend to path
# From qgis_plugin/test/wms_tester/wms_diagnostic.py -> workspace root
workspace_root = Path(__file__).parent.parent.parent.parent
backend_path = workspace_root / "backend"
sys.path.insert(0, str(backend_path))

# Explicitly load .env file from workspace root
try:
    from dotenv import load_dotenv
    dotenv_path = workspace_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
        print(f"Loaded environment from: {dotenv_path}")
    else:
        print(f"WARNING: .env file not found at {dotenv_path}")
except ImportError:
    print("WARNING: python-dotenv not installed, environment variables may not be loaded")

from app.workbench import bounds_from_geometry
from app.satellogic_client import SatellogicClient
from app.config import settings

try:
    from PIL import Image
    import numpy as np
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("WARNING: PIL/numpy not available - image analysis will be limited")


def create_test_aoi(center_lat, center_lon, size_km=10):
    """Create a test AOI box around a center point."""
    # Rough conversion: 1 degree lat ~ 111km, 1 degree lon ~ 111km * cos(lat)
    lat_offset = (size_km / 2) / 111.0
    lon_offset = (size_km / 2) / (111.0 * math.cos(math.radians(center_lat)))
    
    return {
        "type": "Polygon",
        "coordinates": [[
            [center_lon - lon_offset, center_lat - lat_offset],  # SW
            [center_lon + lon_offset, center_lat - lat_offset],  # SE
            [center_lon + lon_offset, center_lat + lat_offset],  # NE
            [center_lon - lon_offset, center_lat + lat_offset],  # NW
            [center_lon - lon_offset, center_lat - lat_offset],  # close
        ]]
    }


def perform_search(client: SatellogicClient, geometry: dict, collection_id: str, contract_id: str = None) -> List[dict]:
    """Perform a search query and return results."""
    print(f"\n{'='*80}")
    print(f"PERFORMING SEARCH")
    print(f"{'='*80}")
    print(f"Collection: {collection_id}")
    
    today = datetime.now()
    start_date = (today - timedelta(days=60)).isoformat() + "Z"
    end_date = today.isoformat() + "Z"
    
    print(f"Date range: {start_date[:10]} to {end_date[:10]}")
    
    try:
        results = client.search(
            geometry=geometry,
            start_date=start_date,
            end_date=end_date,
            collection_id=collection_id,
            contract_id=contract_id,
            limit=100,
            max_cloud_cover=None,
            satellite_name=None,
            min_gsd=None,
            max_gsd=None,
        )
        
        print(f"Search returned {len(results)} items")
        return results
    except Exception as e:
        print(f"ERROR: Search failed: {e}")
        import traceback
        traceback.print_exc()
        return []


def _is_strip_collection(collection_id: str) -> bool:
    return str(collection_id or "").strip().lower().replace("_", "-") in {"quickview-visual-thumb"}


def _capture_group_key(item: dict) -> str:
    props = item.get("properties", {})
    outcome = props.get("satl:outcome_id") or props.get("outcome_id")
    if outcome:
        return f"outcome:{outcome}"

    item_id = item.get("id", "") or ""
    match = re.search(r"(\d{8}_\d{6}_\d+_SN\d+)", item_id)
    if match:
        return f"capture:{match.group(1)}"

    return f"fallback:{props.get('datetime') or item_id}"


def _item_cog_source_url(item: dict) -> str:
    assets = item.get("assets") or {}
    for key in ("visual_fullres", "visual", "analytic"):
        asset = assets.get(key)
        href = asset.get("href") if isinstance(asset, dict) else None
        if not href:
            continue
        value = str(href).strip()
        if value.startswith("s3://"):
            return value
        try:
            parsed = urlparse(value)
            source = str((parse_qs(parsed.query or "").get("s") or [""])[0]).strip()
            if source.startswith("s3://"):
                return source
        except Exception:
            return value
        return value
    return ""


def _latlon_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return x, y


def _tile_range_for_bounds(bounds: tuple[float, float, float, float], zoom: int) -> tuple[int, int, int, int]:
    minx, miny, maxx, maxy = bounds
    x_min, y_min = _latlon_to_tile(minx, maxy, zoom)
    x_max, y_max = _latlon_to_tile(maxx, miny, zoom)
    return x_min, x_max, y_min, y_max


def _tile_is_empty(image_bytes: bytes) -> bool:
    if not HAS_PIL:
        return False
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            rgba = img.convert("RGBA")
            extrema = rgba.getextrema()
            if len(extrema) == 4:
                alpha_min, alpha_max = extrema[3]
                if alpha_max == 0:
                    return True
            # Fallback: treat fully black as empty
            if all(channel_extrema[1] == 0 for channel_extrema in extrema[:3]):
                return True
    except Exception:
        return False
    return False


def _fetch_tile(
    client: SatellogicClient,
    base_url: str,
    contract_id: str | None,
    zoom: int,
    x: int,
    y: int,
    sources: list[str],
    scale: int = 1,
    buffer_size: int = 1,
    tile_matrix_set: str = "WebMercatorQuad",
    render_layer: str | None = "raw",
    bands: list[str] | None = None,
) -> tuple[bool, str]:
    params: list[tuple[str, str]] = [
        ("tileMatrixSetId", tile_matrix_set),
        ("format", "png"),
        ("scale", str(scale)),
        ("buffer", str(buffer_size)),
    ]
    if render_layer:
        params.append(("render_layer", render_layer))
    if bands:
        for band in bands:
            params.append(("bidx", str(band)))
    for source in sources:
        if source:
            params.append(("url", source))
    if contract_id:
        params.append(("contract_id", contract_id))

    query = urlencode(params, doseq=True, safe=":/")
    url = f"{base_url.rstrip('/')}/raster/cog/tiles/{zoom}/{x}/{y}?{query}"
    headers = client.auth_headers(contract_id=contract_id)
    try:
        resp = requests.get(url, headers=headers, timeout=20)
    except Exception as exc:
        return False, f"error:{exc.__class__.__name__}"
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}"
    if _tile_is_empty(resp.content):
        return False, "empty"
    return True, "ok"


def _edge_tile_debug(
    client: SatellogicClient,
    results: List[dict],
    contract_id: str | None,
    zoom: int,
    include_multi: bool = False,
    include_variants: bool = False,
    edge_tiles: int = 4,
) -> Dict[str, Any]:
    print(f"\n{'='*80}")
    print("EDGE TILE DEBUG")
    print(f"{'='*80}")

    grouped: dict[str, list[dict]] = {}
    for item in results:
        key = _capture_group_key(item)
        grouped.setdefault(key, []).append(item)

    target_group = None
    for key, items in grouped.items():
        if len(items) >= 4:
            target_group = (key, items)
            break
    if target_group is None:
        print("No capture group with >= 4 tiles found for edge debug")
        return {"skipped": True}

    group_key, group_items = target_group
    print(f"Using capture group: {group_key} ({len(group_items)} tiles)")

    tiles = []
    for item in group_items:
        geom = item.get("geometry")
        if not isinstance(geom, dict):
            continue
        bounds = bounds_from_geometry(geom)
        if not bounds:
            continue
        minx, miny, maxx, maxy = bounds
        cx = (minx + maxx) / 2.0
        cy = (miny + maxy) / 2.0
        tiles.append({
            "item": item,
            "bounds": bounds,
            "center": (cx, cy),
        })

    if len(tiles) < 4:
        print("Not enough tiles with geometry in target group")
        return {"skipped": True}

    group_minx = min(t["bounds"][0] for t in tiles)
    group_miny = min(t["bounds"][1] for t in tiles)
    group_maxx = max(t["bounds"][2] for t in tiles)
    group_maxy = max(t["bounds"][3] for t in tiles)
    group_cx = (group_minx + group_maxx) / 2.0
    group_cy = (group_miny + group_maxy) / 2.0

    quadrants = {"A": None, "B": None, "C": None, "D": None}
    for tile in tiles:
        cx, cy = tile["center"]
        if cx <= group_cx and cy >= group_cy:
            quadrants["A"] = tile
        elif cx > group_cx and cy >= group_cy:
            quadrants["B"] = tile
        elif cx <= group_cx and cy < group_cy:
            quadrants["C"] = tile
        else:
            quadrants["D"] = tile

    sources_all = [
        _item_cog_source_url(tile["item"]) for tile in quadrants.values() if tile is not None
    ]

    base_url = settings.satellogic_api_base_url
    results_out: dict[str, Any] = {"group": group_key, "zoom": zoom, "tiles": {}}

    labels = ["A", "B", "C", "D"]
    max_tiles = max(1, min(int(edge_tiles or 4), len(labels)))
    for label in labels[:max_tiles]:
        tile = quadrants.get(label)
        if tile is None:
            continue
        item = tile["item"]
        item_id = item.get("id")
        bounds = tile["bounds"]
        x_min, x_max, y_min, y_max = _tile_range_for_bounds(bounds, zoom)
        x_edge = x_max
        y_edge = y_max
        x_right = x_max + 1
        y_bottom = y_max + 1
        x_left = x_min - 1
        y_top = y_min - 1
        center_lon = (bounds[0] + bounds[2]) / 2.0
        center_lat = (bounds[1] + bounds[3]) / 2.0
        x_center, y_center = _latlon_to_tile(center_lon, center_lat, zoom)

        source = _item_cog_source_url(item)
        ok_single, status_single = _fetch_tile(
            client,
            base_url,
            contract_id,
            zoom,
            x_edge,
            y_edge,
            [source],
            buffer_size=1,
        )
        ok_single_b0, status_single_b0 = _fetch_tile(
            client,
            base_url,
            contract_id,
            zoom,
            x_edge,
            y_edge,
            [source],
            buffer_size=0,
        )
        _, status_center = _fetch_tile(
            client,
            base_url,
            contract_id,
            zoom,
            x_center,
            y_center,
            [source],
            buffer_size=1,
        )
        _, status_right = _fetch_tile(
            client,
            base_url,
            contract_id,
            zoom,
            x_right,
            y_edge,
            [source],
            buffer_size=1,
        )
        _, status_bottom = _fetch_tile(
            client,
            base_url,
            contract_id,
            zoom,
            x_edge,
            y_bottom,
            [source],
            buffer_size=1,
        )
        _, status_left = _fetch_tile(
            client,
            base_url,
            contract_id,
            zoom,
            x_left,
            y_edge,
            [source],
            buffer_size=1,
        )
        _, status_top = _fetch_tile(
            client,
            base_url,
            contract_id,
            zoom,
            x_edge,
            y_top,
            [source],
            buffer_size=1,
        )
        status_multi = "skipped"
        status_multi_b0 = "skipped"
        if include_multi:
            _, status_multi = _fetch_tile(
                client,
                base_url,
                contract_id,
                zoom,
                x_edge,
                y_edge,
                sources_all,
                buffer_size=1,
            )
            _, status_multi_b0 = _fetch_tile(
                client,
                base_url,
                contract_id,
                zoom,
                x_edge,
                y_edge,
                sources_all,
                buffer_size=0,
            )

        print(
            f"Tile {label} ({item_id}) edge z{zoom}/{x_edge}/{y_edge} "
            f"single={status_single} multi={status_multi} "
            f"single_b0={status_single_b0} multi_b0={status_multi_b0} "
            f"center={status_center} right+1={status_right} bottom+1={status_bottom} "
            f"left-1={status_left} top-1={status_top}"
        )

        results_out["tiles"][label] = {
            "id": item_id,
            "edge_tile": (zoom, x_edge, y_edge),
            "single": status_single,
            "multi": status_multi,
            "single_b0": status_single_b0,
            "multi_b0": status_multi_b0,
            "center": status_center,
            "right_plus_one": status_right,
            "bottom_plus_one": status_bottom,
            "left_minus_one": status_left,
            "top_minus_one": status_top,
        }

    if include_variants:
        sample = quadrants.get("A") or next((t for t in quadrants.values() if t), None)
        if sample is not None:
            item = sample["item"]
            item_id = item.get("id")
            bounds = sample["bounds"]
            x_min, x_max, y_min, y_max = _tile_range_for_bounds(bounds, zoom)
            x_edge = x_max
            y_edge = y_max
            source = _item_cog_source_url(item)

            variants = {
                "default": {
                    "tile_matrix_set": "WebMercatorQuad",
                    "render_layer": "raw",
                    "bands": ["1", "2", "3"],
                    "scale": 1,
                },
                "no_render_layer": {
                    "tile_matrix_set": "WebMercatorQuad",
                    "render_layer": None,
                    "bands": ["1", "2", "3"],
                    "scale": 1,
                },
                "no_bands": {
                    "tile_matrix_set": "WebMercatorQuad",
                    "render_layer": "raw",
                    "bands": None,
                    "scale": 1,
                },
                "scale2": {
                    "tile_matrix_set": "WebMercatorQuad",
                    "render_layer": "raw",
                    "bands": ["1", "2", "3"],
                    "scale": 2,
                },
            }

            results_out["variants"] = {"item": item_id, "edge_tile": (zoom, x_edge, y_edge), "tests": {}}
            for key, cfg in variants.items():
                _, status_v = _fetch_tile(
                    client,
                    base_url,
                    contract_id,
                    zoom,
                    x_edge,
                    y_edge,
                    [source],
                    buffer_size=1,
                    scale=cfg["scale"],
                    tile_matrix_set=cfg["tile_matrix_set"],
                    render_layer=cfg["render_layer"],
                    bands=cfg["bands"],
                )
                results_out["variants"]["tests"][key] = status_v
                print(f"Variant {key} edge z{zoom}/{x_edge}/{y_edge}: {status_v}")

    return results_out


def analyze_search_results(results: List[dict], collection_id: str) -> Dict[str, Any]:
    """Analyze search results for collection consistency and GSD."""
    print(f"\n{'='*80}")
    print(f"ANALYZING SEARCH RESULTS")
    print(f"{'='*80}")
    
    analysis = {
        "total_items": len(results),
        "collections": {},
        "issues": [],
    }
    
    if not results:
        print("No results to analyze")
        return analysis
    
    # Group by collection
    by_collection = defaultdict(list)
    for item in results:
        collection = item.get("collection", "unknown")
        by_collection[collection].append(item)
    
    print(f"\nResults grouped by collection:")
    for collection, items in sorted(by_collection.items()):
        print(f"  {collection}: {len(items)} items")
        
        # Analyze GSD within this collection
        gsds = []
        for item in items:
            props = item.get("properties", {})
            gsd = props.get("gsd")
            if gsd is not None:
                gsds.append(float(gsd))
        
        collection_info = {
            "count": len(items),
            "gsd_data": {},
        }
        
        if gsds:
            min_gsd = min(gsds)
            max_gsd = max(gsds)
            avg_gsd = sum(gsds) / len(gsds)
            print(f"    GSD range: {min_gsd:.6f} - {max_gsd:.6f} (avg: {avg_gsd:.6f})")
            
            collection_info["gsd_data"] = {
                "min": min_gsd,
                "max": max_gsd,
                "avg": avg_gsd,
                "range": max_gsd - min_gsd,
            }
            
            if not _is_strip_collection(collection_id):
                groups: dict[str, list[float]] = {}
                for item in items:
                    gsd = item.get("properties", {}).get("gsd")
                    if gsd is None:
                        continue
                    groups.setdefault(_capture_group_key(item), []).append(float(gsd))
                noisy_groups = 0
                for gsd_values in groups.values():
                    if gsd_values and max(gsd_values) - min(gsd_values) > 0.001:
                        noisy_groups += 1
                if noisy_groups:
                    issue = f"GSD varies within {noisy_groups} capture group(s) for {collection}"
                    print(f"    ⚠️  WARNING: {issue}")
                    analysis["issues"].append(issue)
        else:
            print(f"    No GSD data available")
        
        analysis["collections"][collection] = collection_info
    
    # Check for collection mixing issue
    if len(by_collection) > 1:
        issue = f"Search returned items from {len(by_collection)} different collections: {', '.join(sorted(by_collection.keys()))}"
        print(f"\n⚠️  WARNING: {issue}")
        print(f"   This indicates a collection filtering bug!")
        analysis["issues"].append(issue)
        analysis["collection_mixing"] = True
    else:
        analysis["collection_mixing"] = False
    
    # Analyze overall GSD
    all_gsds = []
    for item in results:
        props = item.get("properties", {})
        gsd = props.get("gsd")
        if gsd is not None:
            all_gsds.append(float(gsd))
    
    if all_gsds:
        print(f"\nOverall GSD statistics:")
        print(f"  Min: {min(all_gsds):.6f}")
        print(f"  Max: {max(all_gsds):.6f}")
        print(f"  Avg: {sum(all_gsds)/len(all_gsds):.6f}")
        print(f"  Range: {max(all_gsds) - min(all_gsds):.6f}")
        
        analysis["overall_gsd"] = {
            "min": min(all_gsds),
            "max": max(all_gsds),
            "avg": sum(all_gsds) / len(all_gsds),
            "range": max(all_gsds) - min(all_gsds),
        }
        
        if not _is_strip_collection(collection_id):
            groups: dict[str, list[float]] = {}
            for item in results:
                gsd = item.get("properties", {}).get("gsd")
                if gsd is None:
                    continue
                groups.setdefault(_capture_group_key(item), []).append(float(gsd))
            noisy_groups = 0
            for gsd_values in groups.values():
                if gsd_values and max(gsd_values) - min(gsd_values) > 0.01:
                    noisy_groups += 1
            if noisy_groups:
                issue = f"Significant GSD variation detected in {noisy_groups} capture group(s)"
                print(f"  ⚠️  WARNING: {issue}")
                analysis["issues"].append(issue)
    
    return analysis


def download_image(url: str, client: SatellogicClient, output_path: Path, contract_id: str = None) -> bool:
    """Download an image asset."""
    try:
        content = client.download_bytes(url, contract_id=contract_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return True
    except Exception as e:
        print(f"  ERROR downloading {output_path.name}: {e}")
        return False


def analyze_image_properties(image_path: Path) -> Dict[str, Any]:
    """Analyze image properties like size, resolution, etc."""
    if not HAS_PIL:
        return {"error": "PIL not available"}
    
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            mode = img.mode
            format = img.format
            
            # Try to get DPI/resolution info
            dpi = img.info.get('dpi', (None, None))
            
            info = {
                "width": width,
                "height": height,
                "mode": mode,
                "format": format,
                "dpi": dpi,
                "size_bytes": image_path.stat().st_size,
            }
            
            # Calculate aspect ratio
            if height > 0:
                info["aspect_ratio"] = width / height
            
            return info
    except Exception as e:
        return {"error": str(e)}


def analyze_tile_connectivity(results: List[dict], collection_id: str) -> Dict[str, Any]:
    """Analyze if tiles connect to each other spatially."""
    print(f"\n{'='*80}")
    print(f"ANALYZING TILE CONNECTIVITY")
    print(f"{'='*80}")
    
    connectivity = {
        "tiles_analyzed": 0,
        "gaps_found": [],
        "overlaps_found": [],
        "issues": [],
    }
    
    if _is_strip_collection(collection_id):
        print("Collection uses full-strip previews; tile connectivity checks skipped")
        connectivity["skipped"] = True
        return connectivity

    if len(results) < 2:
        print("Need at least 2 tiles for connectivity analysis")
        return connectivity
    
    # Extract bounding boxes
    tiles_with_bounds = []
    for item in results:
        geom = item.get("geometry")
        if not geom:
            continue
        bounds = bounds_from_geometry(geom)
        if not bounds:
            continue
        
        minx, miny, maxx, maxy = bounds
        tiles_with_bounds.append({
            "id": item.get("id"),
            "collection": item.get("collection"),
            "group": _capture_group_key(item),
            "bounds": bounds,
            "minx": minx,
            "miny": miny,
            "maxx": maxx,
            "maxy": maxy,
            "width": maxx - minx,
            "height": maxy - miny,
        })
    
    connectivity["tiles_analyzed"] = len(tiles_with_bounds)
    print(f"\nAnalyzing {len(tiles_with_bounds)} tiles with geometry")
    
    # Check for gaps between tiles
    for i, tile1 in enumerate(tiles_with_bounds):
        for j, tile2 in enumerate(tiles_with_bounds[i+1:], start=i+1):
            # Check if tiles are adjacent (should touch)
            # Horizontal adjacency
            if abs(tile1["maxx"] - tile2["minx"]) < 0.0001 or abs(tile2["maxx"] - tile1["minx"]) < 0.0001:
                # Check if they overlap in Y
                y_overlap = min(tile1["maxy"], tile2["maxy"]) - max(tile1["miny"], tile2["miny"])
                if y_overlap > 0:
                    # They should be touching horizontally
                    continue
            
            # Vertical adjacency
            if abs(tile1["maxy"] - tile2["miny"]) < 0.0001 or abs(tile2["maxy"] - tile1["miny"]) < 0.0001:
                # Check if they overlap in X
                x_overlap = min(tile1["maxx"], tile2["maxx"]) - max(tile1["minx"], tile2["minx"])
                if x_overlap > 0:
                    # They should be touching vertically
                    continue
            
            # Check for overlap
            x_overlap = min(tile1["maxx"], tile2["maxx"]) - max(tile1["minx"], tile2["minx"])
            y_overlap = min(tile1["maxy"], tile2["maxy"]) - max(tile1["miny"], tile2["miny"])
            
            if x_overlap > 0.0001 and y_overlap > 0.0001:
                overlap = {
                    "tile1": tile1["id"],
                    "tile2": tile2["id"],
                    "overlap_x": x_overlap,
                    "overlap_y": y_overlap,
                }
                connectivity["overlaps_found"].append(overlap)
            
            # Check for gaps (tiles that are close but not touching)
            x_gap = max(tile1["minx"], tile2["minx"]) - min(tile1["maxx"], tile2["maxx"])
            y_gap = max(tile1["miny"], tile2["miny"]) - min(tile1["maxy"], tile2["maxy"])
            
            if 0 < x_gap < tile1["width"] * 0.2 and y_overlap > 0:
                gap = {
                    "tile1": tile1["id"],
                    "tile2": tile2["id"],
                    "gap_type": "horizontal",
                    "gap_size": x_gap,
                }
                connectivity["gaps_found"].append(gap)
            elif 0 < y_gap < tile1["height"] * 0.2 and x_overlap > 0:
                gap = {
                    "tile1": tile1["id"],
                    "tile2": tile2["id"],
                    "gap_type": "vertical",
                    "gap_size": y_gap,
                }
                connectivity["gaps_found"].append(gap)
    
    if connectivity["gaps_found"]:
        issue = f"Found {len(connectivity['gaps_found'])} gaps between tiles"
        print(f"\n⚠️  {issue}:")
        connectivity["issues"].append(issue)
        for gap in connectivity["gaps_found"][:10]:
            print(f"  Gap between {gap['tile1'][:20]} and {gap['tile2'][:20]}")
            print(f"    Type: {gap['gap_type']}, Size: {gap['gap_size']:.6f} degrees")
    else:
        print(f"\n✓ No significant gaps found between tiles")
    
    if connectivity["overlaps_found"]:
        print(f"\n  Found {len(connectivity['overlaps_found'])} overlaps between tiles:")
        for overlap in connectivity["overlaps_found"][:5]:
            print(f"  Overlap: {overlap['tile1'][:20]} & {overlap['tile2'][:20]}")
            print(f"    X: {overlap['overlap_x']:.6f}°, Y: {overlap['overlap_y']:.6f}°")
    
    # Analyze tile size consistency
    widths = [t["width"] for t in tiles_with_bounds]
    heights = [t["height"] for t in tiles_with_bounds]
    
    print(f"\nTile size consistency:")
    print(f"  Width range: {min(widths):.6f} - {max(widths):.6f} degrees")
    print(f"  Height range: {min(heights):.6f} - {max(heights):.6f} degrees")
    
    connectivity["size_consistency"] = {
        "width_min": min(widths),
        "width_max": max(widths),
        "height_min": min(heights),
        "height_max": max(heights),
    }
    
    by_group: dict[str, list[dict[str, Any]]] = {}
    for tile in tiles_with_bounds:
        by_group.setdefault(tile.get("group") or "unknown", []).append(tile)

    width_issue = False
    height_issue = False
    for group_tiles in by_group.values():
        g_widths = [t["width"] for t in group_tiles]
        g_heights = [t["height"] for t in group_tiles]
        if g_widths and max(g_widths) - min(g_widths) > 0.0001:
            width_issue = True
        if g_heights and max(g_heights) - min(g_heights) > 0.0001:
            height_issue = True

    if width_issue:
        issue = "Tile widths are inconsistent within capture groups"
        print(f"  ⚠️  WARNING: {issue}")
        connectivity["issues"].append(issue)
    if height_issue:
        issue = "Tile heights are inconsistent within capture groups"
        print(f"  ⚠️  WARNING: {issue}")
        connectivity["issues"].append(issue)
    
    return connectivity


def download_and_analyze(
    client: SatellogicClient,
    results: List[dict],
    output_dir: Path,
    contract_id: str = None,
    collection_id: str | None = None,
) -> Dict[str, Any]:
    """Download images and analyze their properties."""
    print(f"\n{'='*80}")
    print(f"DOWNLOADING AND ANALYZING IMAGES")
    print(f"{'='*80}")
    
    image_analysis = {
        "downloaded": 0,
        "failed": 0,
        "by_collection": {},
        "issues": [],
    }
    
    if not results:
        print("No results to download")
        return image_analysis
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Limit downloads to avoid taking too long
    max_downloads = 10
    to_download = results[:max_downloads]
    
    print(f"\nDownloading up to {max_downloads} images...")
    
    downloaded_images = []
    
    for i, item in enumerate(to_download, 1):
        item_id = item.get("id", f"unknown_{i}")
        collection = item.get("collection", "unknown")
        assets = item.get("assets", {})
        
        # Try to get preview or thumbnail
        preview_url = assets.get("preview", {}).get("href") if isinstance(assets.get("preview"), dict) else assets.get("preview")
        if not preview_url and "preview" in assets:
            preview_url = assets["preview"]
        
        thumb_url = assets.get("thumbnail", {}).get("href") if isinstance(assets.get("thumbnail"), dict) else assets.get("thumbnail")
        if not thumb_url and "thumbnail" in assets:
            thumb_url = assets["thumbnail"]
        
        url = preview_url or thumb_url
        
        if not url:
            print(f"  [{i}/{len(to_download)}] {item_id[:30]}: No preview/thumbnail URL")
            image_analysis["failed"] += 1
            continue
        
        # Sanitize filename
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in item_id[:50])
        output_path = output_dir / f"{safe_id}_col_{collection}.jpg"
        
        print(f"  [{i}/{len(to_download)}] Downloading {item_id[:30]}...")
        if download_image(url, client, output_path, contract_id):
            props = analyze_image_properties(output_path)
            downloaded_images.append({
                "id": item_id,
                "collection": collection,
                "path": output_path,
                "props": props,
                "source_item": item,
            })
            image_analysis["downloaded"] += 1
            print(f"    ✓ Saved to {output_path.name}")
            if "width" in props:
                print(f"    Size: {props['width']}x{props['height']}, {props.get('format', 'unknown')}, {props['size_bytes']} bytes")
        else:
            image_analysis["failed"] += 1
    
    # Analyze downloaded images
    if downloaded_images:
        print(f"\n{'='*80}")
        print(f"IMAGE ANALYSIS SUMMARY")
        print(f"{'='*80}")
        
        # Group by collection
        by_collection = defaultdict(list)
        for img in downloaded_images:
            by_collection[img["collection"]].append(img)
        
        print(f"\nImages grouped by collection:")
        for collection, images in sorted(by_collection.items()):
            print(f"\n  Collection: {collection} ({len(images)} images)")
            
            widths = [img["props"].get("width") for img in images if "width" in img["props"]]
            heights = [img["props"].get("height") for img in images if "height" in img["props"]]
            
            coll_info = {
                "count": len(images),
                "dimensions": {},
            }
            
            if widths and heights:
                print(f"    Width range: {min(widths)} - {max(widths)} pixels")
                print(f"    Height range: {min(heights)} - {max(heights)} pixels")
                
                coll_info["dimensions"] = {
                    "width_min": min(widths),
                    "width_max": max(widths),
                    "height_min": min(heights),
                    "height_max": max(heights),
                }
                
                if not _is_strip_collection(collection_id) and len(set(widths)) > 1:
                    issue = f"Image widths vary within collection {collection}: {min(widths)} - {max(widths)}"
                    print(f"    ⚠️  WARNING: {issue}")
                    image_analysis["issues"].append(issue)
                if not _is_strip_collection(collection_id) and len(set(heights)) > 1:
                    issue = f"Image heights vary within collection {collection}: {min(heights)} - {max(heights)}"
                    print(f"    ⚠️  WARNING: {issue}")
                    image_analysis["issues"].append(issue)
            
            image_analysis["by_collection"][collection] = coll_info
    
    return image_analysis


def load_test_case(test_file: Path) -> Dict[str, Any]:
    """Load a test case from a JSON file."""
    with open(test_file, 'r') as f:
        test_case = json.load(f)
    
    # Validate required fields
    required = ["name", "collection_id", "center_lat", "center_lon"]
    for field in required:
        if field not in test_case:
            raise ValueError(f"Test case missing required field: {field}")
    
    # Set defaults
    test_case.setdefault("aoi_size_km", 20)
    test_case.setdefault("contract_id", None)
    
    return test_case


def run_test_case(test_case: Dict[str, Any], client: SatellogicClient, output_base: Path) -> Dict[str, Any]:
    """Run a single test case and return results."""
    print(f"\n{'#'*80}")
    print(f"# TEST CASE: {test_case['name']}")
    print(f"{'#'*80}")
    
    # Create AOI
    geometry = create_test_aoi(
        test_case["center_lat"],
        test_case["center_lon"],
        test_case["aoi_size_km"]
    )
    
    print(f"Location: {test_case['center_lat']}, {test_case['center_lon']}")
    print(f"AOI size: {test_case['aoi_size_km']}km x {test_case['aoi_size_km']}km")
    
    # Perform search
    results = perform_search(
        client,
        geometry,
        test_case["collection_id"],
        test_case.get("contract_id")
    )
    
    if not results:
        return {
            "test_case": test_case["name"],
            "success": False,
            "error": "No results found",
        }
    
    # Analyze results
    search_analysis = analyze_search_results(results, test_case["collection_id"])
    connectivity_analysis = analyze_tile_connectivity(results, test_case["collection_id"])
    
    # Create output directory for this test case
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in test_case["name"])
    test_output_dir = output_base / safe_name
    
    if test_case.get("skip_downloads"):
        image_analysis = {
            "downloaded": 0,
            "failed": 0,
            "by_collection": {},
            "issues": [],
            "skipped": True,
        }
    else:
        image_analysis = download_and_analyze(
            client,
            results,
            test_output_dir,
            test_case.get("contract_id"),
            test_case.get("collection_id"),
        )

    edge_debug = None
    if test_case.get("edge_debug") and str(test_case.get("collection_id") or "").strip().lower() == "l1d-sr":
        edge_debug = _edge_tile_debug(
            client,
            results,
            test_case.get("contract_id"),
            int(test_case.get("edge_zoom") or 16),
            bool(test_case.get("edge_multi")),
            bool(test_case.get("edge_variants")),
            int(test_case.get("edge_tiles") or 4),
        )
    
    # Combine all analyses
    all_issues = (
        search_analysis.get("issues", []) +
        connectivity_analysis.get("issues", []) +
        image_analysis.get("issues", [])
    )
    
    result = {
        "test_case": test_case["name"],
        "success": True,
        "collection_id": test_case["collection_id"],
        "total_items": search_analysis["total_items"],
        "collection_mixing": search_analysis.get("collection_mixing", False),
        "collections": search_analysis["collections"],
        "connectivity": connectivity_analysis,
        "images": image_analysis,
        "issues": all_issues,
        "edge_debug": edge_debug,
        "output_dir": str(test_output_dir),
    }
    
    return result


def main():
    parser = argparse.ArgumentParser(description="WMS/Tile Search Diagnostic Tool")
    parser.add_argument(
        "test_cases_dir",
        type=str,
        nargs="?",
        default="test_cases",
        help="Directory containing test case JSON files (default: test_cases)"
    )
    parser.add_argument(
        "--test",
        type=str,
        help="Run only a specific test case file (e.g., test_quickview_thumb.json)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="test_results",
        help="Output directory for downloaded images and results (default: test_results)"
    )
    parser.add_argument(
        "--edge-debug",
        action="store_true",
        help="Probe bottom/right edge tiles for L1D SR capture groups"
    )
    parser.add_argument(
        "--edge-zoom",
        type=int,
        default=16,
        help="Zoom level to probe for edge tiles (default: 16)"
    )
    parser.add_argument(
        "--skip-downloads",
        action="store_true",
        help="Skip preview/thumbnail downloads"
    )
    parser.add_argument(
        "--edge-multi",
        action="store_true",
        help="Include multi-source edge tile checks (slower)"
    )
    parser.add_argument(
        "--edge-variants",
        action="store_true",
        help="Test alternate tile parameters on one edge tile"
    )
    parser.add_argument(
        "--edge-tiles",
        type=int,
        default=4,
        help="Number of quadrant tiles to probe (default: 4)"
    )
    
    args = parser.parse_args()
    
    print("="*80)
    print("WMS/TILE SEARCH DIAGNOSTIC TOOL")
    print("="*80)
    print()
    
    # Get base directories
    script_dir = Path(__file__).parent
    test_cases_dir = script_dir / args.test_cases_dir
    output_base = script_dir / args.output
    
    # Check if test cases directory exists
    if not test_cases_dir.exists():
        print(f"ERROR: Test cases directory not found: {test_cases_dir}")
        print(f"\nCreating directory and sample test case...")
        test_cases_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a sample test case
        sample_test = {
            "name": "QuickView Visual Thumb - Vietnam Coast",
            "collection_id": "quickview-visual-thumb",
            "center_lat": 16.46092468,
            "center_lon": 111.56210960,
            "aoi_size_km": 20,
            "contract_id": None
        }
        sample_file = test_cases_dir / "test_quickview_thumb.json"
        with open(sample_file, 'w') as f:
            json.dump(sample_test, f, indent=2)
        print(f"Created sample test case: {sample_file}")
        print(f"\nPlease add more test cases to {test_cases_dir} and run again.")
        return
    
    # Load test cases
    if args.test:
        test_files = [test_cases_dir / args.test]
    else:
        test_files = sorted(test_cases_dir.glob("*.json"))
    
    if not test_files:
        print(f"ERROR: No test case files found in {test_cases_dir}")
        return
    
    print(f"Found {len(test_files)} test case(s):")
    for tf in test_files:
        print(f"  - {tf.name}")
    print()
    
    # Initialize client
    print(f"Initializing Satellogic client...")
    print(f"Auth mode: {settings.satellogic_auth_mode}")
    print(f"API URL: {settings.satellogic_api_base_url}")
    print(f"STAC URL: {settings.satellogic_stac_url}")
    print(f"Token URL: {settings.satellogic_token_url}")
    
    # Check credentials
    if settings.satellogic_auth_mode == "bearer":
        has_token = bool(settings.satellogic_bearer_token)
        print(f"Bearer token present: {has_token}")
        if has_token:
            print(f"Bearer token length: {len(settings.satellogic_bearer_token)}")
    elif settings.satellogic_auth_mode == "key_secret":
        has_key = bool(settings.satellogic_key_id)
        has_secret = bool(settings.satellogic_key_secret)
        print(f"Key ID present: {has_key}")
        print(f"Key secret present: {has_secret}")
        if has_key:
            print(f"Key ID: {settings.satellogic_key_id[:10]}...")
    elif settings.satellogic_auth_mode == "oauth_client_credentials":
        has_key = bool(settings.satellogic_key_id)
        has_secret = bool(settings.satellogic_key_secret)
        print(f"Client ID present: {has_key}")
        print(f"Client secret present: {has_secret}")
        if has_key:
            print(f"Client ID: {settings.satellogic_key_id[:10]}...")
    
    client = SatellogicClient()
    
    # Test OAuth token acquisition
    print(f"\nTesting OAuth token acquisition...")
    try:
        token = client._get_access_token()
        if token:
            print(f"✓ OAuth token acquired successfully (length: {len(token)})")
        else:
            print(f"⚠️  OAuth token is None (missing credentials)")
    except Exception as e:
        print(f"❌ OAuth token acquisition failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Test auth headers
    print(f"\nGenerating auth headers...")
    try:
        headers = client.auth_headers()
        if "authorizationToken" in headers:
            auth_token = headers["authorizationToken"]
            auth_type = auth_token.split()[0] if " " in auth_token else "unknown"
            print(f"✓ Auth header present (type: {auth_type})")
        else:
            print(f"❌ No authorizationToken in headers!")
    except Exception as e:
        print(f"❌ Failed to generate auth headers: {e}")
    
    contract_id = settings.satellogic_contract_id
    if not contract_id:
        try:
            contracts = client.list_contracts()
            if contracts:
                contract_id = contracts[0].get("contract_id")
        except Exception as e:
            print(f"WARNING: Failed to list contracts: {e}")

    if contract_id:
        print(f"\nUsing contract ID: {contract_id}")
    else:
        print("\nWARNING: No contract ID available; STAC requests may be unauthorized")
    print()
    
    # Run test cases
    results = []
    for test_file in test_files:
        try:
            test_case = load_test_case(test_file)
            if not test_case.get("contract_id") and contract_id:
                test_case["contract_id"] = contract_id
            if args.edge_debug:
                test_case["edge_debug"] = True
                test_case["edge_zoom"] = args.edge_zoom
                test_case["edge_multi"] = args.edge_multi
                test_case["edge_variants"] = args.edge_variants
                test_case["edge_tiles"] = args.edge_tiles
            if args.skip_downloads:
                test_case["skip_downloads"] = True
            result = run_test_case(test_case, client, output_base)
            results.append(result)
        except Exception as e:
            print(f"\n❌ ERROR running test case {test_file.name}: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "test_case": test_file.name,
                "success": False,
                "error": str(e),
            })
    
    # Print summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    
    for result in results:
        print(f"\nTest: {result['test_case']}")
        if not result.get("success"):
            print(f"  ❌ FAILED: {result.get('error', 'Unknown error')}")
            continue
        
        print(f"  Collection: {result['collection_id']}")
        print(f"  Total items: {result['total_items']}")
        print(f"  Collection mixing: {'YES ⚠️' if result['collection_mixing'] else 'No ✓'}")
        print(f"  Issues found: {len(result['issues'])}")
        
        if result['issues']:
            for issue in result['issues'][:5]:
                print(f"    - {issue}")
            if len(result['issues']) > 5:
                print(f"    ... and {len(result['issues']) - 5} more")
        else:
            print(f"    ✓ No issues detected")
        
        print(f"  Output: {result['output_dir']}")
    
    # Save results to JSON
    results_file = output_base / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed results saved to: {results_file}")
    
    print(f"\n{'='*80}")
    print("DIAGNOSTIC COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
