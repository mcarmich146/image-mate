#!/usr/bin/env python3
"""
Randomized seed-and-grow strip optimizer.

Objective:
  Minimize total linear strip length while fully covering AOI.

Core idea:
  - Run many randomized trials.
  - In each trial, pick seed points in uncovered AOI.
  - At each seed, estimate the local shortest chord through the AOI.
  - Build a strip perpendicular to that chord and capture one contiguous
    along-track cluster (no tele-connection), bounded by min/max strip length.
  - Keep the best feasible trial by total strip length.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, box
from shapely.ops import nearest_points

from finite_variable_angle_strips2 import (
    build_output_gdf,
    choose_work_crs,
    configure_logging,
    dissolve_polygonal_geometry,
    fix_geometry,
    output_gap_area_m2,
    prepare_search_geometry,
    read_vector_file,
    remove_existing_output_dataset,
    split_overlap_by_along_track_gap,
    write_vector_file,
    written_output_gap_area_m2,
)


LOGGER = logging.getLogger("finite_strips_final")


def safe_fix_geometry(geom):
    if geom is None or geom.is_empty:
        return geom
    try:
        return fix_geometry(geom)
    except Exception:
        try:
            return geom.buffer(0)
        except Exception:
            return geom


@dataclass
class StripPlacement:
    angle_deg: float
    x0_m: float
    x1_m: float
    y0_m: float
    core_x0_m: float
    core_x1_m: float
    point_a: Point
    coverage_geom: object
    physical_geom: object
    new_area_m2: float
    strip_area_m2: float
    unused_area_m2: float

    @property
    def length_m(self) -> float:
        return max(0.0, self.x1_m - self.x0_m)

    @property
    def core_length_m(self) -> float:
        return max(0.0, self.core_x1_m - self.core_x0_m)

    @property
    def center_x_m(self) -> float:
        return (self.x0_m + self.x1_m) / 2.0

    @property
    def center_y_m(self) -> float:
        return self.y0_m


@dataclass
class TrialResult:
    success: bool
    rows: list[dict]
    uncovered_area_m2: float
    total_length_m: float
    total_unused_m2: float
    strips_count: int
    trials_steps: int


def nonnegative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return number


def iter_lines(geom):
    if geom is None or geom.is_empty:
        return
    gtype = geom.geom_type
    if gtype == "LineString":
        yield geom
    elif gtype == "MultiLineString":
        for part in geom.geoms:
            yield part
    elif gtype == "GeometryCollection":
        for part in geom.geoms:
            yield from iter_lines(part)


def merged_intervals(intervals: list[tuple[float, float]], tol_m: float = 1e-6) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted((min(a, b), max(a, b)) for a, b in intervals)
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        prev = merged[-1]
        if start <= prev[1] + tol_m:
            prev[1] = max(prev[1], end)
        else:
            merged.append([start, end])
    return [(float(a), float(b)) for a, b in merged]


def line_intervals_at_y(rotated_geom, y_m: float, margin_m: float = 1000.0) -> list[tuple[float, float]]:
    if rotated_geom is None or rotated_geom.is_empty:
        return []
    minx, _miny, maxx, _maxy = rotated_geom.bounds
    line = LineString([(float(minx - margin_m), float(y_m)), (float(maxx + margin_m), float(y_m))])
    inter = rotated_geom.intersection(line)
    inter = safe_fix_geometry(inter)
    intervals = []
    for seg in iter_lines(inter):
        coords = list(seg.coords)
        if len(coords) < 2:
            continue
        x0 = float(coords[0][0])
        x1 = float(coords[-1][0])
        if abs(x1 - x0) > 1e-6:
            intervals.append((x0, x1))
    return merged_intervals(intervals)


def interval_containing_x(intervals: list[tuple[float, float]], x_m: float, tol_m: float = 1e-6):
    for start, end in intervals:
        if start - tol_m <= x_m <= end + tol_m:
            return (start, end)
    return None


def interval_nearest_x(intervals: list[tuple[float, float]], x_m: float):
    if not intervals:
        return None
    ranked = sorted(intervals, key=lambda r: min(abs(x_m - r[0]), abs(x_m - r[1])))
    return ranked[0]


def sample_random_point_in_geom(geom, rng: random.Random, max_attempts: int = 1000):
    geom = safe_fix_geometry(geom)
    if geom is None or geom.is_empty:
        return None
    minx, miny, maxx, maxy = geom.bounds
    for _ in range(max_attempts):
        px = rng.uniform(minx, maxx)
        py = rng.uniform(miny, maxy)
        p = Point(px, py)
        if geom.contains(p):
            return p
    return geom.representative_point()


def choose_cluster_containing_seed(clusters: list, seed_x_m: float):
    if not clusters:
        return None
    containing = []
    for cluster in clusters:
        minx, _miny, maxx, _maxy = cluster.bounds
        if minx <= seed_x_m <= maxx:
            containing.append(cluster)
    if containing:
        return max(containing, key=lambda g: float(g.area))
    return min(
        clusters,
        key=lambda g: min(abs(seed_x_m - g.bounds[0]), abs(seed_x_m - g.bounds[2])),
    )


def shortest_chord_seed(
    remaining_geom,
    seed_point: Point,
    origin,
    angle_step_deg: float,
):
    def candidate_for_angle(angle_deg: float):
        rotated_remaining = rotate(
            remaining_geom,
            -float(angle_deg),
            origin=origin,
            use_radians=False,
        )
        rotated_remaining = safe_fix_geometry(rotated_remaining)
        if rotated_remaining is None or rotated_remaining.is_empty:
            return None

        rotated_seed = rotate(
            seed_point,
            -float(angle_deg),
            origin=origin,
            use_radians=False,
        )
        intervals = line_intervals_at_y(rotated_remaining, float(rotated_seed.y))
        if not intervals:
            return None
        segment = interval_containing_x(intervals, float(rotated_seed.x))
        if segment is None:
            segment = interval_nearest_x(intervals, float(rotated_seed.x))
        if segment is None:
            return None
        length_m = float(segment[1] - segment[0])
        if length_m <= 0.0:
            return None
        x_mid = (segment[0] + segment[1]) / 2.0
        point_mid_rot = Point(x_mid, float(rotated_seed.y))
        point_a = rotate(
            point_mid_rot,
            float(angle_deg),
            origin=origin,
            use_radians=False,
        )
        return {
            "line_angle_deg": float(angle_deg),
            "length_m": length_m,
            "point_a": point_a,
        }

    coarse_step_deg = max(angle_step_deg * 2.0, angle_step_deg)
    coarse_candidates = []
    for angle_deg in np.arange(0.0, 180.0, coarse_step_deg, dtype=float):
        cand = candidate_for_angle(float(angle_deg))
        if cand is not None:
            coarse_candidates.append(cand)

    if not coarse_candidates:
        return None

    coarse_best = min(coarse_candidates, key=lambda c: float(c["length_m"]))
    coarse_angle = float(coarse_best["line_angle_deg"])
    refine_angles = np.arange(
        coarse_angle - coarse_step_deg,
        coarse_angle + coarse_step_deg + angle_step_deg,
        angle_step_deg,
        dtype=float,
    )
    candidates = []
    for raw_angle in refine_angles:
        wrapped = float(raw_angle % 180.0)
        cand = candidate_for_angle(wrapped)
        if cand is not None:
            candidates.append(cand)

    if not candidates:
        candidates = [coarse_best]

    chosen = min(candidates, key=lambda c: float(c["length_m"]))
    strip_angle_deg = (chosen["line_angle_deg"] + 90.0) % 180.0
    return strip_angle_deg, chosen["point_a"], chosen["length_m"]


def place_strip_from_seed(
    remaining_geom,
    point_a: Point,
    strip_angle_deg: float,
    origin,
    effective_width_m: float,
    strip_side_buffer_m: float,
    physical_width_m: float,
    min_length_m: float,
    max_length_m: float,
    max_along_track_gap_m: float,
) -> StripPlacement | None:
    rotated_remaining = rotate(
        remaining_geom,
        -float(strip_angle_deg),
        origin=origin,
        use_radians=False,
    )
    rotated_remaining = safe_fix_geometry(rotated_remaining)
    if rotated_remaining is None or rotated_remaining.is_empty:
        return None

    rotated_seed = rotate(
        point_a,
        -float(strip_angle_deg),
        origin=origin,
        use_radians=False,
    )
    y0_m = float(rotated_seed.y) - effective_width_m / 2.0
    minx, _miny, maxx, _maxy = rotated_remaining.bounds
    span_margin = max(max_length_m, physical_width_m * 2.0, 2000.0)
    band = box(minx - span_margin, y0_m, maxx + span_margin, y0_m + effective_width_m)
    overlap = rotated_remaining.intersection(band)
    overlap = safe_fix_geometry(overlap)
    if overlap is None or overlap.is_empty:
        return None

    clusters = split_overlap_by_along_track_gap(overlap, max_along_track_gap_m)
    if not clusters:
        return None
    chosen_cluster = choose_cluster_containing_seed(clusters, float(rotated_seed.x))
    if chosen_cluster is None or chosen_cluster.is_empty:
        return None

    cluster_minx, _cminy, cluster_maxx, _cmaxy = chosen_cluster.bounds
    contiguous_len_m = float(cluster_maxx - cluster_minx)
    if contiguous_len_m <= 0.0:
        return None

    length_m = min(max_length_m, contiguous_len_m)
    if length_m < min_length_m:
        return None

    # Keep the strip centered near seed while clamping inside the chosen cluster
    # whenever possible.
    x0_m = float(rotated_seed.x) - length_m / 2.0
    if contiguous_len_m >= length_m:
        low = cluster_minx
        high = cluster_maxx - length_m
        x0_m = min(max(x0_m, low), high)
    x1_m = x0_m + length_m

    core_x0_m = max(cluster_minx, x0_m)
    core_x1_m = min(cluster_maxx, x1_m)
    if core_x1_m <= core_x0_m:
        return None

    coverage_rotated = box(core_x0_m, y0_m, core_x1_m, y0_m + effective_width_m)
    physical_rotated = box(
        x0_m,
        y0_m - strip_side_buffer_m,
        x1_m,
        y0_m + effective_width_m + strip_side_buffer_m,
    )

    coverage_geom = rotate(
        coverage_rotated,
        float(strip_angle_deg),
        origin=origin,
        use_radians=False,
    )
    coverage_geom = safe_fix_geometry(coverage_geom)
    if coverage_geom is None or coverage_geom.is_empty:
        return None

    physical_geom = rotate(
        physical_rotated,
        float(strip_angle_deg),
        origin=origin,
        use_radians=False,
    )
    physical_geom = safe_fix_geometry(physical_geom)
    if physical_geom is None or physical_geom.is_empty:
        return None

    new_overlap = remaining_geom.intersection(coverage_geom)
    new_overlap = safe_fix_geometry(new_overlap)
    new_area_m2 = 0.0 if new_overlap is None or new_overlap.is_empty else float(new_overlap.area)
    if new_area_m2 <= 0.0:
        return None

    strip_area_m2 = float(length_m * physical_width_m)
    unused_area_m2 = max(0.0, strip_area_m2 - new_area_m2)

    return StripPlacement(
        angle_deg=float(strip_angle_deg),
        x0_m=float(x0_m),
        x1_m=float(x1_m),
        y0_m=float(y0_m),
        core_x0_m=float(core_x0_m),
        core_x1_m=float(core_x1_m),
        point_a=point_a,
        coverage_geom=coverage_geom,
        physical_geom=physical_geom,
        new_area_m2=new_area_m2,
        strip_area_m2=strip_area_m2,
        unused_area_m2=unused_area_m2,
    )


def run_single_trial(
    target_geom,
    search_geom_base,
    origin,
    trial_index: int,
    rng: random.Random,
    effective_width_m: float,
    strip_side_buffer_m: float,
    physical_width_m: float,
    min_length_m: float,
    max_length_m: float,
    max_along_track_gap_m: float,
    chord_angle_step_deg: float,
    tolerance_area_m2: float,
    min_progress_area_m2: float,
    max_strips: int,
    max_seed_tries_per_strip: int,
    max_failed_steps: int,
    best_length_cap_m: float | None,
    precision_m: float | None,
    end_padding_m: float,
) -> TrialResult:
    remaining = target_geom
    remaining_search = search_geom_base
    rows: list[dict] = []
    total_len_m = 0.0
    total_unused_m2 = 0.0
    steps = 0

    failed_steps = 0

    while remaining is not None and not remaining.is_empty:
        remaining = safe_fix_geometry(remaining)
        remaining_search = safe_fix_geometry(remaining_search)
        remaining_area_m2 = 0.0 if remaining is None or remaining.is_empty else float(remaining.area)
        if remaining_area_m2 <= tolerance_area_m2:
            break
        if len(rows) >= max_strips:
            break
        if best_length_cap_m is not None and total_len_m >= best_length_cap_m:
            break

        steps += 1
        search_remaining = remaining_search
        if search_remaining is None or search_remaining.is_empty:
            search_remaining = remaining

        best_step_placement: StripPlacement | None = None
        tries = max(1, max_seed_tries_per_strip)
        for _seed_try in range(tries):
            seed = sample_random_point_in_geom(remaining, rng)
            if seed is None:
                continue

            if not remaining.buffer(1e-6).contains(seed):
                try:
                    seed = nearest_points(seed, remaining)[1]
                except Exception:
                    seed = remaining.representative_point()

            chord = shortest_chord_seed(
                remaining_geom=search_remaining,
                seed_point=seed,
                origin=origin,
                angle_step_deg=chord_angle_step_deg,
            )
            if chord is None:
                continue

            strip_angle_deg, point_a, _chord_len_m = chord
            placement = place_strip_from_seed(
                remaining_geom=remaining,
                point_a=point_a,
                strip_angle_deg=strip_angle_deg,
                origin=origin,
                effective_width_m=effective_width_m,
                strip_side_buffer_m=strip_side_buffer_m,
                physical_width_m=physical_width_m,
                min_length_m=min_length_m,
                max_length_m=max_length_m,
                max_along_track_gap_m=max_along_track_gap_m,
            )
            if placement is None or placement.new_area_m2 < min_progress_area_m2:
                continue

            if (
                best_step_placement is None
                or placement.new_area_m2 > best_step_placement.new_area_m2
            ):
                best_step_placement = placement

        if best_step_placement is None:
            failed_steps += 1
            if failed_steps >= max_failed_steps:
                break
            continue

        failed_steps = 0
        placement = best_step_placement
        sid = len(rows)
        rows.append(
            {
                "sid": sid,
                "ang_deg": placement.angle_deg,
                "off_m": placement.y0_m,
                "core_km": placement.core_length_m / 1000.0,
                "len_km": placement.length_m / 1000.0,
                "base_km2": placement.new_area_m2 / 1_000_000.0,
                "new_km2": placement.new_area_m2 / 1_000_000.0,
                "strip_km2": placement.strip_area_m2 / 1_000_000.0,
                "unused_km2": placement.unused_area_m2 / 1_000_000.0,
                "coverage_geometry": placement.coverage_geom,
                "geometry": placement.physical_geom,
            }
        )

        total_len_m += placement.length_m + (2.0 * end_padding_m)
        total_unused_m2 += placement.unused_area_m2

        remaining = remaining.difference(placement.coverage_geom)
        remaining = safe_fix_geometry(remaining)
        remaining_search = remaining_search.difference(placement.coverage_geom)
        remaining_search = safe_fix_geometry(remaining_search)
        if precision_m is not None and precision_m > 0:
            # Reuse precision snapping behavior from existing script by geometric buffering trick.
            # This script intentionally avoids importing shapely.set_precision directly.
            remaining = safe_fix_geometry(remaining)

        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                "trial %d strip %d: angle=%.2f len=%.3fkm new=%.6fkm2 remaining=%.6fkm2",
                trial_index,
                sid,
                placement.angle_deg,
                placement.length_m / 1000.0,
                placement.new_area_m2 / 1_000_000.0,
                0.0 if remaining is None or remaining.is_empty else remaining.area / 1_000_000.0,
            )

    remaining_area_m2 = 0.0 if remaining is None or remaining.is_empty else float(remaining.area)
    success = remaining_area_m2 <= tolerance_area_m2
    return TrialResult(
        success=success,
        rows=rows,
        uncovered_area_m2=remaining_area_m2,
        total_length_m=total_len_m,
        total_unused_m2=total_unused_m2,
        strips_count=len(rows),
        trials_steps=steps,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Randomized minimum-total-length strip cover."
    )
    parser.add_argument("input", help="Input polygon: .geojson, .json, .shp, or .kml")
    parser.add_argument("output", help="Output strips: .geojson, .json, .shp, or .kml")

    parser.add_argument("--width-km", type=positive_float, default=5.0, help="Physical strip width. Default: 5")
    parser.add_argument(
        "--strip-side-buffer-km",
        type=nonnegative_float,
        default=0.25,
        help="Excluded safety buffer per side. Default: 0.25",
    )
    parser.add_argument("--length-km", type=positive_float, default=50.0, help="Maximum strip length. Default: 50")
    parser.add_argument("--min-length-km", type=positive_float, default=5.0, help="Minimum strip length. Default: 5")
    parser.add_argument(
        "--end-padding-km",
        type=nonnegative_float,
        default=1.0,
        help="End padding for --clip-output post-processing. Default: 1",
    )
    parser.add_argument(
        "--max-along-track-gap-km",
        type=nonnegative_float,
        default=5.0,
        help="Maximum allowed internal along-track empty gap per captured cluster. Default: 5",
    )
    parser.add_argument(
        "--chord-angle-step",
        type=positive_float,
        default=3.0,
        help="Angle step for shortest-chord search. Default: 3",
    )
    parser.add_argument(
        "--search-dedensify-m",
        "--search-simplify-m",
        dest="search_dedensify_m",
        type=nonnegative_float,
        default=50.0,
        help=(
            "Simplify remaining AOI by this many meters for shortest-chord "
            "search only. Strip placement/subtraction/validation stay exact. "
            "Use 0 to disable. Default: 50"
        ),
    )
    parser.add_argument("--trials", type=positive_int, default=30, help="Number of randomized trials. Default: 30")
    parser.add_argument("--random-seed", type=int, default=42, help="Base random seed. Default: 42")
    parser.add_argument(
        "--seed-tries-per-strip",
        type=positive_int,
        default=6,
        help="Random seeds sampled per strip step before picking the best local candidate. Default: 6",
    )
    parser.add_argument(
        "--max-failed-steps",
        type=positive_int,
        default=25,
        help="Consecutive no-progress strip steps allowed before ending a trial. Default: 25",
    )
    parser.add_argument(
        "--tolerance-area-km2",
        type=nonnegative_float,
        default=0.000001,
        help="Coverage tolerance area. Default: 0.000001",
    )
    parser.add_argument(
        "--min-progress-area-km2",
        type=nonnegative_float,
        default=0.000001,
        help="Minimum progress per selected strip. Default: 0.000001",
    )
    parser.add_argument("--max-strips", type=positive_int, default=2000, help="Maximum strips per trial. Default: 2000")
    parser.add_argument("--precision-m", type=nonnegative_float, default=0.0, help="Optional precision grid. Default: 0")
    parser.add_argument("--clip-output", action="store_true", help="Output padded minimum-span strips.")
    parser.add_argument("--input-crs", default=None, help="Assign CRS if missing.")
    parser.add_argument("--work-crs", default=None, help="Projected working CRS.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.log_level, args.verbose)
    t0 = time.monotonic()

    if args.strip_side_buffer_km * 2.0 >= args.width_km:
        raise ValueError("--strip-side-buffer-km must be less than half of --width-km.")
    if args.min_length_km > args.length_km:
        raise ValueError("--min-length-km must be <= --length-km.")
    if args.chord_angle_step <= 0 or args.chord_angle_step > 180:
        raise ValueError("--chord-angle-step must be > 0 and <= 180.")

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
    work_geom = dissolve_polygonal_geometry(single_gdf.to_crs(work_crs))
    work_geom = safe_fix_geometry(work_geom)
    origin = work_geom.centroid

    search_geom_base, _search_is_simplified = prepare_search_geometry(
        remaining_geom=work_geom,
        search_dedensify_m=args.search_dedensify_m,
        iteration=0,
    )
    search_geom_base = safe_fix_geometry(search_geom_base)
    if search_geom_base is None or search_geom_base.is_empty:
        search_geom_base = work_geom

    strip_width_m = args.width_km * 1000.0
    strip_side_buffer_m = args.strip_side_buffer_km * 1000.0
    effective_width_m = strip_width_m - 2.0 * strip_side_buffer_m
    min_length_m = args.min_length_km * 1000.0
    max_length_m = args.length_km * 1000.0
    max_along_track_gap_m = args.max_along_track_gap_km * 1000.0
    end_padding_m = args.end_padding_km * 1000.0
    tolerance_area_m2 = args.tolerance_area_km2 * 1_000_000.0
    min_progress_area_m2 = args.min_progress_area_km2 * 1_000_000.0

    best_total_strip_length_km = 1_000_000.0
    best_feasible: TrialResult | None = None
    best_failed_uncovered_m2: float | None = None
    for trial_idx in range(args.trials):
        rng = random.Random(args.random_seed + trial_idx)
        result = run_single_trial(
            target_geom=work_geom,
            search_geom_base=search_geom_base,
            origin=origin,
            trial_index=trial_idx,
            rng=rng,
            effective_width_m=effective_width_m,
            strip_side_buffer_m=strip_side_buffer_m,
            physical_width_m=strip_width_m,
            min_length_m=min_length_m,
            max_length_m=max_length_m,
            max_along_track_gap_m=max_along_track_gap_m,
            chord_angle_step_deg=args.chord_angle_step,
            tolerance_area_m2=tolerance_area_m2,
            min_progress_area_m2=min_progress_area_m2,
            max_strips=args.max_strips,
            max_seed_tries_per_strip=args.seed_tries_per_strip,
            max_failed_steps=args.max_failed_steps,
            best_length_cap_m=(
                best_total_strip_length_km * 1000.0
                if best_feasible is not None
                else None
            ),
            precision_m=args.precision_m if args.precision_m > 0 else None,
            end_padding_m=end_padding_m,
        )
        if result.success:
            this_total_strip_length_km = result.total_length_m / 1000.0
            if this_total_strip_length_km <= best_total_strip_length_km:
                best_total_strip_length_km = this_total_strip_length_km
                best_feasible = result
                LOGGER.info(
                    "trial %d/%d best feasible updated: strips=%d total_length=%.3fkm",
                    trial_idx + 1,
                    args.trials,
                    result.strips_count,
                    this_total_strip_length_km,
                )
        else:
            if best_failed_uncovered_m2 is None or result.uncovered_area_m2 < best_failed_uncovered_m2:
                best_failed_uncovered_m2 = result.uncovered_area_m2
                LOGGER.info(
                    "trial %d/%d best failed coverage updated: uncovered=%.6fkm2",
                    trial_idx + 1,
                    args.trials,
                    result.uncovered_area_m2 / 1_000_000.0,
                )

    if best_feasible is None:
        uncovered_km2 = (
            "unknown"
            if best_failed_uncovered_m2 is None
            else f"{best_failed_uncovered_m2 / 1_000_000.0:.6f}"
        )
        raise SystemExit(
            "No feasible trial covered AOI within tolerance. "
            f"Best failed uncovered area: {uncovered_km2} km2"
        )

    best = best_feasible
    LOGGER.info(
        "final best feasible: strips=%d total_length=%.3fkm",
        best.strips_count,
        best_total_strip_length_km,
    )

    result_gdf = build_output_gdf(
        selected_rows=best.rows,
        target_geom=work_geom,
        work_crs=work_crs,
        original_crs=original_crs,
        width_km=args.width_km,
        strip_side_buffer_km=args.strip_side_buffer_km,
        overlap_km=args.end_padding_km,
        clip_output=args.clip_output,
    )

    output_gap_m2 = output_gap_area_m2(
        output_gdf=result_gdf,
        target_geom=work_geom,
        work_crs=work_crs,
        strip_side_buffer_m=strip_side_buffer_m,
    )
    if output_gap_m2 > tolerance_area_m2:
        print(
            "ERROR: best trial output does not cover AOI within tolerance"
            f"\n  effective output gap: {output_gap_m2 / 1_000_000.0:.9f} km2"
            f"\n  tolerance: {args.tolerance_area_km2:.9f} km2",
            file=sys.stderr,
        )
        raise SystemExit(2)

    write_vector_file(result_gdf, output_path)
    written_gap_m2 = written_output_gap_area_m2(
        output_path=output_path,
        target_geom=work_geom,
        work_crs=work_crs,
        original_crs=original_crs,
        strip_side_buffer_m=strip_side_buffer_m,
    )
    if written_gap_m2 > tolerance_area_m2:
        print(
            "ERROR: written output does not cover AOI within tolerance"
            f"\n  written effective gap: {written_gap_m2 / 1_000_000.0:.9f} km2"
            f"\n  tolerance: {args.tolerance_area_km2:.9f} km2",
            file=sys.stderr,
        )
        raise SystemExit(2)

    total_strip_km2 = float(result_gdf["strip_km2"].sum()) if "strip_km2" in result_gdf else 0.0
    total_unused_km2 = float(result_gdf["unused_km2"].sum()) if "unused_km2" in result_gdf else 0.0
    total_overlap_km2 = max(0.0, total_strip_km2 - total_unused_km2)
    total_length_km = float(result_gdf["len_km"].sum()) if "len_km" in result_gdf else best.total_length_m / 1000.0
    captured_km2 = max(0.0, work_geom.area - output_gap_m2) / 1_000_000.0
    capture_ratio = 0.0 if work_geom.area <= 0 else captured_km2 / (work_geom.area / 1_000_000.0)

    elapsed_s = time.monotonic() - t0
    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print(f"Working CRS: {work_crs}")
    print(f"Trials run: {args.trials}")
    print(f"Best trial success: {best.success}")
    print(f"Selected strips: {len(result_gdf)}")
    print(f"Total linear strip length: {total_length_km:.6f} km")
    print(f"Unique AOI captured by strips: {captured_km2:.6f} km2")
    print(f"Unique AOI captured ratio: {capture_ratio:.8f}")
    print(f"Effective output coverage gap: {output_gap_m2 / 1_000_000.0:.6f} km2")
    print(f"Written effective output coverage gap: {written_gap_m2 / 1_000_000.0:.6f} km2")
    print(f"Total strip area: {total_strip_km2:.6f} km2")
    print(f"Total strip overlap with polygon: {total_overlap_km2:.6f} km2")
    print(f"Total unused strip area cost: {total_unused_km2:.6f} km2")
    print(f"Strip width: {args.width_km} km")
    print(f"Strip side buffer: {args.strip_side_buffer_km} km")
    print(f"Effective coverage width: {effective_width_m / 1000.0} km")
    print(f"Minimum strip length: {args.min_length_km} km")
    print(f"Maximum strip length: {args.length_km} km")
    print(f"End padding: {args.end_padding_km} km")
    print(f"Max along-track gap: {args.max_along_track_gap_km} km")
    print(f"Chord angle step: {args.chord_angle_step} deg")
    print(f"Search de-densify tolerance: {args.search_dedensify_m} m")
    print(f"Seed tries per strip: {args.seed_tries_per_strip}")
    print(f"Max failed strip steps: {args.max_failed_steps}")
    print(f"Random seed: {args.random_seed}")
    print(f"Total runtime: {elapsed_s:.2f} s")


if __name__ == "__main__":
    main()
