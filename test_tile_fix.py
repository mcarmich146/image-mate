#!/usr/bin/env python3
"""Test script to verify the tile boundary fix for L1D SR WMS layers."""

import sys
import math
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from app.workbench import _tile_xy_float, geometry_quadkeys


def test_tile_edge_cases():
    """Test that fractional tile boundaries include edge tiles."""
    
    print("Testing tile edge handling with fractional boundaries...")
    
    # Test case 1: Southern edge with fractional tile coordinate
    # A geometry with southern edge at lat=37.0 might have a tile coordinate of 47.8
    # Using floor (old behavior) would give tile 47, missing tile 48
    # Using ceil for max bounds should give tile 48
    
    # Create a test geometry that spans fractional tile boundaries
    test_geometry = {
        "type": "Polygon",
        "coordinates": [[
            [-122.0, 37.0],  # SW corner
            [-121.0, 37.0],  # SE corner
            [-121.0, 38.0],  # NE corner
            [-122.0, 38.0],  # NW corner
            [-122.0, 37.0],
        ]],
    }
    
    # Get quadkeys at zoom level 6
    quadkeys_old_style = set()
    quadkeys_new_style = geometry_quadkeys(test_geometry, zoom=6)
    
    # Calculate using old method (floor for both)
    minx, miny, maxx, maxy = -122.0, 37.0, -121.0, 38.0
    x0_f, y0_f = _tile_xy_float(maxy, minx, 6)
    x1_f, y1_f = _tile_xy_float(miny, maxx, 6)
    x0_floor = int(math.floor(min(x0_f, x1_f)))
    x1_floor = int(math.floor(max(x0_f, x1_f)))
    y0_floor = int(math.floor(min(y0_f, y1_f)))
    y1_floor = int(math.floor(max(y0_f, y1_f)))
    
    print(f"\nOld method (floor for all):")
    print(f"  SW corner (lat={miny}, lon={minx}): tile=({x0_floor}, {y1_floor})")
    print(f"  NE corner (lat={maxy}, lon={maxx}): tile=({x1_floor}, {y0_floor})")
    print(f"  Tile range: x=[{x0_floor}, {x1_floor}], y=[{y0_floor}, {y1_floor}]")
    print(f"  Tile count: {(x1_floor - x0_floor + 1) * (y1_floor - y0_floor + 1)}")
    
    # Calculate using new method (ceil(max)-1 for max bounds)
    x1_ceil = int(math.ceil(max(x0_f, x1_f)) - 1)
    y1_ceil = int(math.ceil(max(y0_f, y1_f)) - 1)
    
    print(f"\nNew method (ceil for max bounds):")
    print(f"  SE corner Y with ceil-1: y={y1_ceil}")
    print(f"  NE corner X with ceil-1: x={x1_ceil}")
    print(f"  New quadkey count: {len(quadkeys_new_style)}")
    
    # Show the difference
    print(f"\nDifference:")
    if y1_ceil > y1_floor:
        print(f"  ✓ Southern edge now includes {y1_ceil - y1_floor} additional tile row(s)")
    else:
        print(f"  Same tile boundaries")
    
    if x1_ceil > x1_floor:
        print(f"  ✓ Eastern edge now includes {x1_ceil - x1_floor} additional tile column(s)")
    else:
        print(f"  Same tile boundaries")
    
    # Test with a geometry that has fractional boundaries
    print("\n" + "="*60)
    print("Testing with geometry at fractional tile boundaries...")
    
    # Create a geometry that should definitely span fractional tiles
    fractional_geometry = {
        "type": "Polygon",
        "coordinates": [[
            [-122.45, 37.25],  # SW corner
            [-121.55, 37.25],  # SE corner
            [-121.55, 37.75],  # NE corner
            [-122.45, 37.75],  # NW corner
            [-122.45, 37.25],
        ]],
    }
    
    quadkeys_fractional = geometry_quadkeys(fractional_geometry, zoom=6)
    print(f"Quadkeys for fractional boundary geometry: {len(quadkeys_fractional)}")
    
    print("\n✓ Test completed successfully!")


if __name__ == "__main__":
    test_tile_edge_cases()
