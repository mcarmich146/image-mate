#!/usr/bin/env python3
"""
Greedy finite-strip cover for geocoded polygons.

This version adds detailed progress logging and a faster candidate search.

The script covers an input polygon with fixed-length rectangular strips. Each
chosen strip may have a different angle.

Algorithm for each iteration:
  1. For every sampled angle in [0, 180), every sampled perpendicular offset,
     and sampled along-strip placement, score the fixed-length candidate by
     overlap area with the remaining polygon. Keep the top 3 coverage
     candidates.
  2. Select the first top-coverage candidate with <= 50% strip waste. If all
     top coverage candidates exceed that waste threshold, use the least-waste
     candidate among those top 3.
  3. Subtract that fixed-length strip from the remaining polygon.
  4. Repeat until the remaining polygon area is below tolerance, then verify
     the output union covers the AOI.

When --clip-output is enabled, output remains rectangular: each selected strip
is shortened to the minimum along-strip span that preserves its AOI intersection,
then padded at both ends by --overlap-km/--end-padding-km.

When --strip-side-buffer-km is greater than zero, the search and coverage
validation use only the center effective width of each physical strip.

Supported input/output formats:
  - GeoJSON: .geojson, .json
  - Shapefile: .shp
  - KML: .kml

Install:
  pip install geopandas shapely pyproj numpy fiona pyogrio

For KML support, your GDAL/OGR build must include KML or LIBKML support.
Conda-forge geospatial packages are usually the easiest route.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
from pyproj import CRS
from shapely.affinity import rotate
from shapely.geometry import box
from shapely.ops import unary_union

try:
    import shapely
    from shapely import area as shapely_area
    from shapely import box as shapely_box
    from shapely import intersection as shapely_intersection
except Exception:  # pragma: no cover
    shapely = None
    shapely_area = None
    shapely_box = None
    shapely_intersection = None

try:
    from shapely import make_valid as shapely_make_valid
except Exception:  # pragma: no cover
    shapely_make_valid = None

try:
    from shapely import set_precision as shapely_set_precision
except Exception:  # pragma: no cover
    shapely_set_precision = None


LOGGER = logging.getLogger("finite_strips")

SUPPORTED_DRIVERS = {
    ".geojson": "GeoJSON",
    ".json": "GeoJSON",
    ".shp": "ESRI Shapefile",
    ".kml": "KML",
}


@dataclass(frozen=True)
class BestCandidate:
    angle_deg: float
    offset_m: float
    x0_m: float
    x1_m: float
    base_area_m2: float
    base_bounds: tuple[float, float, float, float]
    finite_length_m: float
    strip_area_m2: float
    finite_rotated_strip: object
    captured_rotated_strip: object

    @property
    def unused_area_m2(self) -> float:
        return max(0.0, self.strip_area_m2 - self.base_area_m2)

    @property
    def waste_ratio(self) -> float:
        if self.strip_area_m2 <= 0.0:
            return 1.0
        return self.unused_area_m2 / self.strip_area_m2


@dataclass(frozen=True)
class SearchStats:
    angles_tested: int
    candidates_tested: int
    elapsed_s: float
    used_vectorized: bool
    used_dedensified_search: bool


def configure_logging(log_level: str, verbose: bool) -> None:
    if verbose and log_level.upper() == "INFO":
        log_level = "DEBUG"

    level = getattr(logging, log_level.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"Invalid log level: {log_level}")

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def infer_driver(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext not in SUPPORTED_DRIVERS:
        supported = ", ".join(sorted(SUPPORTED_DRIVERS))
        raise ValueError(
            f"Unsupported extension '{ext}'. Supported extensions: {supported}"
        )
    return SUPPORTED_DRIVERS[ext]


def enable_kml_for_fiona_if_available() -> None:
    """Enable KML/LIBKML in Fiona when the underlying GDAL supports it."""
    try:
        import fiona

        fiona.drvsupport.supported_drivers["KML"] = "rw"
        fiona.drvsupport.supported_drivers["LIBKML"] = "rw"
    except Exception:
        pass


def read_vector_file(path: str | Path, input_crs: str | None = None) -> gpd.GeoDataFrame:
    path = Path(path)
    driver = infer_driver(path)

    LOGGER.info("reading input file: %s", path)

    if driver == "KML":
        enable_kml_for_fiona_if_available()
        attempts = [
            {"engine": "fiona", "driver": "KML"},
            {"engine": "fiona", "driver": "LIBKML"},
            {},
        ]
    else:
        # Let GDAL infer the driver from the extension. Passing driver=... to
        # some GeoPandas/Pyogrio versions is interpreted as an open option.
        attempts = [{}, {"engine": "fiona"}]

    errors: list[str] = []
    gdf = None

    for kwargs in attempts:
        try:
            gdf = gpd.read_file(path, **kwargs)
            break
        except Exception as exc:
            errors.append(f"read_file({kwargs}) failed: {exc}")

    if gdf is None:
        raise RuntimeError(
            f"Could not read '{path}'.\n\nErrors:\n" + "\n".join(errors)
        )

    if gdf.empty:
        raise ValueError(f"Input file '{path}' has no features.")

    if gdf.crs is None:
        if input_crs:
            gdf = gdf.set_crs(input_crs, allow_override=True)
            LOGGER.warning("input had no CRS metadata; assigned %s", input_crs)
        elif driver in {"GeoJSON", "KML"}:
            # Most geocoded GeoJSON/KML files are WGS84 when CRS is omitted.
            gdf = gdf.set_crs("EPSG:4326", allow_override=True)
            LOGGER.warning("input had no CRS metadata; assuming EPSG:4326")
        else:
            raise ValueError(
                f"Input file '{path}' has no CRS metadata. Provide one with "
                f"--input-crs, for example: --input-crs EPSG:4326"
            )

    LOGGER.info("read %d features; input CRS: %s", len(gdf), gdf.crs)
    return gdf


def write_vector_file(gdf: gpd.GeoDataFrame, path: str | Path) -> None:
    path = Path(path)
    driver = infer_driver(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    LOGGER.info("writing %d strip features to %s", len(gdf), path)

    out = gdf.copy()

    if driver == "KML":
        enable_kml_for_fiona_if_available()

        # KML expects WGS84 coordinates.
        out = out.to_crs("EPSG:4326")
        out["Name"] = out["sid"].apply(lambda v: f"strip_{int(v):04d}")
        out["Description"] = out.apply(
            lambda r: (
                f"angle_deg={r['ang_deg']}; "
                f"length_km={r['len_km']}; "
                f"width_km={r['width_km']}; "
                f"effective_width_km={r['eff_w_km']}; "
                f"side_buffer_km={r['sidebuf_km']}; "
                f"overlap_km={r['ovlp_km']}"
            ),
            axis=1,
        )
        columns = [
            "Name",
            "Description",
            "sid",
            "ang_deg",
            "off_m",
            "core_km",
            "len_km",
            "base_km2",
            "new_km2",
            "strip_km2",
            "width_km",
            "eff_w_km",
            "sidebuf_km",
            "ovlp_km",
            "geometry",
        ]
        out = out[columns]
        write_attempts = ["KML", "LIBKML"]
    else:
        write_attempts = [driver]

    errors: list[str] = []
    for drv in write_attempts:
        try:
            out.to_file(path, driver=drv)
            LOGGER.info("finished writing output")
            return
        except Exception as exc:
            errors.append(f"to_file(driver={drv}) failed: {exc}")

    raise RuntimeError(f"Could not write '{path}'.\n\nErrors:\n" + "\n".join(errors))


def remove_existing_output_dataset(path: str | Path) -> None:
    """Remove stale output before running so failed runs cannot be mistaken for success."""
    path = Path(path)
    driver = infer_driver(path)

    if driver == "ESRI Shapefile":
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".fix"):
            sidecar = path.with_suffix(ext)
            if sidecar.exists():
                sidecar.unlink()
        return

    if path.exists():
        if path.is_dir():
            raise ValueError(f"Output path exists and is a directory: {path}")
        path.unlink()


def fix_geometry(geom):
    if geom is None or geom.is_empty:
        return geom
    if geom.is_valid:
        return geom
    if shapely_make_valid is not None:
        return shapely_make_valid(geom)
    return geom.buffer(0)


def maybe_set_precision(geom, precision_m: float | None):
    if precision_m is None or precision_m <= 0:
        return geom
    if shapely_set_precision is None:
        LOGGER.warning("--precision-m requested, but shapely.set_precision is unavailable")
        return geom
    if geom is None or geom.is_empty:
        return geom
    return shapely_set_precision(geom, grid_size=precision_m)


def count_polygon_vertices(geom) -> int:
    """Count boundary vertices for logging search geometry de-densification."""
    if geom is None or geom.is_empty:
        return 0

    if geom.geom_type == "Polygon":
        return len(geom.exterior.coords) + sum(len(ring.coords) for ring in geom.interiors)

    if geom.geom_type in {"MultiPolygon", "GeometryCollection"}:
        return sum(count_polygon_vertices(part) for part in geom.geoms)

    return 0


def prepare_search_geometry(remaining_geom, search_dedensify_m: float, iteration: int):
    """
    Build the internal candidate-search geometry.

    De-densification is used only to reduce candidate search cost. The selected
    strip is still recomputed, subtracted, and validated against the exact AOI.
    """
    if search_dedensify_m <= 0:
        return remaining_geom, False

    vertex_count_before = count_polygon_vertices(remaining_geom)
    search_geom = remaining_geom.simplify(search_dedensify_m, preserve_topology=True)
    search_geom = fix_geometry(search_geom)

    if search_geom is None or search_geom.is_empty:
        LOGGER.warning(
            "iteration %d: search de-densification produced empty geometry; using exact AOI",
            iteration,
        )
        return remaining_geom, False

    vertex_count_after = count_polygon_vertices(search_geom)
    area_delta_m2 = abs(search_geom.area - remaining_geom.area)
    LOGGER.info(
        "iteration %d: search de-densification active: tolerance=%.3f m, vertices=%d -> %d, area_delta=%.9f km2",
        iteration,
        search_dedensify_m,
        vertex_count_before,
        vertex_count_after,
        area_delta_m2 / 1_000_000.0,
    )
    return search_geom, True


def polygonal_part(geom):
    if geom is None or geom.is_empty:
        return None

    geom = fix_geometry(geom)

    if geom.geom_type in {"Polygon", "MultiPolygon"}:
        return geom

    if geom.geom_type == "GeometryCollection":
        parts = []
        for subgeom in geom.geoms:
            poly = polygonal_part(subgeom)
            if poly is None or poly.is_empty:
                continue
            if poly.geom_type == "Polygon":
                parts.append(poly)
            elif poly.geom_type == "MultiPolygon":
                parts.extend(list(poly.geoms))
        if not parts:
            return None
        return unary_union(parts)

    return None


def dissolve_polygonal_geometry(gdf: gpd.GeoDataFrame):
    clean_geoms = []
    for geom in gdf.geometry:
        poly = polygonal_part(geom)
        if poly is not None and not poly.is_empty:
            clean_geoms.append(poly)

    if not clean_geoms:
        raise ValueError("No polygonal geometry found in the input file.")

    dissolved = unary_union(clean_geoms)
    dissolved = fix_geometry(dissolved)

    if dissolved is None or dissolved.is_empty:
        raise ValueError("Dissolved polygon is empty after geometry cleanup.")

    return dissolved


def choose_work_crs(gdf: gpd.GeoDataFrame, work_crs: str | None = None) -> CRS:
    """Choose a metric CRS for width/length calculations."""
    if work_crs:
        return CRS.from_user_input(work_crs)

    try:
        estimated = gdf.estimate_utm_crs()
        if estimated is not None:
            return CRS.from_user_input(estimated)
    except Exception:
        pass

    # Fallback for cases where UTM cannot be estimated.
    gdf_wgs84 = gdf.to_crs("EPSG:4326")
    center = unary_union(gdf_wgs84.geometry).centroid
    return CRS.from_proj4(
        f"+proj=aeqd +lat_0={center.y} +lon_0={center.x} "
        f"+datum=WGS84 +units=m +no_defs"
    )


def iter_polygon_vertices_y(geom) -> Iterable[float]:
    """Yield y coordinates from polygon boundaries in the geometry's current CRS."""
    if geom is None or geom.is_empty:
        return

    if geom.geom_type == "Polygon":
        for _x, y in geom.exterior.coords:
            yield y
        for ring in geom.interiors:
            for _x, y in ring.coords:
                yield y
    elif geom.geom_type == "MultiPolygon":
        for part in geom.geoms:
            yield from iter_polygon_vertices_y(part)
    elif geom.geom_type == "GeometryCollection":
        for part in geom.geoms:
            yield from iter_polygon_vertices_y(part)


