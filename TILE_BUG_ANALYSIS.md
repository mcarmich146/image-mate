# Tile Calculation Bug Analysis

## Current Implementation Review

### Location
`backend/app/workbench.py` - functions `_tile_xy()` and `geometry_quadkeys()`

### The Problem
The current code is attempting to include edge tiles by using ceiling for maximum bounds, but there's a **fundamental flaw in the approach**.

## Root Cause Analysis

### Understanding Web Mercator Tile Coordinates

In Web Mercator (used by WMS/WMTS):
- **X axis**: Increases EASTWARD (left to right)
  - minx = western edge → should give x_min (use floor)
  - maxx = eastern edge → should give x_max (use ceiling)

- **Y axis**: Increases SOUTHWARD (top to bottom) 
  - maxy = northern edge → should give y_min (use floor)
  - miny = southern edge → should give y_max (use ceiling)

### Current Implementation (geometry_quadkeys)

```python
x0, y1 = _tile_xy(miny, minx, zoom, use_ceil=False)  # SW corner (floor both)
x1_tmp, y0 = _tile_xy(maxy, maxx, zoom, use_ceil=False)  # NE corner (floor both)
_, y1_max = _tile_xy(miny, maxx, zoom, use_ceil=True)  # SE corner (ceiling both)
x1, _ = _tile_xy(maxy, maxx, zoom, use_ceil=True)  # NE corner (ceiling both)
y1 = max(y1, y1_max)
```

### The Fundamental Flaw

The `use_ceil` parameter in `_tile_xy()` applies to **BOTH** x and y coordinates:

```python
if use_ceil:
    x = math.ceil(x_float)
    y = math.ceil(y_float)  # <-- Both axes use the same mode!
else:
    x = int(x_float)
    y = int(y_float)
```

This means we **cannot** get the correct behavior for all edges:

| Edge | Needs | Current Call | X Correct? | Y Correct? |
|------|-------|--------------|------------|------------|
| Western (x_min) | floor x | `_tile_xy(miny, minx, False)` | ✓ Yes | ✗ No (should ceil y) |
| Eastern (x_max) | ceiling x | `_tile_xy(maxy, maxx, True)` | ✓ Yes | ✗ No (should floor y) |
| Northern (y_min) | floor y | `_tile_xy(maxy, maxx, False)` | N/A | ✓ Yes |
| Southern (y_max) | ceiling y | `_tile_xy(miny, maxx, True)` | N/A | ✓ Yes |

### The Workaround Attempt

The code tries to work around this by:
1. Calling `_tile_xy()` multiple times with different corner combinations
2. Picking the x or y value we want from each call
3. Using `max(y1, y1_max)` to get the southern-most tile

**This is fragile and error-prone** because:
- It's making 4 calls instead of calculating correctly once
- The logic is hard to verify and maintain
- It's still getting some values wrong

### Specific Bug Pattern

When a geometry's southern edge (miny) falls at a fractional tile coordinate:

**Example**: Geometry with southern edge at latitude 16.45°
- Maps to tile Y = 47.82 at zoom 6
- floor(47.82) = 47
- ceiling(47.82) = 48

**Current behavior**:
1. `_tile_xy(miny, minx, False)` → gives y1 = 47 (floor)
2. `_tile_xy(miny, maxx, True)` → gives y1_max = 48 (ceiling)
3. `y1 = max(47, 48)` = 48 ✓ Correct!

**BUT** this only works if we're using the SE corner calculation. If the geometry is small or the coordinates align differently, we might miss this.

### Additional Issue: Clamping

After calculating tile coordinates, they're clamped:
```python
return max(0, min(n - 1, x)), max(0, min(n - 1, y))
```

If `ceil(x_float)` or `ceil(y_float)` exceeds `n-1`, it gets clamped back, potentially losing edge tiles at the world boundaries.

## Why It's Still Missing Tiles

The current "fix" is incomplete because:

1. **Relies on workaround logic** that may not catch all edge cases
2. **The southern-most row of search tiles works** because their individual geometries get the ceiling treatment correctly
3. **Inner tiles fail** because when their northern edge (maxy) calculation uses ceiling instead of floor, we miss tiles

The pattern you're seeing ("missing tiles except for southern-most row") matches this exactly:
- Southern-most search tiles: Their southern edges get ceiling Y correctly → works
- All other search tiles: Their southern edges might be getting floor from the y0 calculation that's using the wrong corner

## Summary

The fix I implemented is **architecturally flawed**. Instead of having separate control over X and Y rounding modes, I tried to work around it by calling the function multiple times. This creates:

1. Performance overhead (4 calls instead of 1)
2. Complex, hard-to-verify logic
3. Still missing edge cases
4. Maintenance nightmare

## Recommended Fix (Not Implemented Yet)

The `_tile_xy()` function should accept separate rounding modes for x and y:

```python
def _tile_xy(lat, lon, zoom, x_mode='floor', y_mode='floor'):
    # Calculate float values
    # Apply x_mode to x, y_mode to y separately
    # Return results
```

Or even simpler, just return the float values and let the caller decide how to round them.

But first, let's run the diagnostic to confirm this analysis.
