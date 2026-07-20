#!/usr/bin/env python3
"""Smoke test for finite_variable_angle_strips_final.py."""

from __future__ import annotations

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
    script = repo_root / "qgis_plugin" / "scripts" / "utils" / "finite_variable_angle_strips_final.py"
    input_path = repo_root / "qgis_plugin" / "scripts" / "utils" / "linear_polygon.geojson"
    output_path = input_path.with_name(f"tmp_final_smoke_{uuid.uuid4().hex}.geojson")

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--clip-output",
            "--trials",
            "10",
            "--random-seed",
            "42",
            "--chord-angle-step",
            "3",
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
        "Search de-densify tolerance:",
    ):
        if required_label not in proc.stdout:
            print(f"FAIL: summary is missing '{required_label}'", file=sys.stderr)
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

    if "len_km" not in output_gdf.columns:
        print("FAIL: output is missing len_km field", file=sys.stderr)
        return 1
    if "eff_w_km" not in output_gdf.columns or "sidebuf_km" not in output_gdf.columns:
        print("FAIL: output is missing effective-width metadata", file=sys.stderr)
        return 1

    total_len_km = float(output_gdf["len_km"].astype(float).sum())
    if total_len_km <= 0:
        print("FAIL: total strip length should be positive")
        return 1

    print(
        "PASS: finite_variable_angle_strips_final covers fixture AOI "
        f"with {len(output_gdf)} strips; gap={gap_area_m2:.6f} m2; total_len={total_len_km:.3f} km"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