def iter_polygon_vertices_x(geom) -> Iterable[float]:
    """Yield x coordinates from polygon boundaries in the geometry's current CRS."""
    if geom is None or geom.is_empty:
        return

    if geom.geom_type == "Polygon":
        for x, _y in geom.exterior.coords:
            yield x
        for ring in geom.interiors:
            for x, _y in ring.coords:
                yield x
    elif geom.geom_type == "MultiPolygon":
        for part in geom.geoms:
            yield from iter_polygon_vertices_x(part)
    elif geom.geom_type == "GeometryCollection":
        for part in geom.geoms:
            yield from iter_polygon_vertices_x(part)


def build_offset_values(
    rotated_geom,
    width_m: float,
    offset_step_m: float,
    use_vertex_offsets: bool,
    max_vertex_offsets: int,
) -> np.ndarray:
    """
    Build candidate lower-edge offsets for horizontal strips in rotated space.

    A strip at offset y covers [y, y + width_m]. We scan grid offsets and,
    optionally, offsets where a strip edge aligns to an input vertex.
    """
    _minx, miny, _maxx, maxy = rotated_geom.bounds

    start = miny - width_m
    stop = maxy

    if stop < start:
        return np.array([], dtype=float)

    grid = np.arange(start, stop + offset_step_m, offset_step_m, dtype=float)
    offsets = [grid]

    if use_vertex_offsets:
        vertex_y = np.array(list(iter_polygon_vertices_y(rotated_geom)), dtype=float)
        if len(vertex_y) > max_vertex_offsets:
            LOGGER.debug(
                "skipping vertex offsets: vertex count %d exceeds max %d",
                len(vertex_y),
                max_vertex_offsets,
            )
        elif len(vertex_y) > 0:
            events = np.concatenate([vertex_y, vertex_y - width_m])
            events = events[(events >= start) & (events <= stop)]
            offsets.append(events)

    values = np.concatenate(offsets)
    values = np.unique(np.round(values, 6))
    values.sort()
    return values


def build_x_start_values(
    overlap_geom,
    strip_length_m: float,
    x_step_m: float,
    max_vertex_offsets: int,
) -> np.ndarray:
    """Build candidate fixed-length strip starts in rotated coordinates."""
    minx, _miny, maxx, _maxy = overlap_geom.bounds
    span_m = maxx - minx

    if span_m <= strip_length_m:
        centered_start = (minx + maxx - strip_length_m) / 2.0
        return np.array([centered_start], dtype=float)

    stop = maxx - strip_length_m
    if stop < minx:
        return np.array([minx], dtype=float)

    values = [np.arange(minx, stop + x_step_m, x_step_m, dtype=float)]
    values.append(np.array([stop], dtype=float))

    vertex_x = np.array(list(iter_polygon_vertices_x(overlap_geom)), dtype=float)
    if 0 < len(vertex_x) <= max_vertex_offsets:
        events = np.concatenate([vertex_x, vertex_x - strip_length_m])
        events = events[(events >= minx) & (events <= stop)]
        values.append(events)

    starts = np.concatenate(values)
    starts = np.unique(np.round(starts, 6))
    starts.sort()
    return starts


MAX_COVERAGE_CANDIDATES_TO_REVIEW = 3
MAX_ACCEPTABLE_WASTE_RATIO = 0.50


def _coverage_rank_key(cand: BestCandidate) -> tuple[float, float, float]:
    """Rank candidates for the minimum-strip objective."""
    return (-cand.base_area_m2, cand.strip_area_m2, cand.finite_length_m)


def _waste_rank_key(cand: BestCandidate) -> tuple[float, float, float, float, float]:
    """Rank fallback candidates when coverage leaders are too wasteful."""
    return (
        cand.waste_ratio,
        cand.unused_area_m2,
        -cand.base_area_m2,
        cand.strip_area_m2,
        cand.finite_length_m,
    )


