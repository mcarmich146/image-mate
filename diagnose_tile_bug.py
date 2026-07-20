#!/usr/bin/env python3
"""
Diagnostic script to download and analyze tiles from a search query.
This will help identify collection mixing issues, GSD inconsistencies, and tile connectivity.

PERFORMS ACTUAL DOWNLOADS AND ANALYSIS.
"""

import sys
import math
import json
import os
from pathlib import Path
from typing import Any, List, Dict, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import requests

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.workbench import _tile_xy, geometry_quadkeys, bounds_from_geometry
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
        return []


def analyze_search_results(results: List[dict]) -> None:
    """Analyze search results for collection consistency and GSD."""
    print(f"\n{'='*80}")
    print(f"ANALYZING SEARCH RESULTS")
    print(f"{'='*80}")
    
    if not results:
        print("No results to analyze")
        return
    
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
        
        if gsds:
            min_gsd = min(gsds)
            max_gsd = max(gsds)
            avg_gsd = sum(gsds) / len(gsds)
            print(f"    GSD range: {min_gsd:.4f} - {max_gsd:.4f} (avg: {avg_gsd:.4f})")
            if max_gsd - min_gsd > 0.001:
                print(f"    ⚠️  WARNING: GSD varies within collection!")
        else:
            print(f"    No GSD data available")
    
    # Check for collection mixing issue
    if len(by_collection) > 1:
        print(f"\n⚠️  WARNING: Search returned items from {len(by_collection)} different collections!")
        print(f"   This indicates a collection filtering bug!")
    
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
        
        if max(all_gsds) - min(all_gsds) > 0.01:
            print(f"  ⚠️  WARNING: Significant GSD variation detected!")


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


def analyze_tile_connectivity(results: List[dict]) -> None:
    """Analyze if tiles connect to each other spatially."""
    print(f"\n{'='*80}")
    print(f"ANALYZING TILE CONNECTIVITY")
    print(f"{'='*80}")
    
    if len(results) < 2:
        print("Need at least 2 tiles for connectivity analysis")
        return
    
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
            "bounds": bounds,
            "minx": minx,
            "miny": miny,
            "maxx": maxx,
            "maxy": maxy,
            "width": maxx - minx,
            "height": maxy - miny,
        })
    
    print(f"\nAnalyzing {len(tiles_with_bounds)} tiles with geometry")
    
    # Check for gaps between tiles
    gaps_found = []
    overlaps_found = []
    
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
                overlaps_found.append({
                    "tile1": tile1["id"],
                    "tile2": tile2["id"],
                    "overlap_x": x_overlap,
                    "overlap_y": y_overlap,
                })
            
            # Check for gaps (tiles that are close but not touching)
            x_gap = max(tile1["minx"], tile2["minx"]) - min(tile1["maxx"], tile2["maxx"])
            y_gap = max(tile1["miny"], tile2["miny"]) - min(tile1["maxy"], tile2["maxy"])
            
            if 0 < x_gap < tile1["width"] * 0.2 and y_overlap > 0:
                gaps_found.append({
                    "tile1": tile1["id"],
                    "tile2": tile2["id"],
                    "gap_type": "horizontal",
                    "gap_size": x_gap,
                })
            elif 0 < y_gap < tile1["height"] * 0.2 and x_overlap > 0:
                gaps_found.append({
                    "tile1": tile1["id"],
                    "tile2": tile2["id"],
                    "gap_type": "vertical",
                    "gap_size": y_gap,
                })
    
    if gaps_found:
        print(f"\n⚠️  Found {len(gaps_found)} gaps between tiles:")
        for gap in gaps_found[:10]:
            print(f"  Gap between {gap['tile1'][:20]} and {gap['tile2'][:20]}")
            print(f"    Type: {gap['gap_type']}, Size: {gap['gap_size']:.6f} degrees")
    else:
        print(f"\n✓ No significant gaps found between tiles")
    
    if overlaps_found:
        print(f"\n  Found {len(overlaps_found)} overlaps between tiles:")
        for overlap in overlaps_found[:5]:
            print(f"  Overlap: {overlap['tile1'][:20]} & {overlap['tile2'][:20]}")
            print(f"    X: {overlap['overlap_x']:.6f}°, Y: {overlap['overlap_y']:.6f}°")
    
    # Analyze tile size consistency
    widths = [t["width"] for t in tiles_with_bounds]
    heights = [t["height"] for t in tiles_with_bounds]
    
    print(f"\nTile size consistency:")
    print(f"  Width range: {min(widths):.6f} - {max(widths):.6f} degrees")
    print(f"  Height range: {min(heights):.6f} - {max(heights):.6f} degrees")
    
    if max(widths) - min(widths) > 0.0001:
        print(f"  ⚠️  WARNING: Tile widths are inconsistent!")
    if max(heights) - min(heights) > 0.0001:
        print(f"  ⚠️  WARNING: Tile heights are inconsistent!")


