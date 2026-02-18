#!/usr/bin/env python3
"""
WMS/Tile Search Diagnostic Tool
Performs actual searches and downloads to diagnose collection mixing, GSD inconsistencies, and tile connectivity issues.
"""

import sys
import math
import json
import os
from pathlib import Path
from typing import Any, List, Dict, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import argparse

# Add backend to path
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

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


def analyze_search_results(results: List[dict]) -> Dict[str, Any]:
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
            
            if max_gsd - min_gsd > 0.001:
                issue = f"GSD varies within collection {collection}: {min_gsd:.6f} - {max_gsd:.6f}"
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
        
        if max(all_gsds) - min(all_gsds) > 0.01:
            issue = f"Significant GSD variation detected: {max(all_gsds) - min(all_gsds):.6f}"
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


def analyze_tile_connectivity(results: List[dict]) -> Dict[str, Any]:
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
    
    if max(widths) - min(widths) > 0.0001:
        issue = "Tile widths are inconsistent"
        print(f"  ⚠️  WARNING: {issue}")
        connectivity["issues"].append(issue)
    if max(heights) - min(heights) > 0.0001:
        issue = "Tile heights are inconsistent"
        print(f"  ⚠️  WARNING: {issue}")
        connectivity["issues"].append(issue)
    
    return connectivity


def download_and_analyze(client: SatellogicClient, results: List[dict], output_dir: Path, contract_id: str = None) -> Dict[str, Any]:
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
                
                if len(set(widths)) > 1:
                    issue = f"Image widths vary within collection {collection}: {min(widths)} - {max(widths)}"
                    print(f"    ⚠️  WARNING: {issue}")
                    image_analysis["issues"].append(issue)
                if len(set(heights)) > 1:
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
    search_analysis = analyze_search_results(results)
    connectivity_analysis = analyze_tile_connectivity(results)
    
    # Create output directory for this test case
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in test_case["name"])
    test_output_dir = output_base / safe_name
    
    # Download and analyze images
    image_analysis = download_and_analyze(
        client,
        results,
        test_output_dir,
        test_case.get("contract_id")
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
    client = SatellogicClient()
    
    contract_id = settings.satellogic_contract_id
    if contract_id:
        print(f"Using contract ID: {contract_id}")
    print()
    
    # Run test cases
    results = []
    for test_file in test_files:
        try:
            test_case = load_test_case(test_file)
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