def add_candidate_to_pool(
    pool: list[BestCandidate],
    cand: BestCandidate,
    max_candidates: int = MAX_COVERAGE_CANDIDATES_TO_REVIEW,
) -> list[BestCandidate]:
    pool.append(cand)
    pool.sort(key=_coverage_rank_key)
    del pool[max_candidates:]
    return pool


def choose_candidate_from_pool(pool: list[BestCandidate]) -> BestCandidate | None:
    if not pool:
        return None

    coverage_ranked = sorted(pool, key=_coverage_rank_key)
    for cand in coverage_ranked[:MAX_COVERAGE_CANDIDATES_TO_REVIEW]:
        if cand.waste_ratio <= MAX_ACCEPTABLE_WASTE_RATIO:
            return cand

    return min(
        coverage_ranked[:MAX_COVERAGE_CANDIDATES_TO_REVIEW],
        key=_waste_rank_key,
    )


def iter_polygon_components(geom):
    """Yield polygonal components from any polygonal/collection geometry."""
    if geom is None or geom.is_empty:
        return

    if geom.geom_type == "Polygon":
        yield geom
    elif geom.geom_type == "MultiPolygon":
        for part in geom.geoms:
            yield part
    elif geom.geom_type == "GeometryCollection":
        for part in geom.geoms:
            yield from iter_polygon_components(part)


def split_overlap_by_along_track_gap(overlap_geom, max_along_track_gap_m: float) -> list:
    """
    Split strip/AOI overlap into along-track clusters.

    Components separated by more than max_along_track_gap_m become separate
    candidate clusters. Gaps at or below the threshold are kept together.
    """
    if (
        overlap_geom is None
        or overlap_geom.is_empty
        or max_along_track_gap_m <= 0.0
    ):
        return [] if overlap_geom is None or overlap_geom.is_empty else [overlap_geom]

    intervals = []
    for part in iter_polygon_components(overlap_geom):
        if part is None or part.is_empty or part.area <= 0.0:
            continue
        minx, _miny, maxx, _maxy = part.bounds
        if maxx > minx:
            intervals.append((float(minx), float(maxx)))

    if not intervals:
        return [overlap_geom]

    intervals.sort()
    clusters: list[list[float]] = []
    current_min, current_max = intervals[0]
    for minx, maxx in intervals[1:]:
        if minx - current_max <= max_along_track_gap_m:
            current_max = max(current_max, maxx)
        else:
            clusters.append([current_min, current_max])
            current_min, current_max = minx, maxx
    clusters.append([current_min, current_max])

    _minx, miny, _maxx, maxy = overlap_geom.bounds
    split_geoms = []
    for minx, maxx in clusters:
        cluster_geom = overlap_geom.intersection(box(minx, miny, maxx, maxy))
        cluster_geom = fix_geometry(cluster_geom)
        if cluster_geom is not None and not cluster_geom.is_empty:
            split_geoms.append(cluster_geom)

    return split_geoms if split_geoms else [overlap_geom]


def choose_cluster_for_preferred_bounds(clusters: list, preferred_bounds):
    if not clusters:
        return None
    if preferred_bounds is None:
        return max(clusters, key=lambda geom: float(geom.area))

    preferred_minx = float(preferred_bounds[0])
    preferred_maxx = float(preferred_bounds[2])

    def rank(cluster) -> tuple[float, float]:
        minx, _miny, maxx, _maxy = cluster.bounds
        interval_overlap_m = max(
            0.0,
            min(float(maxx), preferred_maxx) - max(float(minx), preferred_minx),
        )
        return (interval_overlap_m, float(cluster.area))

    return max(clusters, key=rank)


def make_candidate_from_hit(
    angle_deg: float,
    offset_m: float,
    best_start: float,
    strip_width_m: float,
    physical_strip_width_m: float,
    strip_length_m: float,
    hit,
    use_cluster_capture: bool,
) -> BestCandidate | None:
    if hit is None or hit.is_empty:
        return None

    base_minx, base_miny, base_maxx, base_maxy = hit.bounds
    x1_m = best_start + strip_length_m
    finite_rotated_strip = box(
        best_start,
        float(offset_m),
        x1_m,
        float(offset_m) + strip_width_m,
    )

    if use_cluster_capture:
        captured_rotated_strip = box(
            float(base_minx),
            float(offset_m),
            float(base_maxx),
            float(offset_m) + strip_width_m,
        )
    else:
        captured_rotated_strip = finite_rotated_strip

    return BestCandidate(
        angle_deg=float(angle_deg),
        offset_m=float(offset_m),
        x0_m=float(best_start),
        x1_m=float(x1_m),
        base_area_m2=float(hit.area),
        base_bounds=(
            float(base_minx),
            float(base_miny),
            float(base_maxx),
            float(base_maxy),
        ),
        finite_length_m=float(strip_length_m),
        strip_area_m2=float(strip_length_m * physical_strip_width_m),
        finite_rotated_strip=finite_rotated_strip,
        captured_rotated_strip=captured_rotated_strip,
    )


def make_candidates_from_overlap(
    angle_deg: float,
    offset_m: float,
    strip_width_m: float,
    physical_strip_width_m: float,
    strip_length_m: float,
    x_step_m: float,
    max_vertex_offsets: int,
    max_along_track_gap_m: float,
    overlap_geom,
) -> list[BestCandidate]:
    if overlap_geom is None or overlap_geom.is_empty:
        return []

    candidates = []
    overlap_clusters = split_overlap_by_along_track_gap(
        overlap_geom,
        max_along_track_gap_m=max_along_track_gap_m,
    )

    for overlap_cluster in overlap_clusters:
        best_hit = None
        best_start = None
        best_area_m2 = 0.0

        for x0_m in build_x_start_values(
            overlap_cluster,
            strip_length_m=strip_length_m,
            x_step_m=x_step_m,
            max_vertex_offsets=max_vertex_offsets,
        ):
            fixed_strip = box(
                float(x0_m),
                float(offset_m),
                float(x0_m) + strip_length_m,
                float(offset_m) + strip_width_m,
            )
            hit = overlap_cluster.intersection(fixed_strip)
            if hit.is_empty:
                continue

            area_m2 = float(hit.area)
            if area_m2 > best_area_m2:
                best_area_m2 = area_m2
                best_hit = hit
                best_start = float(x0_m)

        if best_hit is None or best_start is None or best_area_m2 <= 0.0:
            continue

        cand = make_candidate_from_hit(
            angle_deg=angle_deg,
            offset_m=offset_m,
            best_start=best_start,
            strip_width_m=strip_width_m,
            physical_strip_width_m=physical_strip_width_m,
            strip_length_m=strip_length_m,
            hit=best_hit,
            use_cluster_capture=max_along_track_gap_m > 0.0,
        )
        if cand is not None:
            candidates.append(cand)

    return candidates


def exact_candidate_for_angle_offset(
    remaining_geom,
    origin,
    angle_deg: float,
    offset_m: float,
    x0_m: float,
    strip_width_m: float,
    physical_strip_width_m: float,
    strip_length_m: float,
    preferred_base_bounds: tuple[float, float, float, float] | None,
    max_along_track_gap_m: float,
) -> BestCandidate | None:
    rotated_remaining = rotate(
        remaining_geom,
        -float(angle_deg),
        origin=origin,
        use_radians=False,
    )
    rotated_remaining = fix_geometry(rotated_remaining)
    if rotated_remaining is None or rotated_remaining.is_empty:
        return None

    rotated_strip = box(
        float(x0_m),
        float(offset_m),
        float(x0_m) + strip_length_m,
        float(offset_m) + strip_width_m,
    )
    overlap_geom = rotated_remaining.intersection(rotated_strip)
    overlap_geom = fix_geometry(overlap_geom)
    if overlap_geom is None or overlap_geom.is_empty:
        return None

    overlap_clusters = split_overlap_by_along_track_gap(
        overlap_geom,
        max_along_track_gap_m=max_along_track_gap_m,
    )
    selected_overlap = choose_cluster_for_preferred_bounds(
        overlap_clusters,
        preferred_bounds=preferred_base_bounds,
    )
    if selected_overlap is None or selected_overlap.is_empty:
        return None

    return make_candidate_from_hit(
        angle_deg=angle_deg,
        offset_m=offset_m,
        best_start=float(x0_m),
        strip_width_m=strip_width_m,
        physical_strip_width_m=physical_strip_width_m,
        strip_length_m=strip_length_m,
        hit=selected_overlap,
        use_cluster_capture=max_along_track_gap_m > 0.0,
    )


