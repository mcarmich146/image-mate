from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import polygonize, unary_union


@dataclass
class NormalizedAOI:
    geometry: Polygon | MultiPolygon
    geojson: dict
    warnings: list[str]
    feature_count: int


def normalize_aoi(data: dict) -> NormalizedAOI:
    warnings: list[str] = []
    kind = data.get("type")
    if kind == "FeatureCollection":
        geometries = [shape(f["geometry"]) for f in data.get("features", []) if f.get("geometry")]
        feature_count = len(geometries)
        if not geometries:
            raise ValueError("FeatureCollection contains no geometries")
        polygonal = [g for g in geometries if g.geom_type in {"Polygon", "MultiPolygon"}]
        linear = [g for g in geometries if g.geom_type in {"LineString", "MultiLineString"}]
        if polygonal:
            geom = unary_union(polygonal)
            if linear:
                warnings.append("Non-polygon boundary features were ignored before planning.")
        elif linear:
            geom = _polygonize_linework(linear)
            warnings.append("Boundary linework was converted to polygon area before planning.")
        else:
            raise ValueError("AOI FeatureCollection must contain Polygon, MultiPolygon, or closed boundary linework")
    elif kind == "Feature":
        geom = shape(data["geometry"])
        feature_count = 1
        if geom.geom_type in {"LineString", "MultiLineString"}:
            geom = _polygonize_linework([geom])
            warnings.append("Boundary linework was converted to polygon area before planning.")
    else:
        geom = shape(data)
        feature_count = 1
        if geom.geom_type in {"LineString", "MultiLineString"}:
            geom = _polygonize_linework([geom])
            warnings.append("Boundary linework was converted to polygon area before planning.")
    if geom.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("AOI must contain polygon geometry")
    minx, miny, maxx, maxy = geom.bounds
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        raise ValueError("AOI coordinates must be WGS84 longitude/latitude")
    if not geom.is_valid:
        repaired = geom.buffer(0)
        if repaired.is_empty or repaired.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError("AOI geometry is invalid and could not be repaired")
        geom = repaired
        warnings.append("Invalid polygon topology was repaired before planning.")
    return NormalizedAOI(
        geom,
        {"type": "Feature", "properties": {}, "geometry": mapping(geom)},
        warnings,
        feature_count,
    )


def _polygonize_linework(geometries: list) -> Polygon | MultiPolygon:
    merged = unary_union(geometries)
    polygons = list(polygonize(merged))
    if not polygons:
        raise ValueError(
            "AOI contains boundary linework, not polygon area. Provide a Polygon/MultiPolygon file or closed linework."
        )
    geom = unary_union(polygons)
    minx, miny, maxx, maxy = merged.bounds
    bbox_area = max((maxx - minx) * (maxy - miny), 0)
    coverage_ratio = geom.area / bbox_area if bbox_area else 0
    if coverage_ratio < 0.05:
        raise ValueError("AOI boundary linework does not form a usable area polygon")
    if geom.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("AOI boundary linework did not produce polygon area")
    return geom


def load_aoi(path: str | Path) -> NormalizedAOI:
    return normalize_aoi(json.loads(Path(path).read_text(encoding="utf-8")))
