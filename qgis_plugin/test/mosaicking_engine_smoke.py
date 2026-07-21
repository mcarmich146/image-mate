#!/usr/bin/env python3
"""End-to-end synthetic checks for the vendored Mosaicker_v2 engine."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


def assert_bounds_filter(script: Path) -> None:
    sys.path.insert(0, str(script.parent))
    from seamless_mosaic import intersecting_bounds_indices  # noqa: PLC0415

    source_bounds = [
        (0.0, 0.0, 10.0, 10.0),
        (20.0, 20.0, 30.0, 30.0),
        (8.0, -5.0, 12.0, 2.0),
    ]
    actual = intersecting_bounds_indices(source_bounds, (5.0, 1.0, 9.0, 6.0))
    if actual != [0, 2]:
        raise AssertionError(f"unexpected bounds-filter candidates: {actual}")


def write_raster(path: Path, data: np.ndarray, left: float, *, nodata: float | None = None) -> None:
    count, height, width = data.shape
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": count,
        "dtype": data.dtype.name,
        "crs": "EPSG:3857",
        "transform": from_origin(left, float(height), 1.0, 1.0),
        "tiled": True,
        "blockxsize": 32,
        "blockysize": 32,
        "compress": "deflate",
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "Command failed\n"
            + " ".join(command)
            + f"\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def build_balancing_case(root: Path) -> tuple[Path, np.ndarray, tuple[slice, slice]]:
    height, width = 96, 240
    yy, xx = np.mgrid[0:height, 0:width]
    texture = 8.0 * np.sin(xx / 7.0) + 5.0 * np.cos(yy / 9.0)
    base = np.stack(
        [
            35.0 + 0.42 * xx + 0.10 * yy + texture,
            48.0 + 0.30 * xx + 0.18 * yy + 0.7 * texture,
            62.0 + 0.22 * xx + 0.12 * yy + 0.5 * texture,
        ],
        axis=0,
    )
    base = np.clip(np.rint(base), 1, 190).astype(np.uint8)

    source_a = base[:, :, :160].copy()
    source_b = np.clip(
        np.rint(base[:, :, 80:].astype(np.float32) * 1.20 + 15.0),
        0,
        255,
    ).astype(np.uint8)

    cloud_rows = slice(28, 68)
    cloud_global_cols = slice(108, 142)
    cloud_local_cols = slice(cloud_global_cols.start, cloud_global_cols.stop)
    source_a[:, cloud_rows, cloud_local_cols] = 245
    cloud_mask = np.zeros((1, height, 160), dtype=np.uint8)
    cloud_mask[:, cloud_rows, cloud_local_cols] = 1

    write_raster(root / "a.tif", source_a, 0.0)
    write_raster(root / "b.tif", source_b, 80.0)
    write_raster(root / "a_cloud.tif", cloud_mask, 0.0)

    manifest = {
        "inputs": [
            {
                "path": "a.tif",
                "cloud_mask": "a_cloud.tif",
                "cloud_mask_mode": "nonzero",
            },
            {"path": "b.tif"},
        ]
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path, base, (cloud_rows, cloud_global_cols)


def assert_balancing_and_cloud_replacement(script: Path, root: Path) -> None:
    manifest, base, cloud_area = build_balancing_case(root)
    output = root / "mosaic.tif"
    command = [
        sys.executable,
        str(script),
        "--manifest",
        str(manifest),
        "--output",
        str(output),
        "--no-auto-cloud",
        "--feather",
        "10",
        "--cloud-dilate",
        "2",
        "--tile-size",
        "64",
        "--tile-max-memory-mb",
        "32",
        "--block-size",
        "64",
        "--max-open-sources",
        "1",
        "--no-overviews",
        "--progress-interval",
        "0",
    ]
    run_command(command, root)

    report = json.loads((root / "mosaic.tif.analysis.json").read_text(encoding="utf-8"))
    gains = np.asarray(report["radiometry"]["gains"], dtype=np.float64)
    offsets = np.asarray(report["radiometry"]["offsets"], dtype=np.float64)
    if not np.allclose(gains[1], 1.0 / 1.20, atol=0.08):
        raise AssertionError(f"Unexpected recovered gains: {gains[1].tolist()}")
    if not np.allclose(offsets[1], -15.0 / 1.20, atol=7.0):
        raise AssertionError(f"Unexpected recovered offsets: {offsets[1].tolist()}")

    with rasterio.open(output) as dst:
        mosaic = dst.read()
        validity = dst.dataset_mask() > 0
        if (dst.width, dst.height, dst.count) != (240, 96, 3):
            raise AssertionError("Unexpected mosaic dimensions")
        if not dst.is_tiled:
            raise AssertionError("Output is not tiled")
        if not validity.all():
            raise AssertionError("Fully covered synthetic case contains invalid output pixels")

    rows, cols = cloud_area
    cloud_mae = float(
        np.mean(
            np.abs(
                mosaic[:, rows, cols].astype(np.float32)
                - base[:, rows, cols].astype(np.float32)
            )
        )
    )
    if cloud_mae > 9.0:
        raise AssertionError(f"Cloud replacement MAE is too high: {cloud_mae:.3f}")

    overall_mae = float(
        np.mean(np.abs(mosaic.astype(np.float32) - base.astype(np.float32)))
    )
    if overall_mae > 10.0:
        raise AssertionError(f"Overall mosaic MAE is too high: {overall_mae:.3f}")


def assert_gap_remains_invalid(script: Path, root: Path) -> None:
    gap_root = root / "gap_case"
    gap_root.mkdir()
    left = np.full((1, 24, 20), 25, dtype=np.uint8)
    right = np.full((1, 24, 20), 80, dtype=np.uint8)
    write_raster(gap_root / "left.tif", left, 0.0)
    write_raster(gap_root / "right.tif", right, 40.0)
    output = gap_root / "gap.tif"
    command = [
        sys.executable,
        str(script),
        str(gap_root / "left.tif"),
        str(gap_root / "right.tif"),
        "--output",
        str(output),
        "--no-auto-cloud",
        "--balance",
        "none",
        "--seam-method",
        "voronoi",
        "--feather",
        "4",
        "--tile-size",
        "32",
        "--block-size",
        "64",
        "--no-overviews",
    ]
    run_command(command, gap_root)
    with rasterio.open(output) as dst:
        mask = dst.dataset_mask() > 0
        if (dst.width, dst.height) != (60, 24):
            raise AssertionError("Unexpected dimensions in separated-source case")
        if mask[:, :20].mean() != 1.0 or mask[:, 40:].mean() != 1.0:
            raise AssertionError("Covered separated-source pixels are invalid")
        if mask[:, 20:40].any():
            raise AssertionError("Uncovered gap was incorrectly marked valid")


def assert_dry_run_sizes_and_reduces_tile(script: Path, root: Path) -> None:
    output = root / "dry_run.tif"
    command = [
        sys.executable,
        str(script),
        str(root / "a.tif"),
        str(root / "b.tif"),
        "--output",
        str(output),
        "--dry-run",
        "--tile-size",
        "4096",
        "--tile-max-memory-mb",
        "1",
        "--feather",
        "8",
        "--cloud-dilate",
        "2",
    ]
    completed = run_command(command, root)
    summary = json.loads(completed.stdout)
    if summary["width"] != 240 or summary["height"] != 96:
        raise AssertionError("Dry-run output sizing is incorrect")
    if summary["effective_tile_size"] >= 4096:
        raise AssertionError("Tile memory cap did not reduce the processing tile")
    if output.exists():
        raise AssertionError("Dry run unexpectedly created an output raster")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keep",
        type=Path,
        help="Keep generated test data in this directory instead of a temporary directory",
    )
    args = parser.parse_args()
    script = (
        Path(__file__).resolve().parents[1]
        / "image_mate_qgis_plugin"
        / "vendor"
        / "mosaicker"
        / "seamless_mosaic.py"
    )
    assert_bounds_filter(script)

    if args.keep:
        root = args.keep.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        assert_balancing_and_cloud_replacement(script, root)
        assert_gap_remains_invalid(script, root)
        assert_dry_run_sizes_and_reduces_tile(script, root)
        print(f"All smoke tests passed. Artifacts: {root}")
        return 0

    with tempfile.TemporaryDirectory(prefix="seamless_mosaic_test_") as tmp:
        root = Path(tmp)
        assert_balancing_and_cloud_replacement(script, root)
        assert_gap_remains_invalid(script, root)
        assert_dry_run_sizes_and_reduces_tile(script, root)
    print("All smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