def evaluate_offsets_loop(
    rotated_remaining,
    angle_deg: float,
    offsets: np.ndarray,
    broad_minx: float,
    broad_maxx: float,
    strip_width_m: float,
    physical_strip_width_m: float,
    strip_length_m: float,
    x_step_m: float,
    min_gain_area_m2: float,
    max_vertex_offsets: int,
    max_along_track_gap_m: float,
    candidate_pool: list[BestCandidate],
) -> list[BestCandidate]:
    for offset_m in offsets:
        rotated_strip = box(
            broad_minx,
            float(offset_m),
            broad_maxx,
            float(offset_m) + strip_width_m,
        )

        overlap_geom = rotated_remaining.intersection(rotated_strip)
        if overlap_geom.is_empty:
            continue

        base_area_m2 = overlap_geom.area
        if base_area_m2 < min_gain_area_m2:
            continue

        candidates = make_candidates_from_overlap(
            angle_deg=angle_deg,
            offset_m=float(offset_m),
            strip_width_m=strip_width_m,
            physical_strip_width_m=physical_strip_width_m,
            strip_length_m=strip_length_m,
            x_step_m=x_step_m,
            max_vertex_offsets=max_vertex_offsets,
            max_along_track_gap_m=max_along_track_gap_m,
            overlap_geom=overlap_geom,
        )
        for cand in candidates:
            add_candidate_to_pool(candidate_pool, cand)

    return candidate_pool


def evaluate_offsets_vectorized(
    rotated_remaining,
    angle_deg: float,
    offsets: np.ndarray,
    broad_minx: float,
    broad_maxx: float,
    strip_width_m: float,
    physical_strip_width_m: float,
    strip_length_m: float,
    x_step_m: float,
    min_gain_area_m2: float,
    max_vertex_offsets: int,
    max_along_track_gap_m: float,
    candidate_pool: list[BestCandidate],
    chunk_size: int,
) -> list[BestCandidate]:
    """
    Score offsets in chunks using Shapely 2 vectorized ufuncs.

    This avoids thousands of Python-level intersection calls. The final best
    overlap geometry in each chunk is still inspected exactly to compute the
    minimum along-strip span.
    """
    if shapely_box is None or shapely_intersection is None or shapely_area is None:
        return evaluate_offsets_loop(
            rotated_remaining=rotated_remaining,
            angle_deg=angle_deg,
            offsets=offsets,
            broad_minx=broad_minx,
            broad_maxx=broad_maxx,
            strip_width_m=strip_width_m,
            physical_strip_width_m=physical_strip_width_m,
            strip_length_m=strip_length_m,
            x_step_m=x_step_m,
            min_gain_area_m2=min_gain_area_m2,
            max_vertex_offsets=max_vertex_offsets,
            max_along_track_gap_m=max_along_track_gap_m,
            candidate_pool=candidate_pool,
        )

    chunk_size = max(1, int(chunk_size))

    for start in range(0, len(offsets), chunk_size):
        offset_chunk = offsets[start : start + chunk_size]
        if len(offset_chunk) == 0:
            continue

        try:
            boxes = shapely_box(
                np.full(len(offset_chunk), broad_minx, dtype=float),
                offset_chunk,
                np.full(len(offset_chunk), broad_maxx, dtype=float),
                offset_chunk + strip_width_m,
            )
            overlaps = shapely_intersection(boxes, rotated_remaining)
            areas = np.asarray(shapely_area(overlaps), dtype=float)
        except Exception as exc:
            LOGGER.debug("vectorized offset scoring failed; using loop: %s", exc)
            return evaluate_offsets_loop(
                rotated_remaining=rotated_remaining,
                angle_deg=angle_deg,
                offsets=offsets,
                broad_minx=broad_minx,
                broad_maxx=broad_maxx,
                strip_width_m=strip_width_m,
                physical_strip_width_m=physical_strip_width_m,
                strip_length_m=strip_length_m,
                x_step_m=x_step_m,
                min_gain_area_m2=min_gain_area_m2,
                max_vertex_offsets=max_vertex_offsets,
                max_along_track_gap_m=max_along_track_gap_m,
                candidate_pool=candidate_pool,
            )

        valid_indexes = np.flatnonzero(areas >= min_gain_area_m2)
        if len(valid_indexes) == 0:
            continue

        local_areas = areas[valid_indexes]
        keep_count = min(MAX_COVERAGE_CANDIDATES_TO_REVIEW, len(valid_indexes))
        top_local_indexes = valid_indexes[
            np.argpartition(local_areas, -keep_count)[-keep_count:]
        ]

        for local_idx in top_local_indexes:
            overlap_geom = overlaps[int(local_idx)]
            candidates = make_candidates_from_overlap(
                angle_deg=angle_deg,
                offset_m=float(offset_chunk[int(local_idx)]),
                strip_width_m=strip_width_m,
                physical_strip_width_m=physical_strip_width_m,
                strip_length_m=strip_length_m,
                x_step_m=x_step_m,
                max_vertex_offsets=max_vertex_offsets,
                max_along_track_gap_m=max_along_track_gap_m,
                overlap_geom=overlap_geom,
            )
            for cand in candidates:
                add_candidate_to_pool(candidate_pool, cand)

    return candidate_pool