def download_and_analyze(client: SatellogicClient, results: List[dict], output_dir: Path, contract_id: str = None) -> None:
    """Download images and analyze their properties."""
    print(f"\n{'='*80}")
    print(f"DOWNLOADING AND ANALYZING IMAGES")
    print(f"{'='*80}")
    
    if not results:
        print("No results to download")
        return
    
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
            print(f"    ✓ Saved to {output_path.name}")
            if "width" in props:
                print(f"    Size: {props['width']}x{props['height']}, {props.get('format', 'unknown')}, {props['size_bytes']} bytes")
    
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
            
            if widths and heights:
                print(f"    Width range: {min(widths)} - {max(widths)} pixels")
                print(f"    Height range: {min(heights)} - {max(heights)} pixels")
                
                if len(set(widths)) > 1:
                    print(f"    ⚠️  WARNING: Image widths vary within collection!")
                if len(set(heights)) > 1:
                    print(f"    ⚠️  WARNING: Image heights vary within collection!")


def main():
    print("="*80)
    print("TILE SEARCH AND ANALYSIS DIAGNOSTIC SCRIPT")
    print("="*80)
    print("\nThis script will:")
    print("  1. Perform a search for a specific collection")
    print("  2. Analyze search results for collection consistency")
    print("  3. Check GSD consistency across tiles")
    print("  4. Download sample images and analyze their properties")
    print("  5. Check tile connectivity (gaps/overlaps)")
    print()
    
    # Configuration
    collection_id = input("Enter collection ID (default: quickview-visual-thumb): ").strip() or "quickview-visual-thumb"
    
    # Test location - you can modify this
    center_lat = 16.46092468
    center_lon = 111.56210960
    aoi_size_km = 20
    
    print(f"\nUsing test location: {center_lat}, {center_lon}")
    print(f"AOI size: {aoi_size_km}km x {aoi_size_km}km")
    
    # Create AOI
    geometry = create_test_aoi(center_lat, center_lon, aoi_size_km)
    
    # Initialize client
    print(f"\nInitializing Satellogic client...")
    client = SatellogicClient()
    
    contract_id = settings.satellogic_contract_id
    if contract_id:
        print(f"Using contract ID: {contract_id}")
    
    # Perform search
    results = perform_search(client, geometry, collection_id, contract_id)
    
    if not results:
        print("\nNo results found. Exiting.")
        return
    
    # Analyze results
    analyze_search_results(results)
    
    # Analyze tile connectivity
    analyze_tile_connectivity(results)
    
    # Download and analyze images
    output_dir = Path(__file__).parent / "tile_diagnostic_downloads"
    download_and_analyze(client, results, output_dir, contract_id)
    
    print(f"\n{'='*80}")
    print("DIAGNOSTIC COMPLETE")
    print(f"{'='*80}")
    print(f"\nDownloaded images saved to: {output_dir}")
    print("\nKey findings:")
    print("  - Check if multiple collections appear in search results (collection filtering bug)")
    print("  - Check if GSD varies significantly (indicates mixed collections)")
    print("  - Check if image dimensions vary (indicates mixed collections)")
    print("  - Check for gaps between tiles (indicates connectivity issues)")


if __name__ == "__main__":
    main()

