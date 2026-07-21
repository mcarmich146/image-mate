#!/usr/bin/env python3
"""Smoke test for finite_variable_angle_strips2.py AOI coverage."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import uuid
from pathlib import Path

import geopandas as gpd
from shapely.affinity import rotate
from shapely.geometry import box
from shapely.ops import unary_union


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "qgis_plugin" / "scripts" / "utils" / "finite_variable_angle_strips2.py"
    input_path = repo_root / "qgis_plugin" / "scripts" / "utils" / "linear_polygon.geojson"

    spec = importlib.util.spec_from_file_location("finite_variable_angle_strips2", script)
    if spec is None or spec.loader is None:
        print("FAIL: could not import finite_variable_angle_strips2.py", file=sys.stderr)
        return 1
    finite_strips = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = finite_strips
    spec.loader.exec_module(finite_strips)

    split_fixture = unary_union(
        [
            box(0.0, 0.0, 1000.0, 1000.0),
            box(10000.0, 0.0, 11000.0, 1000.0),
        ]
    )
    if len(finite_strips.split_overlap_by_along_track_gap(split_fixture, 5000.0)) != 2:
        print("FAIL: along-track gap guard did not split distant clusters", file=sys.stderr)
        return 1
    if len(finite_strips.split_overlap_by_along_track_gap(split_fixture, 15000.0)) != 1:
        print("FAIL: along-track gap guard did not merge clusters within threshold", file=sys.stderr)
        return 1

    output_path = input_path.with_name(f"tmp_smoke_strips_{uuid.uuid4().hex}.geojson")
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--clip-output",
            "--search-dedensify-m",
            "50",
            "--strip-side-buffer-km",
            "0.25",
            "--max-along-track-gap-km",
            "5",
            "--tolerance-area-km2",
            "0.000001",
            "--log-level",
            "WARNING",
            str(input_path),
            str(output_path),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    for required_label in (
        "Total linear strip length:",
        "Unique AOI captured by strips:",
        "Unique AOI captured ratio:",
        "Max along-track gap:",
    ):
        if required_label not in proc.stdout:
            print(f"FAIL: output summary is missing '{required_label}'", file=sys.stderr)
            print(proc.stdout)
            return 1

    input_gdf = gpd.read_file(input_path)
    output_gdf = gpd.read_file(output_path)
    output_path.unlink(missing_ok=True)

    if output_gdf.empty:
        print("FAIL: output strips are empty", file=sys.stderr)
        return 1

    work_crs = input_gdf.estimate_utm_crs()
    target = unary_union(input_gdf.to_crs(work_crs).geometry)
    output_work = output_gdf.to_crs(work_crs)
    origin = target.centroid
    effective_strips = []
    for _idx, row in output_work.iterrows():
        angle_deg = float(row["ang_deg"])
        effective_offset_m = float(row["off_m"])
        effective_width_m = float(row["eff_w_km"]) * 1000.0
        rotated_geom = rotate(
            row.geometry,
            -angle_deg,
            origin=origin,
            use_radians=False,
        )
        minx, _miny, maxx, _maxy = rotated_geom.bounds
        effective_rotated = box(
            float(minx),
            effective_offset_m,
            float(maxx),
            effective_offset_m + effective_width_m,
        )
        effective_strips.append(
            rotate(effective_rotated, angle_deg, origin=origin, use_radians=False)
        )

    strips = unary_union(effective_strips)
    gap_area_m2 = target.difference(strips).area

    if gap_area_m2 > 1.0:
        print(f"FAIL: uncovered AOI gap is {gap_area_m2 / 1_000_000.0:.9f} km2")
        return 1

    if len(output_gdf) > 8:
        print(f"FAIL: expected at most 8 buffered strips for fixture, got {len(output_gdf)}")
        return 1

    bad_effective_widths = [
        float(value)
        for value in output_gdf["eff_w_km"]
        if abs(float(value) - 4.5) > 1e-6
    ]
    if bad_effective_widths:
        print(f"FAIL: expected effective width 4.5 km, got {bad_effective_widths}")
        return 1

    bad_side_buffers = [
        float(value)
        for value in output_gdf["sidebuf_km"]
        if abs(float(value) - 0.25) > 1e-6
    ]
    if bad_side_buffers:
        print(f"FAIL: expected side buffer 0.25 km, got {bad_side_buffers}")
        return 1

    if "len_km" not in output_gdf.columns:
        print("FAIL: output is missing len_km field", file=sys.stderr)
        return 1

    lengths = [float(value) for value in output_gdf["len_km"]]
    if any(value <= 0.0 for value in lengths):
        print(f"FAIL: expected positive len_km values, got {lengths}")
        return 1

    if all(abs(value - 50.0) <= 1e-6 for value in lengths):
        print("FAIL: --clip-output did not post-process fixed 50 km strip lengths")
        return 1

    rectangle_like = []
    for geom in output_work.geometry:
        rectangle_like.append(
            geom.geom_type == "Polygon"
            and len(geom.interiors) == 0
            and len(geom.exterior.coords) == 5
        )
    if not all(rectangle_like):
        print("FAIL: --clip-output should emit padded rectangles, not AOI intersections")
        return 1

    print(
        "PASS: finite_variable_angle_strips2 covers fixture AOI "
        f"with {len(output_gdf)} strips; gap={gap_area_m2:.6f} m2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