def find_best_strip_for_remaining(
    remaining_geom,
    origin,
    strip_width_m: float,
    physical_strip_width_m: float,
    strip_length_m: float,
    overlap_m: float,
    angle_step_deg: float,
    offset_step_m: float,
    use_vertex_offsets: bool,
    max_vertex_offsets: int,
    min_gain_area_m2: float,
    search_dedensify_m: float,
    max_along_track_gap_m: float,
    use_vectorized: bool,
    candidate_chunk_size: int,
    progress_every_angles: int,
    iteration: int,
) -> tuple[BestCandidate | None, SearchStats]:
    """
    Step 1 and Step 2 of the requested algorithm.

    For each angle and offset, this tests a full-length candidate strip against
    the remaining polygon. The best candidate is then recomputed on the exact
    remaining geometry and converted to a finite padded strip.
    """
    start_time = time.monotonic()
    candidate_pool: list[BestCandidate] = []

    angles = np.arange(0.0, 180.0, angle_step_deg, dtype=float)

    candidates_tested = 0
    search_geom, used_dedensified_search = prepare_search_geometry(
        remaining_geom=remaining_geom,
        search_dedensify_m=search_dedensify_m,
        iteration=iteration,
    )

    LOGGER.info(
        "iteration %d: candidate search started: angles=%d, angle_step=%.3f deg, offset_step=%.3f km, vectorized=%s, vertex_offsets=%s, search_dedensify=%.3f m, max_along_gap=%.3f km, objective=top-coverage-with-waste-gate",
        iteration,
        len(angles),
        angle_step_deg,
        offset_step_m / 1000.0,
        bool(use_vectorized and shapely_box is not None),
        use_vertex_offsets,
        search_dedensify_m,
        max_along_track_gap_m / 1000.0,
    )

    for angle_index, angle_deg in enumerate(angles, start=1):
        angle_start_time = time.monotonic()

        rotated_remaining = rotate(
            search_geom,
            -float(angle_deg),
            origin=origin,
            use_radians=False,
        )
        rotated_remaining = fix_geometry(rotated_remaining)
        if rotated_remaining is None or rotated_remaining.is_empty:
            continue

        minx, _miny, maxx, _maxy = rotated_remaining.bounds
        margin_x = max(strip_width_m * 2.0, strip_length_m * 0.1, overlap_m * 2.0, 1000.0)
        broad_minx = minx - margin_x
        broad_maxx = maxx + margin_x

        offsets = build_offset_values(
            rotated_geom=rotated_remaining,
            width_m=strip_width_m,
            offset_step_m=offset_step_m,
            use_vertex_offsets=use_vertex_offsets,
            max_vertex_offsets=max_vertex_offsets,
        )
        candidates_tested += len(offsets)

        if len(offsets) == 0:
            continue

        if use_vectorized:
            candidate_pool = evaluate_offsets_vectorized(
                rotated_remaining=rotated_remaining,
                angle_deg=float(angle_deg),
                offsets=offsets,
                broad_minx=broad_minx,
                broad_maxx=broad_maxx,
                strip_width_m=strip_width_m,
                physical_strip_width_m=physical_strip_width_m,
                strip_length_m=strip_length_m,
                x_step_m=offset_step_m,
                min_gain_area_m2=min_gain_area_m2,
                max_vertex_offsets=max_vertex_offsets,
                max_along_track_gap_m=max_along_track_gap_m,
                candidate_pool=candidate_pool,
                chunk_size=candidate_chunk_size,
            )
        else:
            candidate_pool = evaluate_offsets_loop(
                rotated_remaining=rotated_remaining,
                angle_deg=float(angle_deg),
                offsets=offsets,
                broad_minx=broad_minx,
                broad_maxx=broad_maxx,
                strip_width_m=strip_width_m,
                physical_strip_width_m=physical_strip_width_m,
                strip_length_m=strip_length_m,
                x_step_m=offset_step_m,
                min_gain_area_m2=min_gain_area_m2,
                max_vertex_offsets=max_vertex_offsets,
                max_along_track_gap_m=max_along_track_gap_m,
                candidate_pool=candidate_pool,
            )

        best_for_log = choose_candidate_from_pool(candidate_pool)
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                "iteration %d: angle %.3f deg done (%d/%d), offsets=%d, elapsed=%.2fs, best_area=%.6f km2, best_waste=%.2f%%",
                iteration,
                angle_deg,
                angle_index,
                len(angles),
                len(offsets),
                time.monotonic() - angle_start_time,
                0.0 if best_for_log is None else best_for_log.base_area_m2 / 1_000_000.0,
                0.0 if best_for_log is None else best_for_log.waste_ratio * 100.0,
            )
        elif progress_every_angles > 0 and (
            angle_index == 1
            or angle_index == len(angles)
            or angle_index % progress_every_angles == 0
        ):
            LOGGER.info(
                "iteration %d: searched angles %d/%d, candidates=%d, elapsed=%.1fs, best_area=%.6f km2, best_waste=%.2f%%",
                iteration,
                angle_index,
                len(angles),
                candidates_tested,
                time.monotonic() - start_time,
                0.0 if best_for_log is None else best_for_log.base_area_m2 / 1_000_000.0,
                0.0 if best_for_log is None else best_for_log.waste_ratio * 100.0,
            )

    elapsed_s = time.monotonic() - start_time
    stats = SearchStats(
        angles_tested=len(angles),
        candidates_tested=candidates_tested,
        elapsed_s=elapsed_s,
        used_vectorized=bool(use_vectorized and shapely_box is not None),
        used_dedensified_search=used_dedensified_search,
    )

    best = choose_candidate_from_pool(candidate_pool)
    if best is None:
        return None, stats

    # If de-densified geometry was used for speed, recompute the selected strip on
    # the exact remaining geometry. This preserves exact subtraction/output.
    exact_best = exact_candidate_for_angle_offset(
        remaining_geom=remaining_geom,
        origin=origin,
        angle_deg=best.angle_deg,
        offset_m=best.offset_m,
        x0_m=best.x0_m,
        strip_width_m=strip_width_m,
        physical_strip_width_m=physical_strip_width_m,
        strip_length_m=strip_length_m,
        preferred_base_bounds=best.base_bounds,
        max_along_track_gap_m=max_along_track_gap_m,
    )
    if exact_best is None:
        LOGGER.warning(
            "iteration %d: de-densified-search candidate had no exact overlap; falling back to approximate candidate",
            iteration,
        )
        exact_best = best

    LOGGER.info(
        "iteration %d: candidate search finished: best_angle=%.3f deg, offset=%.1f m, base=%.6f km2, length=%.3f km, waste=%.2f%%, candidates=%d, elapsed=%.1fs",
        iteration,
        exact_best.angle_deg,
        exact_best.offset_m,
        exact_best.base_area_m2 / 1_000_000.0,
        exact_best.finite_length_m / 1000.0,
        exact_best.waste_ratio * 100.0,
        candidates_tested,
        elapsed_s,
    )

    return exact_best, stats


def make_physical_rotated_strip(
    x0_m: float,
    x1_m: float,
    effective_offset_m: float,
    effective_strip_width_m: float,
    strip_side_buffer_m: float,
):
    """Expand an effective coverage swath to the full physical strip width."""
    return box(
        float(x0_m),
        float(effective_offset_m) - strip_side_buffer_m,
        float(x1_m),
        float(effective_offset_m) + effective_strip_width_m + strip_side_buffer_m,
    )


def greedy_finite_strip_cover(
    target_geom,
    strip_width_m: float,
    effective_strip_width_m: float,
    strip_side_buffer_m: float,
    strip_length_m: float,
    overlap_m: float,
    angle_step_deg: float,
    offset_step_m: float,
    tolerance_area_m2: float,
    min_gain_area_m2: float,
    min_progress_area_m2: float,
    max_strips: int | None,
    max_iterations: int,
    use_vertex_offsets: bool,
    max_vertex_offsets: int,
    search_dedensify_m: float,
    max_along_track_gap_m: float,
    precision_m: float | None,
    use_vectorized: bool,
    candidate_chunk_size: int,
    progress_every_angles: int,
):
    """Repeat the requested search/pad/subtract loop until covered."""
    origin = target_geom.centroid
    total_area_m2 = target_geom.area
    remaining = target_geom
    selected_rows = []
    search_stats_rows: list[SearchStats] = []

    LOGGER.info("target area: %.6f km2", total_area_m2 / 1_000_000.0)
    LOGGER.info("target bounds in working CRS: %s", tuple(round(v, 3) for v in target_geom.bounds))

    iteration = 0
    while remaining is not None and not remaining.is_empty:
        remaining_area_m2 = remaining.area
        if remaining_area_m2 <= tolerance_area_m2:
            LOGGER.info(
                "stopping: remaining area %.9f km2 is <= tolerance %.9f km2",
                remaining_area_m2 / 1_000_000.0,
                tolerance_area_m2 / 1_000_000.0,
            )
            break

        if max_strips is not None and iteration >= max_strips:
            LOGGER.warning("stopping: reached --max-strips=%d", max_strips)
            break

        if max_iterations is not None and iteration >= max_iterations:
            LOGGER.warning("stopping: reached --max-iterations=%d", max_iterations)
            break

        covered_pct = 100.0 * (1.0 - remaining_area_m2 / total_area_m2)
        LOGGER.info(
            "iteration %d started: remaining=%.6f km2, covered=%.4f%%, selected=%d",
            iteration,
            remaining_area_m2 / 1_000_000.0,
            covered_pct,
            len(selected_rows),
        )

        best, stats = find_best_strip_for_remaining(
            remaining_geom=remaining,
            origin=origin,
            strip_width_m=effective_strip_width_m,
            physical_strip_width_m=strip_width_m,
            strip_length_m=strip_length_m,
            overlap_m=overlap_m,
            angle_step_deg=angle_step_deg,
            offset_step_m=offset_step_m,
            use_vertex_offsets=use_vertex_offsets,
            max_vertex_offsets=max_vertex_offsets,
            min_gain_area_m2=min_gain_area_m2,
            search_dedensify_m=search_dedensify_m,
            max_along_track_gap_m=max_along_track_gap_m,
            use_vectorized=use_vectorized,
            candidate_chunk_size=candidate_chunk_size,
            progress_every_angles=progress_every_angles,
            iteration=iteration,
        )
        search_stats_rows.append(stats)

        if best is None:
            LOGGER.warning(
                "iteration %d: no candidate met min_gain_area %.9f km2; retrying with near-zero threshold",
                iteration,
                min_gain_area_m2 / 1_000_000.0,
            )
            best, retry_stats = find_best_strip_for_remaining(
                remaining_geom=remaining,
                origin=origin,
                strip_width_m=effective_strip_width_m,
                physical_strip_width_m=strip_width_m,
                strip_length_m=strip_length_m,
                overlap_m=overlap_m,
                angle_step_deg=angle_step_deg,
                offset_step_m=offset_step_m,
                use_vertex_offsets=use_vertex_offsets,
                max_vertex_offsets=max_vertex_offsets,
                min_gain_area_m2=max(1.0, tolerance_area_m2 * 0.001),
                search_dedensify_m=search_dedensify_m,
                max_along_track_gap_m=max_along_track_gap_m,
                use_vectorized=use_vectorized,
                candidate_chunk_size=candidate_chunk_size,
                progress_every_angles=progress_every_angles,
                iteration=iteration,
            )
            search_stats_rows.append(retry_stats)

        if best is None:
            LOGGER.warning("stopping: no usable candidate found")
            break

        coverage_strip = rotate(
            best.captured_rotated_strip,
            best.angle_deg,
            origin=origin,
            use_radians=False,
        )
        coverage_strip = fix_geometry(coverage_strip)

        physical_rotated_strip = make_physical_rotated_strip(
            x0_m=best.x0_m,
            x1_m=best.x1_m,
            effective_offset_m=best.offset_m,
            effective_strip_width_m=effective_strip_width_m,
            strip_side_buffer_m=strip_side_buffer_m,
        )
        finite_strip = rotate(
            physical_rotated_strip,
            best.angle_deg,
            origin=origin,
            use_radians=False,
        )
        finite_strip = fix_geometry(finite_strip)

        newly_covered = remaining.intersection(coverage_strip)
        newly_covered = fix_geometry(newly_covered)
        new_area_m2 = (
            0.0 if newly_covered is None or newly_covered.is_empty else newly_covered.area
        )

        if new_area_m2 <= 0.0:
            LOGGER.warning("stopping: selected strip produced zero new coverage")
            break

        selected_rows.append(
            {
                "sid": iteration,
                "ang_deg": best.angle_deg,
                "off_m": best.offset_m,
                "core_km": max(0.0, best.base_bounds[2] - best.base_bounds[0]) / 1000.0,
                "len_km": best.finite_length_m / 1000.0,
                "base_km2": best.base_area_m2 / 1_000_000.0,
                "new_km2": new_area_m2 / 1_000_000.0,
                "strip_km2": best.strip_area_m2 / 1_000_000.0,
                "unused_km2": max(0.0, best.strip_area_m2 - new_area_m2) / 1_000_000.0,
                "eff_w_km": effective_strip_width_m / 1000.0,
                "sidebuf_km": strip_side_buffer_m / 1000.0,
                "coverage_geometry": coverage_strip,
                "geometry": finite_strip,
            }
        )

        before_area_m2 = remaining_area_m2
        remaining = remaining.difference(coverage_strip)
        remaining = fix_geometry(remaining)
        remaining = maybe_set_precision(remaining, precision_m)
        remaining = fix_geometry(remaining)

        after_area_m2 = 0.0 if remaining is None or remaining.is_empty else remaining.area
        actual_progress_m2 = max(0.0, before_area_m2 - after_area_m2)
        covered_pct_after = 100.0 * (1.0 - after_area_m2 / total_area_m2)

        LOGGER.info(
            "iteration %d finished: angle=%.3f deg, length=%.3f km, new=%.6f km2, remaining=%.6f km2, covered=%.4f%%",
            iteration,
            best.angle_deg,
            best.finite_length_m / 1000.0,
            actual_progress_m2 / 1_000_000.0,
            after_area_m2 / 1_000_000.0,
            covered_pct_after,
        )

        if actual_progress_m2 < min_progress_area_m2:
            LOGGER.warning(
                "stopping: progress %.9f km2 is below --min-progress-area-km2 %.9f; this avoids a possible sliver loop",
                actual_progress_m2 / 1_000_000.0,
                min_progress_area_m2 / 1_000_000.0,
            )
            break

        iteration += 1

    covered_area_m2 = total_area_m2
    uncovered_area_m2 = 0.0
    if remaining is not None and not remaining.is_empty:
        uncovered_area_m2 = remaining.area
        covered_area_m2 = total_area_m2 - uncovered_area_m2

    return (
        selected_rows,
        remaining,
        covered_area_m2 / total_area_m2,
        uncovered_area_m2,
        search_stats_rows,
    )


def padded_minimum_coverage_strip(
    row: dict,
    target_geom,
    origin,
    effective_strip_width_m: float,
    strip_side_buffer_m: float,
    end_padding_m: float,
):
    """
    Return a rectangular strip trimmed to the AOI coverage span, plus end padding.

    The current full strip's AOI intersection defines the coverage that must be
    preserved. The output remains a rectangle in the strip coordinate frame.
    """
    original_coverage_strip = row.get("coverage_geometry", row["geometry"])
    coverage_geom = original_coverage_strip.intersection(target_geom)
    coverage_geom = fix_geometry(coverage_geom)
    if coverage_geom is None or coverage_geom.is_empty:
        return None, None, 0.0, 0.0

    angle_deg = float(row["ang_deg"])
    rotated_coverage = rotate(
        coverage_geom,
        -angle_deg,
        origin=origin,
        use_radians=False,
    )
    rotated_coverage = fix_geometry(rotated_coverage)
    if rotated_coverage is None or rotated_coverage.is_empty:
        return None, None, 0.0, 0.0

    minx, _miny, maxx, _maxy = rotated_coverage.bounds
    core_length_m = max(0.0, float(maxx) - float(minx))
    x0_m = float(minx) - end_padding_m
    x1_m = float(maxx) + end_padding_m
    length_m = max(0.0, x1_m - x0_m)
    if length_m <= 0.0:
        return None, None, 0.0, 0.0

    effective_y0_m = float(row["off_m"])
    trimmed_rotated_strip = make_physical_rotated_strip(
        x0_m=x0_m,
        x1_m=x1_m,
        effective_offset_m=effective_y0_m,
        effective_strip_width_m=effective_strip_width_m,
        strip_side_buffer_m=strip_side_buffer_m,
    )
    trimmed_rotated_coverage_strip = box(
        x0_m,
        effective_y0_m,
        x1_m,
        effective_y0_m + effective_strip_width_m,
    )
    trimmed_strip = rotate(
        trimmed_rotated_strip,
        angle_deg,
        origin=origin,
        use_radians=False,
    )
    trimmed_strip = fix_geometry(trimmed_strip)
    if trimmed_strip is None or trimmed_strip.is_empty:
        return None, None, 0.0, 0.0

    trimmed_coverage_strip = rotate(
        trimmed_rotated_coverage_strip,
        angle_deg,
        origin=origin,
        use_radians=False,
    )
    trimmed_coverage_strip = fix_geometry(trimmed_coverage_strip)
    if trimmed_coverage_strip is None or trimmed_coverage_strip.is_empty:
        return None, None, 0.0, 0.0

    return trimmed_strip, trimmed_coverage_strip, length_m, core_length_m


def build_output_gdf(
    selected_rows: list[dict],
    target_geom,
    work_crs,
    original_crs,
    width_km: float,
    strip_side_buffer_km: float,
    overlap_km: float,
    clip_output: bool,
) -> gpd.GeoDataFrame:
    rows = []
    origin = target_geom.centroid
    strip_width_m = width_km * 1000.0
    strip_side_buffer_m = strip_side_buffer_km * 1000.0
    effective_strip_width_m = strip_width_m - 2.0 * strip_side_buffer_m
    end_padding_m = overlap_km * 1000.0

    for row in selected_rows:
        geom = row["geometry"]
        coverage_geom = row.get("coverage_geometry", geom)
        length_m = float(row["len_km"]) * 1000.0
        core_length_m = float(row["core_km"]) * 1000.0

        if clip_output:
            geom, coverage_geom, length_m, core_length_m = padded_minimum_coverage_strip(
                row=row,
                target_geom=target_geom,
                origin=origin,
                effective_strip_width_m=effective_strip_width_m,
                strip_side_buffer_m=strip_side_buffer_m,
                end_padding_m=end_padding_m,
            )
        if (
            geom is None
            or geom.is_empty
            or coverage_geom is None
            or coverage_geom.is_empty
        ):
            continue

        out = {key: value for key, value in row.items() if key != "coverage_geometry"}
        target_overlap = coverage_geom.intersection(target_geom)
        target_overlap = fix_geometry(target_overlap)
        target_overlap_area_m2 = (
            0.0 if target_overlap is None or target_overlap.is_empty else target_overlap.area
        )
        strip_area_m2 = float(geom.area)
        out["core_km"] = core_length_m / 1000.0
        out["len_km"] = length_m / 1000.0
        out["strip_km2"] = strip_area_m2 / 1_000_000.0
        out["unused_km2"] = max(0.0, strip_area_m2 - target_overlap_area_m2) / 1_000_000.0
        out["width_km"] = width_km
        out["eff_w_km"] = effective_strip_width_m / 1000.0
        out["sidebuf_km"] = strip_side_buffer_km
        out["ovlp_km"] = overlap_km
        out["geometry"] = geom
        rows.append(out)

    columns = [
        "sid",
        "ang_deg",
        "off_m",
        "core_km",
        "len_km",
        "base_km2",
        "new_km2",
        "strip_km2",
        "unused_km2",
        "width_km",
        "eff_w_km",
        "sidebuf_km",
        "ovlp_km",
        "geometry",
    ]

    if not rows:
        return gpd.GeoDataFrame(columns=columns, crs=original_crs)

    result_work = gpd.GeoDataFrame(rows, crs=work_crs)
    return result_work.to_crs(original_crs)


def effective_coverage_geometries_from_output(
    output_work: gpd.GeoDataFrame,
    target_geom,
    strip_side_buffer_m: float,
) -> list:
    """Reconstruct the center coverage swath from output strips and metadata."""
    if strip_side_buffer_m <= 0:
        return list(output_work.geometry)

    origin = target_geom.centroid
    coverage_geoms = []

    for _idx, row in output_work.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        try:
            angle_deg = float(row["ang_deg"])
            effective_offset_m = float(row["off_m"])
            effective_width_m = float(row["eff_w_km"]) * 1000.0
        except Exception:
            LOGGER.warning(
                "output is missing effective coverage metadata; falling back to full strip geometry"
            )
            coverage_geoms.append(geom)
            continue

        rotated_geom = rotate(
            geom,
            -angle_deg,
            origin=origin,
            use_radians=False,
        )
        rotated_geom = fix_geometry(rotated_geom)
        if rotated_geom is None or rotated_geom.is_empty:
            continue

        minx, _miny, maxx, _maxy = rotated_geom.bounds
        coverage_rotated = box(
            float(minx),
            effective_offset_m,
            float(maxx),
            effective_offset_m + effective_width_m,
        )
        coverage_geom = rotate(
            coverage_rotated,
            angle_deg,
            origin=origin,
            use_radians=False,
        )
        coverage_geom = fix_geometry(coverage_geom)
        if coverage_geom is not None and not coverage_geom.is_empty:
            coverage_geoms.append(coverage_geom)

    return coverage_geoms


def output_gap_area_m2(
    output_gdf: gpd.GeoDataFrame,
    target_geom,
    work_crs,
    strip_side_buffer_m: float,
) -> float:
    if output_gdf.empty:
        return target_geom.area

    output_work = output_gdf.to_crs(work_crs)
    coverage_geoms = effective_coverage_geometries_from_output(
        output_work=output_work,
        target_geom=target_geom,
        strip_side_buffer_m=strip_side_buffer_m,
    )
    if not coverage_geoms:
        return target_geom.area

    strip_union = unary_union(coverage_geoms)
    gap = target_geom.difference(strip_union)
    gap = fix_geometry(gap)
    if gap is None or gap.is_empty:
        return 0.0
    return float(gap.area)


def written_output_gap_area_m2(
    output_path: str | Path,
    target_geom,
    work_crs,
    original_crs,
    strip_side_buffer_m: float,
) -> float:
    output_gdf = read_vector_file(str(output_path), input_crs=str(original_crs))
    return output_gap_area_m2(
        output_gdf,
        target_geom,
        work_crs,
        strip_side_buffer_m=strip_side_buffer_m,
    )


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return number


def nonnegative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cover a polygon with finite, variable-angle, overlapping strips."
    )

    parser.add_argument("input", help="Input polygon: .geojson, .json, .shp, or .kml")
    parser.add_argument("output", help="Output strips: .geojson, .json, .shp, or .kml")

    parser.add_argument(
        "--width-km",
        type=positive_float,
        default=5.0,
        help="Strip width in kilometers. Default: 5",
    )
    parser.add_argument(
        "--strip-side-buffer-km",
        type=nonnegative_float,
        default=0.25,
        help=(
            "Safety buffer excluded from coverage on each side of the physical "
            "strip width. Example: width 5 and buffer 0.25 gives 4.5 km "
            "effective coverage width. Default: 0"
        ),
    )
    parser.add_argument(
        "--length-km",
        type=positive_float,
        default=50.0,
        help="Fixed strip length in kilometers. Default: 50",
    )
    parser.add_argument(
        "--overlap-km",
        "--end-padding-km",
        dest="overlap_km",
        type=nonnegative_float,
        default=1.0,
        help=(
            "End padding in kilometers added to both ends when --clip-output "
            "post-processes strips to their minimum AOI coverage span. Default: 1"
        ),
    )
    parser.add_argument(
        "--angle-step",
        type=positive_float,
        default=1.0,
        help="Angle sampling step in degrees. Smaller is better but slower. Default: 5",
    )
    parser.add_argument(
        "--offset-step-km",
        type=positive_float,
        default=0.5,
        help="Perpendicular offset sampling step in kilometers. Default: 0.5",
    )
    parser.add_argument(
        "--max-along-track-gap-km",
        type=nonnegative_float,
        default=5.0,
        help=(
            "Maximum empty along-track gap allowed inside one captured AOI "
            "cluster. Larger gaps split the overlap into separate candidate "
            "clusters. Use 0 to disable. Default: 5"
        ),
    )
    parser.add_argument(
        "--tolerance-area-km2",
        type=nonnegative_float,
        default=0.001,
        help="Stop once remaining area is below this value. Default: 0.001",
    )
    parser.add_argument(
        "--min-gain-area-km2",
        type=nonnegative_float,
        default=0.0001,
        help="Ignore candidate strips below this remaining-area gain. Default: 0.0001",
    )
    parser.add_argument(
        "--min-progress-area-km2",
        type=nonnegative_float,
        default=0.000001,
        help=(
            "Stop if an iteration removes less than this area. This prevents "
            "sliver loops. Default: 0.000001"
        ),
    )
    parser.add_argument(
        "--max-strips",
        type=int,
        default=None,
        help="Optional maximum number of strips.",
    )
    parser.add_argument(
        "--max-iterations",
        type=positive_int,
        default=10000,
        help="Safety cap on iterations. Default: 10000",
    )

    # Fast default: vertex-derived offsets are OFF. They can multiply the search
    # space by thousands on detailed polygons. Turn them on only for final runs.
    parser.set_defaults(vertex_offsets=False)
    parser.add_argument(
        "--vertex-offsets",
        dest="vertex_offsets",
        action="store_true",
        help=(
            "Add candidate offsets where strip edges align with polygon vertices. "
            "This may improve results but can be much slower. Default: off"
        ),
    )
    parser.add_argument(
        "--no-vertex-offsets",
        dest="vertex_offsets",
        action="store_false",
        help="Compatibility option; vertex offsets are already off by default.",
    )
    parser.add_argument(
        "--max-vertex-offsets",
        type=int,
        default=5000,
        help="Maximum vertex count for adding vertex-derived offsets. Default: 5000",
    )
    parser.add_argument(
        "--search-dedensify-m",
        "--search-simplify-m",
        dest="search_dedensify_m",
        type=nonnegative_float,
        default=50.0,
        metavar="METERS",
        help=(
            "Build an internal de-densified remaining geometry with this "
            "topology-preserving tolerance for candidate scoring only. The "
            "selected strip is still rescored, subtracted, and coverage-validated "
            "against the exact AOI. Use 0 to disable. Default: 50"
        ),
    )
    parser.add_argument(
        "--precision-m",
        type=nonnegative_float,
        default=0.0,
        help=(
            "Snap geometry to this precision grid after each subtraction. This can "
            "remove tiny slivers and speed later iterations. Try 0.1 or 1.0. Default: 0"
        ),
    )
    parser.add_argument(
        "--candidate-chunk-size",
        type=positive_int,
        default=4096,
        help="Vectorized candidate scoring chunk size. Default: 4096",
    )
    parser.add_argument(
        "--no-vectorized",
        action="store_true",
        help="Disable Shapely 2 vectorized candidate scoring.",
    )
    parser.add_argument(
        "--progress-every-angles",
        type=int,
        default=10,
        help="During candidate search, log progress every N angles. Use 0 to disable. Default: 10",
    )
    parser.add_argument(
        "--clip-output",
        action="store_true",
        help=(
            "Post-process output strips to padded rectangular AOI coverage spans. "
            "Default outputs full fixed-length rectangles."
        ),
    )
    parser.add_argument(
        "--input-crs",
        default=None,
        help="CRS to assign if input lacks CRS metadata, for example EPSG:4326.",
    )
    parser.add_argument(
        "--work-crs",
        default=None,
        help="Projected CRS for metric calculations. Default: auto-estimated UTM.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity. Default: INFO",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Alias for DEBUG-level progress logging.",
    )

    args = parser.parse_args()
    configure_logging(args.log_level, args.verbose)
    t0 = time.monotonic()

    if args.angle_step <= 0 or args.angle_step > 180:
        raise ValueError("--angle-step must be > 0 and <= 180.")

    if args.strip_side_buffer_km * 2.0 >= args.width_km:
        raise ValueError("--strip-side-buffer-km must be less than half of --width-km.")

    LOGGER.info("starting finite strip cover")
    LOGGER.info("command-line arguments: %s", vars(args))

    input_path = Path(args.input)
    output_path = Path(args.output)
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output paths must be different.")
    remove_existing_output_dataset(output_path)

    input_gdf = read_vector_file(args.input, input_crs=args.input_crs)
    original_crs = input_gdf.crs
    original_geom = dissolve_polygonal_geometry(input_gdf)

    single_gdf = gpd.GeoDataFrame({"geometry": [original_geom]}, crs=original_crs)
    work_crs = choose_work_crs(single_gdf, work_crs=args.work_crs)
    LOGGER.info("working CRS: %s", work_crs)

    work_gdf = single_gdf.to_crs(work_crs)
    work_geom = dissolve_polygonal_geometry(work_gdf)
    work_geom = maybe_set_precision(work_geom, args.precision_m if args.precision_m > 0 else None)
    work_geom = fix_geometry(work_geom)

    strip_width_m = args.width_km * 1000.0
    strip_side_buffer_m = args.strip_side_buffer_km * 1000.0
    effective_strip_width_m = strip_width_m - 2.0 * strip_side_buffer_m
    strip_length_m = args.length_km * 1000.0
    overlap_m = args.overlap_km * 1000.0
    offset_step_m = args.offset_step_km * 1000.0
    max_along_track_gap_m = args.max_along_track_gap_km * 1000.0

    selected_rows, remaining, coverage_ratio, uncovered_area_m2, stats_rows = greedy_finite_strip_cover(
        target_geom=work_geom,
        strip_width_m=strip_width_m,
        effective_strip_width_m=effective_strip_width_m,
        strip_side_buffer_m=strip_side_buffer_m,
        strip_length_m=strip_length_m,
        overlap_m=overlap_m,
        angle_step_deg=args.angle_step,
        offset_step_m=offset_step_m,
        tolerance_area_m2=args.tolerance_area_km2 * 1_000_000.0,
        min_gain_area_m2=args.min_gain_area_km2 * 1_000_000.0,
        min_progress_area_m2=args.min_progress_area_km2 * 1_000_000.0,
        max_strips=args.max_strips,
        max_iterations=args.max_iterations,
        use_vertex_offsets=args.vertex_offsets,
        max_vertex_offsets=args.max_vertex_offsets,
        search_dedensify_m=args.search_dedensify_m,
        max_along_track_gap_m=max_along_track_gap_m,
        precision_m=args.precision_m if args.precision_m > 0 else None,
        use_vectorized=not args.no_vectorized,
        candidate_chunk_size=args.candidate_chunk_size,
        progress_every_angles=args.progress_every_angles,
    )

    result = build_output_gdf(
        selected_rows=selected_rows,
        target_geom=work_geom,
        work_crs=work_crs,
        original_crs=original_crs,
        width_km=args.width_km,
        strip_side_buffer_km=args.strip_side_buffer_km,
        overlap_km=args.overlap_km,
        clip_output=args.clip_output,
    )

    coverage_tolerance_m2 = args.tolerance_area_km2 * 1_000_000.0
    output_gap_m2 = output_gap_area_m2(
        result,
        work_geom,
        work_crs,
        strip_side_buffer_m=strip_side_buffer_m,
    )
    if uncovered_area_m2 > coverage_tolerance_m2 or output_gap_m2 > coverage_tolerance_m2:
        print(
            "ERROR: generated strips do not cover the AOI within tolerance"
            f"\n  remaining loop gap: {uncovered_area_m2 / 1_000_000.0:.9f} km2"
            f"\n  effective output coverage gap: {output_gap_m2 / 1_000_000.0:.9f} km2"
            f"\n  tolerance: {args.tolerance_area_km2:.9f} km2",
            file=sys.stderr,
        )
        raise SystemExit(2)

    write_vector_file(result, output_path)
    written_gap_m2 = written_output_gap_area_m2(
        output_path,
        work_geom,
        work_crs,
        original_crs,
        strip_side_buffer_m=strip_side_buffer_m,
    )
    if written_gap_m2 > coverage_tolerance_m2:
        try:
            remove_existing_output_dataset(output_path)
        except Exception as exc:
            LOGGER.warning("could not remove failed output dataset: %s", exc)
        print(
            "ERROR: written output does not cover the AOI within tolerance"
            f"\n  written output gap: {written_gap_m2 / 1_000_000.0:.9f} km2"
            f"\n  tolerance: {args.tolerance_area_km2:.9f} km2",
            file=sys.stderr,
        )
        raise SystemExit(2)

    total_candidates = sum(s.candidates_tested for s in stats_rows)
    total_search_time = sum(s.elapsed_s for s in stats_rows)
    elapsed_total = time.monotonic() - t0
    total_strip_km2 = float(result["strip_km2"].sum()) if "strip_km2" in result else 0.0
    total_unused_km2 = float(result["unused_km2"].sum()) if "unused_km2" in result else 0.0
    total_overlap_km2 = max(0.0, total_strip_km2 - total_unused_km2)
    total_linear_length_km = float(result["len_km"].sum()) if "len_km" in result else 0.0
    aoi_captured_km2 = max(0.0, work_geom.area - output_gap_m2) / 1_000_000.0
    aoi_capture_ratio = 0.0 if work_geom.area <= 0.0 else aoi_captured_km2 / (work_geom.area / 1_000_000.0)

    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print(f"Working CRS: {work_crs}")
    print(f"Selected strips: {len(selected_rows)}")
    print(f"Coverage ratio: {coverage_ratio:.8f}")
    print(f"Uncovered area: {uncovered_area_m2 / 1_000_000.0:.6f} km2")
    print(f"Effective output coverage gap: {output_gap_m2 / 1_000_000.0:.6f} km2")
    print(f"Written effective output coverage gap: {written_gap_m2 / 1_000_000.0:.6f} km2")
    print(f"Total linear strip length: {total_linear_length_km:.6f} km")
    print(f"Unique AOI captured by strips: {aoi_captured_km2:.6f} km2")
    print(f"Unique AOI captured ratio: {aoi_capture_ratio:.8f}")
    print(f"Total strip area: {total_strip_km2:.6f} km2")
    print(f"Total strip overlap with polygon: {total_overlap_km2:.6f} km2")
    print(f"Total unused strip area cost: {total_unused_km2:.6f} km2")
    print(f"Strip width: {args.width_km} km")
    print(f"Strip side buffer: {args.strip_side_buffer_km} km")
    print(f"Effective coverage width: {effective_strip_width_m / 1000.0} km")
    print(f"Fixed strip length: {args.length_km} km")
    if args.clip_output:
        print(f"End padding / overlap: {args.overlap_km} km")
    else:
        print(
            f"End padding / overlap: {args.overlap_km} km "
            "(only applied when --clip-output is enabled)"
        )
    print(f"Angle step: {args.angle_step} degrees")
    print(f"Offset step: {args.offset_step_km} km")
    print(f"Max along-track gap: {args.max_along_track_gap_km} km")
    print(f"Vertex offsets: {args.vertex_offsets}")
    print(f"Search de-densify tolerance: {args.search_dedensify_m} m")
    print("Selection objective: top AOI coverage with 50% waste gate")
    print(f"Vectorized scoring: {not args.no_vectorized and shapely_box is not None}")
    print(f"Candidates tested: {total_candidates}")
    print(f"Candidate search time: {total_search_time:.2f} s")
    print(f"Total runtime: {elapsed_total:.2f} s")
    print(f"Output padded to minimum AOI coverage spans: {args.clip_output}")


if __name__ == "__main__":
    main()
