#!/usr/bin/env python3
"""Seamless, radiometrically balanced GeoTIFF mosaicking.

The program performs three passes:

1. Inspect all inputs and pre-compute the target grid and a conservative
   output-size estimate.
2. Build a bounded-resolution planning mosaic, estimate one global affine
   radiometric transform per source/band, detect clouds, and compute graph-cut
   seam ownership.
3. Stream full-resolution windows through WarpedVRT objects, feather across
   the planned seams, and write a tiled BigTIFF-compatible GeoTIFF.

Cloud masks supplied by the user are strongly preferred.  The automatic cloud
score is intentionally sensor-agnostic and therefore heuristic; it cannot
reliably distinguish clouds from snow, salt, bright roofs, or haze for every
sensor.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import sys
import tempfile
import time
from collections import OrderedDict
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2 as cv
import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS
from rasterio.enums import ColorInterp, Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform, transform_bounds
from rasterio.windows import Window, bounds as window_bounds
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import lsqr
from shapely.geometry import box
from shapely.strtree import STRtree

LOGGER = logging.getLogger("seamless_mosaic")
PROGRAM_VERSION = "1.0.0"
GIB = 1024**3


@dataclass(slots=True)
class InputSpec:
    path: str
    cloud_mask: str | None = None
    cloud_mask_mode: str = "nonzero"
    cloud_mask_threshold: float = 0.5
    priority: float = 0.0
    name: str | None = None


@dataclass(slots=True)
class SourceInfo:
    index: int
    spec: InputSpec
    crs: str
    source_bounds: tuple[float, float, float, float]
    target_bounds: tuple[float, float, float, float]
    source_width: int
    source_height: int
    source_count: int
    source_dtypes: list[str]
    source_nodatavals: list[float | None]
    full_window: tuple[int, int, int, int]
    plan_window: tuple[int, int, int, int] | None = None
    percentiles_low: list[float] = field(default_factory=list)
    percentiles_high: list[float] = field(default_factory=list)
    gains: list[float] = field(default_factory=list)
    offsets: list[float] = field(default_factory=list)
    auto_cloud_threshold: float | None = None


@dataclass(slots=True)
class GridSpec:
    crs: CRS
    transform: Affine
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    resolution: tuple[float, float]


@dataclass(slots=True)
class OutputPlan:
    grid: GridSpec
    plan_grid: GridSpec
    plan_scale: int
    selected_bands: list[int]
    rgb_positions: tuple[int, int, int]
    nir_position: int | None
    output_dtype: str
    working_dtype: str
    output_nodata: float | int | None
    uncompressed_bytes: int
    mask_bytes: int
    overview_bytes_estimate: int
    conservative_bytes: int
    bigtiff: str
    source_infos: list[SourceInfo]
    first_colorinterp: list[str]
    first_descriptions: list[str | None]


@dataclass(slots=True)
class PlanSource:
    info: SourceInfo
    window: Window
    data: np.ndarray  # B,H,W float32 in selected-band order
    valid: np.ndarray  # H,W bool
    clear: np.ndarray  # H,W bool
    cloud_probability: np.ndarray  # H,W float32


@dataclass(slots=True)
class OverlapEdge:
    source_i: int
    source_j: int
    overlap_pixels: int
    med_i: list[float | None]
    med_j: list[float | None]
    scale_i: list[float | None]
    scale_j: list[float | None]
    counts: list[int]
    weights: list[float]


@dataclass(slots=True)
class RuntimeSource:
    info: SourceInfo
    dataset: rasterio.io.DatasetReader
    vrt: WarpedVRT
    alpha_band: int
    cloud_dataset: rasterio.io.DatasetReader | None
    cloud_vrt: WarpedVRT | None

    def close(self) -> None:
        if self.cloud_vrt is not None:
            self.cloud_vrt.close()
        if self.cloud_dataset is not None:
            self.cloud_dataset.close()
        self.vrt.close()
        self.dataset.close()


class RuntimeSourceCache:
    """Small LRU cache so mosaics with many inputs do not exhaust file handles."""

    def __init__(self, plan: OutputPlan, args: argparse.Namespace) -> None:
        self.plan = plan
        self.args = args
        self.max_open = max(1, int(args.max_open_sources))
        self._items: OrderedDict[int, RuntimeSource] = OrderedDict()

    def get(self, source_index: int) -> RuntimeSource:
        runtime = self._items.pop(source_index, None)
        if runtime is not None:
            self._items[source_index] = runtime
            return runtime
        while len(self._items) >= self.max_open:
            _, old = self._items.popitem(last=False)
            old.close()
        runtime = open_runtime_source(
            self.plan.source_infos[source_index], self.plan, self.args
        )
        self._items[source_index] = runtime
        return runtime

    def close(self) -> None:
        while self._items:
            _, runtime = self._items.popitem(last=False)
            runtime.close()

    def __enter__(self) -> "RuntimeSourceCache":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


class MosaicError(RuntimeError):
    """A user-facing mosaicking error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, CRS):
        return value.to_string()
    if isinstance(value, Affine):
        return tuple(value)[:6]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Not JSON serializable: {type(value)!r}")


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=False, default=_json_default)
        f.write("\n")
    os.replace(tmp, path)


def parse_csv_ints(text: str) -> list[int]:
    try:
        values = [int(v.strip()) for v in text.split(",") if v.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected comma-separated integers: {text!r}") from exc
    if not values or any(v < 1 for v in values):
        raise argparse.ArgumentTypeError("Band numbers are 1-based positive integers")
    return values


def parse_overviews(text: str) -> list[int]:
    values = parse_csv_ints(text)
    values = sorted(set(v for v in values if v > 1))
    if not values:
        raise argparse.ArgumentTypeError("At least one overview factor greater than 1 is required")
    return values


def parse_nodata(text: str | None) -> float | int | None:
    if text is None:
        return None
    lowered = text.strip().lower()
    if lowered in {"none", "null"}:
        return None
    if lowered == "nan":
        return float("nan")
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid nodata value: {text!r}") from exc
    if value.is_integer():
        return int(value)
    return value


def parse_cloud_mapping(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise argparse.ArgumentTypeError("Cloud-mask mappings must be INPUT=MASK")
    source, mask = text.split("=", 1)
    source = source.strip()
    mask = mask.strip()
    if not source or not mask:
        raise argparse.ArgumentTypeError("Cloud-mask mappings must be INPUT=MASK")
    return source, mask


def is_remote_path(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith(("/vsi", "http://", "https://", "s3://", "gs://", "az://"))


def ensure_artifact_path_is_safe(
    path: Path,
    input_local_paths: set[str],
    label: str,
    other_artifacts: Sequence[Path] = (),
) -> None:
    resolved = str(path.expanduser().resolve())
    if resolved in input_local_paths:
        raise MosaicError(f"{label} must not overwrite an input image or cloud mask: {path}")
    for other in other_artifacts:
        if resolved == str(other.expanduser().resolve()):
            raise MosaicError(f"{label} conflicts with another output artifact: {path}")


def normalize_local_path(path: str, base_dir: Path | None = None) -> str:
    if is_remote_path(path):
        return path
    p = Path(path).expanduser()
    if base_dir is not None and not p.is_absolute():
        p = base_dir / p
    return str(p.resolve())


def load_input_specs(args: argparse.Namespace) -> list[InputSpec]:
    specs: list[InputSpec] = []
    if args.manifest:
        manifest_path = Path(args.manifest).expanduser().resolve()
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MosaicError(f"Cannot read manifest {manifest_path}: {exc}") from exc
        entries = raw.get("inputs") if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            raise MosaicError("Manifest must be a JSON list or an object with an 'inputs' list")
        for n, entry in enumerate(entries):
            if isinstance(entry, str):
                entry = {"path": entry}
            if not isinstance(entry, dict) or not entry.get("path"):
                raise MosaicError(f"Manifest input {n} must contain a path")
            mode = str(entry.get("cloud_mask_mode", "nonzero")).lower()
            if mode not in {"nonzero", "zero", "probability"}:
                raise MosaicError(
                    f"Manifest input {n}: cloud_mask_mode must be nonzero, zero, or probability"
                )
            try:
                cloud_mask_threshold = float(entry.get("cloud_mask_threshold", 0.5))
                priority = float(entry.get("priority", 0.0))
            except (TypeError, ValueError) as exc:
                raise MosaicError(
                    f"Manifest input {n}: priority and cloud_mask_threshold must be numeric"
                ) from exc
            specs.append(
                InputSpec(
                    path=normalize_local_path(str(entry["path"]), manifest_path.parent),
                    cloud_mask=(
                        normalize_local_path(str(entry["cloud_mask"]), manifest_path.parent)
                        if entry.get("cloud_mask")
                        else None
                    ),
                    cloud_mask_mode=mode,
                    cloud_mask_threshold=cloud_mask_threshold,
                    priority=priority,
                    name=str(entry.get("name")) if entry.get("name") is not None else None,
                )
            )

    for path in args.inputs:
        specs.append(InputSpec(path=normalize_local_path(path)))

    if not specs:
        raise MosaicError("Provide at least one input GeoTIFF, directly or through --manifest")

    cloud_map: dict[str, str] = {}
    basename_map: dict[str, str] = {}
    for source, mask in args.cloud_mask:
        source_normalized = normalize_local_path(source)
        mask_normalized = normalize_local_path(mask)
        cloud_map[source_normalized] = mask_normalized
        basename_map[Path(source).name] = mask_normalized

    for spec in specs:
        if spec.path in cloud_map:
            spec.cloud_mask = cloud_map[spec.path]
        elif Path(spec.path).name in basename_map:
            spec.cloud_mask = basename_map[Path(spec.path).name]

    seen: set[str] = set()
    unique: list[InputSpec] = []
    for spec in specs:
        key = spec.path
        if key in seen:
            LOGGER.warning("Ignoring duplicate input %s", spec.path)
            continue
        seen.add(key)
        if not is_remote_path(spec.path) and not Path(spec.path).is_file():
            raise MosaicError(f"Input does not exist: {spec.path}")
        if spec.cloud_mask and not is_remote_path(spec.cloud_mask) and not Path(spec.cloud_mask).is_file():
            raise MosaicError(f"Cloud mask does not exist: {spec.cloud_mask}")
        unique.append(spec)
    return unique


def validate_block_size(value: int) -> None:
    if value < 64 or value > 4096 or value % 16 != 0 or (value & (value - 1)) != 0:
        raise MosaicError("--block-size must be a power of two, divisible by 16, from 64 to 4096")


def resampling_from_name(name: str) -> Resampling:
    try:
        return getattr(Resampling, name)
    except AttributeError as exc:
        valid = [n for n in ("nearest", "bilinear", "cubic", "lanczos", "average")]
        raise MosaicError(f"Unknown resampling {name!r}; choose one of {', '.join(valid)}") from exc


def pixel_window_for_bounds(
    bounds: tuple[float, float, float, float], grid: GridSpec
) -> tuple[int, int, int, int]:
    left, bottom, right, top = bounds
    grid_left, grid_bottom, grid_right, grid_top = grid.bounds
    res_x, res_y = grid.resolution
    col0 = max(0, int(math.floor((left - grid_left) / res_x)))
    col1 = min(grid.width, int(math.ceil((right - grid_left) / res_x)))
    row0 = max(0, int(math.floor((grid_top - top) / res_y)))
    row1 = min(grid.height, int(math.ceil((grid_top - bottom) / res_y)))
    return col0, row0, max(0, col1 - col0), max(0, row1 - row0)


def tuple_to_window(values: tuple[int, int, int, int]) -> Window:
    col, row, width, height = values
    return Window(col, row, width, height)


def choose_resolution(
    datasets: Sequence[rasterio.io.DatasetReader],
    target_crs: CRS,
    explicit: Sequence[float] | None,
    policy: str,
) -> tuple[float, float]:
    if explicit:
        if len(explicit) == 1:
            x = y = abs(float(explicit[0]))
        elif len(explicit) == 2:
            x, y = abs(float(explicit[0])), abs(float(explicit[1]))
        else:
            raise MosaicError("--resolution accepts one value or two values (X Y)")
        if x <= 0 or y <= 0:
            raise MosaicError("Output resolution must be positive")
        return x, y

    resolutions: list[tuple[float, float]] = []
    for src in datasets:
        if src.crs == target_crs and abs(src.transform.b) < 1e-12 and abs(src.transform.d) < 1e-12:
            resolutions.append((abs(src.transform.a), abs(src.transform.e)))
        else:
            transform, _, _ = calculate_default_transform(
                src.crs, target_crs, src.width, src.height, *src.bounds
            )
            resolutions.append((abs(transform.a), abs(transform.e)))

    if policy == "first":
        return resolutions[0]
    if policy == "finest":
        return min(r[0] for r in resolutions), min(r[1] for r in resolutions)
    if policy == "coarsest":
        return max(r[0] for r in resolutions), max(r[1] for r in resolutions)
    raise MosaicError(f"Unknown resolution policy: {policy}")


def choose_output_dtype(
    datasets: Sequence[rasterio.io.DatasetReader], selected_bands: Sequence[int], requested: str
) -> str:
    if requested != "auto":
        try:
            return np.dtype(requested).name
        except TypeError as exc:
            raise MosaicError(f"Unsupported output dtype: {requested}") from exc

    dtypes = [np.dtype(src.dtypes[b - 1]) for src in datasets for b in selected_bands]
    if all(dt == dtypes[0] for dt in dtypes):
        return dtypes[0].name
    result = np.result_type(*dtypes)
    if result.kind == "c":
        raise MosaicError("Complex-valued rasters are not supported")
    return result.name


def choose_working_dtype(
    datasets: Sequence[rasterio.io.DatasetReader],
    selected_bands: Sequence[int],
    requested: str,
    output_dtype: str,
) -> str:
    if requested in {"float32", "float64"}:
        chosen = requested
    elif requested == "auto":
        selected_dtypes = [
            np.dtype(src.dtypes[band - 1])
            for src in datasets
            for band in selected_bands
        ]
        needs_float64 = np.dtype(output_dtype).itemsize > 4 or any(
            (dt.kind == "f" and dt.itemsize > 4)
            or (dt.kind in "iu" and dt.itemsize > 2)
            for dt in selected_dtypes
        )
        chosen = "float64" if needs_float64 else "float32"
    else:
        raise MosaicError(f"Unknown working dtype: {requested}")

    if chosen == "float32":
        high_precision = [
            src.dtypes[band - 1]
            for src in datasets
            for band in selected_bands
            if (
                (np.dtype(src.dtypes[band - 1]).kind == "f" and np.dtype(src.dtypes[band - 1]).itemsize > 4)
                or (
                    np.dtype(src.dtypes[band - 1]).kind in "iu"
                    and np.dtype(src.dtypes[band - 1]).itemsize > 2
                )
            )
        ]
        if high_precision:
            LOGGER.warning(
                "float32 working precision was selected for high-precision source data (%s); "
                "use --working-dtype float64 to avoid precision loss",
                ", ".join(sorted(set(high_precision))),
            )
    return chosen


def validate_nodata_for_dtype(value: float | int | None, dtype: str) -> None:
    if value is None:
        return
    dt = np.dtype(dtype)
    if isinstance(value, float) and math.isnan(value):
        if dt.kind != "f":
            raise MosaicError("NaN nodata requires a floating-point output dtype")
        return
    if dt.kind in "iu":
        limits = np.iinfo(dt)
        if float(value) < limits.min or float(value) > limits.max:
            raise MosaicError(f"Nodata {value} is outside the range of {dtype}")


def inspect_and_plan(specs: list[InputSpec], args: argparse.Namespace) -> OutputPlan:
    with ExitStack() as stack:
        datasets = []
        for spec in specs:
            try:
                src = stack.enter_context(rasterio.open(spec.path))
            except Exception as exc:  # Rasterio raises several backend-specific errors.
                raise MosaicError(f"Cannot open {spec.path}: {exc}") from exc
            if src.crs is None:
                raise MosaicError(f"Input has no CRS: {spec.path}")
            if src.width <= 0 or src.height <= 0 or src.count <= 0:
                raise MosaicError(f"Input has invalid dimensions: {spec.path}")
            datasets.append(src)

        if args.bands:
            selected_bands = args.bands[:]
        else:
            selected_bands = [
                band
                for band, interpretation in enumerate(datasets[0].colorinterp, start=1)
                if interpretation != ColorInterp.alpha
            ]
            if not selected_bands:
                selected_bands = list(range(1, datasets[0].count + 1))
        if len(set(selected_bands)) != len(selected_bands):
            raise MosaicError("--bands must not contain duplicates")
        for src, spec in zip(datasets, specs, strict=True):
            if max(selected_bands) > src.count:
                raise MosaicError(
                    f"{spec.path} has {src.count} bands but --bands requests band {max(selected_bands)}"
                )
            if any(np.dtype(src.dtypes[b - 1]).kind == "c" for b in selected_bands):
                raise MosaicError(f"Complex-valued bands are not supported: {spec.path}")

        target_crs = CRS.from_user_input(args.crs) if args.crs else datasets[0].crs
        res_x, res_y = choose_resolution(datasets, target_crs, args.resolution, args.resolution_policy)

        transformed_bounds: list[tuple[float, float, float, float]] = []
        for src in datasets:
            b = transform_bounds(src.crs, target_crs, *src.bounds, densify_pts=21)
            if not all(math.isfinite(v) for v in b):
                raise MosaicError(f"Non-finite transformed bounds for {src.name}")
            transformed_bounds.append(tuple(float(v) for v in b))

        min_left = min(b[0] for b in transformed_bounds)
        min_bottom = min(b[1] for b in transformed_bounds)
        max_right = max(b[2] for b in transformed_bounds)
        max_top = max(b[3] for b in transformed_bounds)

        left = math.floor(min_left / res_x) * res_x
        right = math.ceil(max_right / res_x) * res_x
        bottom = math.floor(min_bottom / res_y) * res_y
        top = math.ceil(max_top / res_y) * res_y
        width = int(math.ceil((right - left) / res_x))
        height = int(math.ceil((top - bottom) / res_y))
        if width <= 0 or height <= 0:
            raise MosaicError("Computed output grid is empty")
        if width > 2_147_483_647 or height > 2_147_483_647:
            raise MosaicError(
                "A single raster dimension exceeds the practical GDAL limit; split the requested area"
            )
        right = left + width * res_x
        bottom = top - height * res_y
        transform = from_origin(left, top, res_x, res_y)
        grid = GridSpec(
            crs=target_crs,
            transform=transform,
            width=width,
            height=height,
            bounds=(left, bottom, right, top),
            resolution=(res_x, res_y),
        )

        output_dtype = choose_output_dtype(datasets, selected_bands, args.dtype)
        working_dtype = choose_working_dtype(
            datasets,
            selected_bands,
            args.working_dtype,
            output_dtype,
        )
        source_nodata_candidates: list[float | None] = []
        for src in datasets:
            source_nodata_candidates.extend(src.nodatavals[b - 1] for b in selected_bands)
        if args.nodata_was_set:
            output_nodata = args.nodata
        else:
            non_none = [v for v in source_nodata_candidates if v is not None]
            all_same = False
            if non_none and len(non_none) == len(source_nodata_candidates):
                first_nodata = non_none[0]
                all_same = all(
                    (
                        isinstance(first_nodata, float)
                        and isinstance(v, float)
                        and math.isnan(first_nodata)
                        and math.isnan(v)
                    )
                    or v == first_nodata
                    for v in non_none
                )
            output_nodata = non_none[0] if all_same else None
        validate_nodata_for_dtype(output_nodata, output_dtype)

        full_windows = [pixel_window_for_bounds(b, grid) for b in transformed_bounds]
        total_source_pixels = sum(w[2] * w[3] for w in full_windows)
        output_pixels = width * height
        # Data, corrected RGB, masks, cloud probabilities, distance transforms,
        # OpenCV workspaces, and global label/cost arrays coexist during planning.
        # Because both source-local and output-grid arrays shrink by scale^2, a
        # single scale factor can enforce an approximate working-set budget.
        estimated_plan_bytes_per_source_pixel = (
            np.dtype(working_dtype).itemsize * len(selected_bands) + 96
        )
        estimated_plan_bytes_per_output_pixel = 40
        raw_planning_bytes = (
            total_source_pixels * estimated_plan_bytes_per_source_pixel
            + output_pixels * estimated_plan_bytes_per_output_pixel
        )
        planning_budget_bytes = args.plan_max_memory_mb * 1024 * 1024
        scale_output = math.sqrt(output_pixels / max(1, args.plan_max_output_pixels))
        scale_sources = math.sqrt(
            total_source_pixels / max(1, args.plan_max_source_pixels)
        )
        scale_memory = math.sqrt(raw_planning_bytes / max(1, planning_budget_bytes))
        plan_scale = max(
            1,
            int(math.ceil(max(scale_output, scale_sources, scale_memory))),
        )
        plan_width = int(math.ceil(width / plan_scale))
        plan_height = int(math.ceil(height / plan_scale))
        plan_res_x = res_x * plan_scale
        plan_res_y = res_y * plan_scale
        plan_transform = from_origin(left, top, plan_res_x, plan_res_y)
        plan_right = left + plan_width * plan_res_x
        plan_bottom = top - plan_height * plan_res_y
        plan_grid = GridSpec(
            crs=target_crs,
            transform=plan_transform,
            width=plan_width,
            height=plan_height,
            bounds=(left, plan_bottom, plan_right, top),
            resolution=(plan_res_x, plan_res_y),
        )

        source_infos: list[SourceInfo] = []
        for idx, (spec, src, target_b, full_window) in enumerate(
            zip(specs, datasets, transformed_bounds, full_windows, strict=True)
        ):
            plan_window = pixel_window_for_bounds(target_b, plan_grid)
            source_infos.append(
                SourceInfo(
                    index=idx,
                    spec=spec,
                    crs=src.crs.to_string(),
                    source_bounds=tuple(float(v) for v in src.bounds),
                    target_bounds=target_b,
                    source_width=src.width,
                    source_height=src.height,
                    source_count=src.count,
                    source_dtypes=list(src.dtypes),
                    source_nodatavals=[
                        None if v is None else float(v) for v in src.nodatavals
                    ],
                    full_window=full_window,
                    plan_window=plan_window,
                    gains=[1.0] * len(selected_bands),
                    offsets=[0.0] * len(selected_bands),
                )
            )

        if args.rgb_bands:
            rgb_bands = args.rgb_bands
            if len(rgb_bands) != 3:
                raise MosaicError("--rgb-bands must contain exactly three source band numbers")
            missing = [b for b in rgb_bands if b not in selected_bands]
            if missing:
                raise MosaicError(
                    f"RGB bands {missing} are not in --bands; include them in the output band selection"
                )
            rgb_positions = tuple(selected_bands.index(b) for b in rgb_bands)
        elif len(selected_bands) >= 3:
            rgb_positions = (0, 1, 2)
        elif len(selected_bands) == 2:
            rgb_positions = (0, 1, 1)
        else:
            rgb_positions = (0, 0, 0)

        nir_position = None
        if args.nir_band is not None:
            if args.nir_band not in selected_bands:
                raise MosaicError("--nir-band must also be included in --bands")
            nir_position = selected_bands.index(args.nir_band)

        dtype_bytes = np.dtype(output_dtype).itemsize
        uncompressed_bytes = width * height * len(selected_bands) * dtype_bytes
        mask_bytes = width * height
        # A complete 2x pyramid contributes at most 1/3 of the base level.
        overview_bytes = int((uncompressed_bytes + mask_bytes) / 3) if args.overviews else 0
        conservative = uncompressed_bytes + mask_bytes + overview_bytes
        bigtiff = "YES" if conservative >= int(3.5 * GIB) else "IF_SAFER"

        first_colorinterp = []
        first_descriptions = []
        for band in selected_bands:
            try:
                first_colorinterp.append(datasets[0].colorinterp[band - 1].name)
            except Exception:
                first_colorinterp.append(ColorInterp.undefined.name)
            first_descriptions.append(datasets[0].descriptions[band - 1])

    return OutputPlan(
        grid=grid,
        plan_grid=plan_grid,
        plan_scale=plan_scale,
        selected_bands=selected_bands,
        rgb_positions=rgb_positions,
        nir_position=nir_position,
        output_dtype=output_dtype,
        working_dtype=working_dtype,
        output_nodata=output_nodata,
        uncompressed_bytes=uncompressed_bytes,
        mask_bytes=mask_bytes,
        overview_bytes_estimate=overview_bytes,
        conservative_bytes=conservative,
        bigtiff=bigtiff,
        source_infos=source_infos,
        first_colorinterp=first_colorinterp,
        first_descriptions=first_descriptions,
    )


def estimated_planning_memory_bytes(plan: OutputPlan) -> int:
    """Conservative working-set estimate for the bounded planning pass."""
    plan_source_pixels = sum(
        (info.plan_window[2] * info.plan_window[3]) if info.plan_window else 0
        for info in plan.source_infos
    )
    # Per-source data, masks, cloud scores, display images, distance transforms,
    # and OpenCV workspaces dominate. Global label/cost arrays are added
    # separately. This is an estimate, not an allocator guarantee.
    per_source_pixel = np.dtype(plan.working_dtype).itemsize * len(plan.selected_bands) + 96
    per_output_pixel = 40
    return int(
        plan_source_pixels * per_source_pixel
        + plan.plan_grid.width * plan.plan_grid.height * per_output_pixel
    )


def estimated_tile_memory_bytes(
    plan: OutputPlan, tile_size: int, args: argparse.Namespace
) -> int:
    """Estimate the peak work-window allocation for one full-resolution tile."""
    halo = max(int(args.feather), int(args.cloud_dilate), 0) + 2
    side = max(1, int(tile_size)) + 2 * halo
    working_bytes = np.dtype(plan.working_dtype).itemsize
    accumulator_bytes = 8 if working_bytes > 4 or plan.output_dtype == "float64" else 4
    output_bytes = max(np.dtype(plan.output_dtype).itemsize, 4)
    # Persistent accumulators plus one source's data, corrected data, cloud
    # arrays, seam distance transforms, masks, and output/cast workspaces.
    bytes_per_pixel = (
        (2 * accumulator_bytes + 3 * working_bytes + output_bytes)
        * len(plan.selected_bands)
        + 128
    )
    return int(side * side * bytes_per_pixel)


def adjust_tile_size_for_memory(plan: OutputPlan, args: argparse.Namespace) -> int:
    """Reduce --tile-size when its estimated work set exceeds the memory cap."""
    budget = int(args.tile_max_memory_mb) * 1024 * 1024
    halo = max(int(args.feather), int(args.cloud_dilate), 0) + 2
    working_bytes = np.dtype(plan.working_dtype).itemsize
    accumulator_bytes = 8 if working_bytes > 4 or plan.output_dtype == "float64" else 4
    output_bytes = max(np.dtype(plan.output_dtype).itemsize, 4)
    bytes_per_pixel = (
        (2 * accumulator_bytes + 3 * working_bytes + output_bytes)
        * len(plan.selected_bands)
        + 128
    )
    minimum = (1 + 2 * halo) ** 2 * bytes_per_pixel
    if minimum > budget:
        raise MosaicError(
            "--tile-max-memory-mb is too small for the requested feather/cloud halo; "
            f"at least {math.ceil(minimum / (1024 * 1024))} MB is estimated"
        )

    work_side = int(math.floor(math.sqrt(budget / max(bytes_per_pixel, 1))))
    max_core = max(1, work_side - 2 * halo)
    effective = min(int(args.tile_size), max_core)
    # Larger, regular windows are generally friendlier to GDAL. Do not round
    # tiny windows up past the budget.
    if effective >= 64:
        effective = max(64, (effective // 64) * 64)
    if effective < args.tile_size:
        LOGGER.warning(
            "Reducing processing tile size from %d to %d to respect the %d MB "
            "tile memory budget",
            args.tile_size,
            effective,
            args.tile_max_memory_mb,
        )
        args.tile_size = effective
    return estimated_tile_memory_bytes(plan, args.tile_size, args)


def plan_summary(
    plan: OutputPlan, args: argparse.Namespace | None = None
) -> dict[str, Any]:
    plan_source_pixels = sum(
        (info.plan_window[2] * info.plan_window[3]) if info.plan_window else 0
        for info in plan.source_infos
    )
    summary: dict[str, Any] = {
        "target_crs": plan.grid.crs.to_string(),
        "bounds": plan.grid.bounds,
        "resolution": plan.grid.resolution,
        "width": plan.grid.width,
        "height": plan.grid.height,
        "pixels": plan.grid.width * plan.grid.height,
        "bands": plan.selected_bands,
        "dtype": plan.output_dtype,
        "working_dtype": plan.working_dtype,
        "nodata": plan.output_nodata,
        "uncompressed_gib": plan.uncompressed_bytes / GIB,
        "mask_gib": plan.mask_bytes / GIB,
        "overview_gib_estimate": plan.overview_bytes_estimate / GIB,
        "conservative_gib": plan.conservative_bytes / GIB,
        "bigtiff": plan.bigtiff,
        "planning_scale": plan.plan_scale,
        "planning_width": plan.plan_grid.width,
        "planning_height": plan.plan_grid.height,
        "planning_pixels": plan.plan_grid.width * plan.plan_grid.height,
        "planning_source_pixels": plan_source_pixels,
        "planning_memory_gib_estimate": estimated_planning_memory_bytes(plan) / GIB,
    }
    if args is not None:
        summary.update(
            {
                "effective_tile_size": args.tile_size,
                "tile_memory_mib_estimate": estimated_tile_memory_bytes(
                    plan, args.tile_size, args
                )
                / (1024 * 1024),
                "tile_memory_budget_mib": args.tile_max_memory_mb,
                "planning_memory_budget_mib": args.plan_max_memory_mb,
            }
        )
    return summary


def _make_data_vrt(
    src: rasterio.io.DatasetReader,
    grid: GridSpec,
    resampling: Resampling,
    warp_mem_limit_mb: int,
) -> WarpedVRT:
    return WarpedVRT(
        src,
        crs=grid.crs,
        transform=grid.transform,
        width=grid.width,
        height=grid.height,
        resampling=resampling,
        add_alpha=True,
        warp_mem_limit=warp_mem_limit_mb,
        init_dest_nodata=False,
    )


def _make_cloud_vrt(
    src: rasterio.io.DatasetReader,
    grid: GridSpec,
    warp_mem_limit_mb: int,
) -> WarpedVRT:
    return WarpedVRT(
        src,
        crs=grid.crs,
        transform=grid.transform,
        width=grid.width,
        height=grid.height,
        resampling=Resampling.nearest,
        add_alpha=True,
        warp_mem_limit=warp_mem_limit_mb,
        init_dest_nodata=False,
    )


def cloud_mask_from_values(values: np.ndarray, spec: InputSpec) -> np.ndarray:
    mode = spec.cloud_mask_mode
    if mode == "nonzero":
        return values != 0
    if mode == "zero":
        return values == 0
    if mode == "probability":
        return values.astype(np.float32) >= float(spec.cloud_mask_threshold)
    raise MosaicError(f"Unknown cloud mask mode: {mode}")


def cloud_probability_from_values(values: np.ndarray, spec: InputSpec) -> np.ndarray:
    """Convert an external QA/mask band to a 0..1 cloud probability surface."""
    if spec.cloud_mask_mode == "probability":
        return np.clip(values.astype(np.float32), 0.0, 1.0)
    return cloud_mask_from_values(values, spec).astype(np.float32)


def robust_band_percentiles(
    data: np.ndarray, valid: np.ndarray, max_samples: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    band_count = data.shape[0]
    indices = np.flatnonzero(valid)
    if indices.size == 0:
        return np.zeros(band_count, np.float64), np.ones(band_count, np.float64)
    if indices.size > max_samples:
        rng = np.random.default_rng(seed)
        indices = rng.choice(indices, size=max_samples, replace=False)
    flat = data.reshape(band_count, -1)[:, indices]
    low = np.nanpercentile(flat, 2.0, axis=1).astype(np.float64)
    high = np.nanpercentile(flat, 98.0, axis=1).astype(np.float64)
    too_small = ~np.isfinite(high - low) | ((high - low) <= 1e-12)
    low[~np.isfinite(low)] = 0.0
    high[~np.isfinite(high)] = 1.0
    high[too_small] = low[too_small] + 1.0
    return low, high


def smoothstep(low: float, high: float, values: np.ndarray) -> np.ndarray:
    if high <= low:
        return (values >= high).astype(np.float32)
    t = np.clip((values - low) / (high - low), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def automatic_cloud_probability(
    data: np.ndarray,
    valid: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    rgb_positions: tuple[int, int, int],
    nir_position: int | None,
) -> np.ndarray:
    eps = np.float32(1e-6)
    rgb = np.stack([data[p] for p in rgb_positions], axis=0).astype(np.float32, copy=False)
    rgb_low = np.array([low[p] for p in rgb_positions], dtype=np.float32)[:, None, None]
    rgb_high = np.array([high[p] for p in rgb_positions], dtype=np.float32)[:, None, None]
    rgb_n = np.clip((rgb - rgb_low) / np.maximum(rgb_high - rgb_low, eps), 0.0, 1.0)
    brightness = np.mean(rgb_n, axis=0)
    max_rgb = np.max(rgb_n, axis=0)
    min_rgb = np.min(rgb_n, axis=0)
    saturation = (max_rgb - min_rgb) / np.maximum(max_rgb, np.float32(0.05))
    whiteness = 1.0 - smoothstep(0.10, 0.38, saturation)
    bright_score = smoothstep(0.55, 0.92, brightness)
    blue_haze = smoothstep(-0.05, 0.28, rgb_n[2] - rgb_n[0])
    cloud = bright_score * np.clip(0.60 * whiteness + 0.40 * np.maximum(whiteness, blue_haze), 0.0, 1.0)
    if nir_position is not None:
        nir = np.clip(
            (data[nir_position] - low[nir_position])
            / max(high[nir_position] - low[nir_position], 1e-6),
            0.0,
            1.0,
        )
        cloud *= 0.70 + 0.30 * smoothstep(0.25, 0.80, nir)
    cloud = np.where(valid, cloud, 0.0).astype(np.float32)
    return cloud


def load_planning_sources(plan: OutputPlan, args: argparse.Namespace) -> list[PlanSource]:
    resampling = resampling_from_name(args.resampling)
    result: list[PlanSource] = []
    for info in plan.source_infos:
        with ExitStack() as stack:
            src = stack.enter_context(rasterio.open(info.spec.path))
            vrt = stack.enter_context(
                _make_data_vrt(src, plan.plan_grid, resampling, args.warp_mem_limit)
            )
            alpha_band = vrt.count
            window = tuple_to_window(info.plan_window or (0, 0, 0, 0))
            if window.width <= 0 or window.height <= 0:
                LOGGER.warning("Source %s has no pixels in the planning grid", info.spec.path)
                data = np.zeros((len(plan.selected_bands), 0, 0), dtype=np.float32)
                valid = np.zeros((0, 0), dtype=bool)
            else:
                data = vrt.read(
                    plan.selected_bands,
                    window=window,
                    out_dtype=plan.working_dtype,
                )
                alpha = vrt.read(alpha_band, window=window)
                valid = alpha > 0
                valid &= np.all(np.isfinite(data), axis=0)

            low, high = robust_band_percentiles(
                data,
                valid,
                max_samples=args.percentile_samples,
                seed=args.seed + info.index * 1009,
            )
            info.percentiles_low = low.tolist()
            info.percentiles_high = high.tolist()

            cloud_prob = np.zeros(valid.shape, dtype=np.float32)
            auto_cloud_binary = np.zeros(valid.shape, dtype=bool)
            if args.auto_cloud and valid.any():
                cloud_prob = automatic_cloud_probability(
                    data,
                    valid,
                    low,
                    high,
                    plan.rgb_positions,
                    plan.nir_position,
                )
                threshold = float(args.cloud_threshold)
                auto_cloud_binary = cloud_prob >= threshold
                predicted_fraction = float(auto_cloud_binary[valid].mean()) if valid.any() else 0.0
                if predicted_fraction > args.max_auto_cloud_fraction:
                    adjusted = float(
                        np.quantile(
                            cloud_prob[valid],
                            max(0.0, 1.0 - args.max_auto_cloud_fraction),
                        )
                    )
                    threshold = max(threshold, adjusted)
                    auto_cloud_binary = cloud_prob >= threshold
                    LOGGER.warning(
                        "Auto-cloud masking for %s was capped from %.1f%% to at most %.1f%%; "
                        "use a sensor QA mask for snow or bright terrain",
                        info.spec.path,
                        predicted_fraction * 100.0,
                        args.max_auto_cloud_fraction * 100.0,
                    )
                info.auto_cloud_threshold = threshold
            else:
                info.auto_cloud_threshold = None

            external_cloud = np.zeros(valid.shape, dtype=bool)
            if info.spec.cloud_mask:
                cloud_src = stack.enter_context(rasterio.open(info.spec.cloud_mask))
                if cloud_src.crs is None:
                    raise MosaicError(f"Cloud mask has no CRS: {info.spec.cloud_mask}")
                if (
                    info.spec.cloud_mask_mode == "zero"
                    and cloud_src.nodatavals
                    and cloud_src.nodatavals[0] == 0
                ):
                    LOGGER.warning(
                        "Cloud mask %s uses zero both as nodata and as the cloud class; "
                        "zero-valued pixels masked as nodata cannot be interpreted as clouds",
                        info.spec.cloud_mask,
                    )
                cloud_vrt = stack.enter_context(
                    _make_cloud_vrt(cloud_src, plan.plan_grid, args.warp_mem_limit)
                )
                cloud_values = cloud_vrt.read(1, window=window)
                cloud_valid = cloud_vrt.read(cloud_vrt.count, window=window) > 0
                external_probability = cloud_probability_from_values(
                    cloud_values, info.spec
                )
                external_probability = np.where(
                    cloud_valid & valid, external_probability, 0.0
                ).astype(np.float32)
                external_cloud = (
                    cloud_mask_from_values(cloud_values, info.spec)
                    & cloud_valid
                    & valid
                )
                cloud_prob = np.maximum(cloud_prob, external_probability)

            combined_cloud = (auto_cloud_binary | external_cloud) & valid
            if args.cloud_dilate > 0 and combined_cloud.any():
                planning_iterations = max(
                    1, int(math.ceil(args.cloud_dilate / plan.plan_scale))
                )
                combined_cloud = (
                    ndimage.binary_dilation(
                        combined_cloud,
                        iterations=planning_iterations,
                    )
                    & valid
                )
            cloud_prob = np.maximum(cloud_prob, combined_cloud.astype(np.float32))
            clear = valid & ~combined_cloud
            if valid.any() and not clear.any():
                LOGGER.warning(
                    "All valid planning pixels are cloudy for %s; least-cloudy fallback may be used",
                    info.spec.path,
                )
            result.append(
                PlanSource(
                    info=info,
                    window=window,
                    data=data,
                    valid=valid,
                    clear=clear,
                    cloud_probability=cloud_prob,
                )
            )
            LOGGER.info(
                "Planning source %d/%d: %s, %dx%d, valid %.1f%%, clear %.1f%%",
                info.index + 1,
                len(plan.source_infos),
                info.spec.path,
                int(window.width),
                int(window.height),
                (100.0 * valid.mean()) if valid.size else 0.0,
                (100.0 * clear.mean()) if clear.size else 0.0,
            )
    return result


def overlapping_pairs(windows: Sequence[Window]) -> Iterable[tuple[int, int]]:
    indexed = sorted(
        enumerate(windows),
        key=lambda item: float(item[1].col_off),
    )
    active: list[tuple[int, Window]] = []
    for idx, window in indexed:
        left = float(window.col_off)
        active = [
            item
            for item in active
            if float(item[1].col_off + item[1].width) > left
        ]
        row0 = float(window.row_off)
        row1 = row0 + float(window.height)
        for other_idx, other in active:
            other_row0 = float(other.row_off)
            other_row1 = other_row0 + float(other.height)
            if min(row1, other_row1) > max(row0, other_row0):
                yield min(idx, other_idx), max(idx, other_idx)
        active.append((idx, window))


def overlap_local_slices(a: Window, b: Window) -> tuple[slice, slice, slice, slice] | None:
    col0 = max(int(a.col_off), int(b.col_off))
    row0 = max(int(a.row_off), int(b.row_off))
    col1 = min(int(a.col_off + a.width), int(b.col_off + b.width))
    row1 = min(int(a.row_off + a.height), int(b.row_off + b.height))
    if col1 <= col0 or row1 <= row0:
        return None
    a_rows = slice(row0 - int(a.row_off), row1 - int(a.row_off))
    a_cols = slice(col0 - int(a.col_off), col1 - int(a.col_off))
    b_rows = slice(row0 - int(b.row_off), row1 - int(b.row_off))
    b_cols = slice(col0 - int(b.col_off), col1 - int(b.col_off))
    return a_rows, a_cols, b_rows, b_cols


def robust_pair_summary(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float, int, float] | None:
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite].astype(np.float64, copy=False)
    y = y[finite].astype(np.float64, copy=False)
    if x.size < 16:
        return None
    x_lo, x_hi = np.quantile(x, [0.02, 0.98])
    y_lo, y_hi = np.quantile(y, [0.02, 0.98])
    keep = (x >= x_lo) & (x <= x_hi) & (y >= y_lo) & (y <= y_hi)
    x = x[keep]
    y = y[keep]
    if x.size < 16:
        return None
    x_q25, x_med, x_q75 = np.quantile(x, [0.25, 0.5, 0.75])
    y_q25, y_med, y_q75 = np.quantile(y, [0.25, 0.5, 0.75])
    x_scale = float(x_q75 - x_q25)
    y_scale = float(y_q75 - y_q25)
    dynamic = max(abs(float(x_med)), abs(float(y_med)), 1.0)
    minimum_resolvable_scale = max(
        np.finfo(np.float64).eps * dynamic * 128.0,
        1e-12,
    )
    if x_scale <= minimum_resolvable_scale or y_scale <= minimum_resolvable_scale:
        return None
    diff = y - x
    diff_med = np.median(diff)
    diff_mad = float(np.median(np.abs(diff - diff_med)))
    mismatch = diff_mad / max(0.5 * (x_scale + y_scale), 1e-9)
    weight = math.sqrt(float(x.size)) / (1.0 + mismatch)
    return float(x_med), float(y_med), x_scale, y_scale, int(x.size), float(weight)


def compute_overlap_edges(
    sources: list[PlanSource], plan: OutputPlan, args: argparse.Namespace
) -> list[OverlapEdge]:
    edges: list[OverlapEdge] = []
    for i, j in overlapping_pairs([s.window for s in sources]):
        a = sources[i]
        b = sources[j]
        overlap = overlap_local_slices(a.window, b.window)
        if overlap is None:
            continue
        ar, ac, br, bc = overlap
        common = a.clear[ar, ac] & b.clear[br, bc]
        if common.sum() < args.min_overlap_samples and args.allow_cloudy_radiometry:
            common = a.valid[ar, ac] & b.valid[br, bc]
        indices = np.flatnonzero(common)
        if indices.size < args.min_overlap_samples:
            continue
        if indices.size > args.overlap_samples:
            rng = np.random.default_rng(args.seed + i * 1_000_003 + j * 9_176)
            indices = rng.choice(indices, size=args.overlap_samples, replace=False)

        a_flat = a.data[:, ar, ac].reshape(len(plan.selected_bands), -1)[:, indices]
        b_flat = b.data[:, br, bc].reshape(len(plan.selected_bands), -1)[:, indices]
        med_i: list[float | None] = []
        med_j: list[float | None] = []
        scale_i: list[float | None] = []
        scale_j: list[float | None] = []
        counts: list[int] = []
        weights: list[float] = []
        any_band = False
        for band in range(len(plan.selected_bands)):
            summary = robust_pair_summary(a_flat[band], b_flat[band])
            if summary is None:
                med_i.append(None)
                med_j.append(None)
                scale_i.append(None)
                scale_j.append(None)
                counts.append(0)
                weights.append(0.0)
                continue
            mi, mj, si, sj, count, weight = summary
            med_i.append(mi)
            med_j.append(mj)
            scale_i.append(si)
            scale_j.append(sj)
            counts.append(count)
            weights.append(weight)
            any_band = True
        if any_band:
            edges.append(
                OverlapEdge(
                    source_i=i,
                    source_j=j,
                    overlap_pixels=int(common.sum()),
                    med_i=med_i,
                    med_j=med_j,
                    scale_i=scale_i,
                    scale_j=scale_j,
                    counts=counts,
                    weights=weights,
                )
            )
    LOGGER.info("Found %d usable overlap relationships", len(edges))
    return edges


def connected_components(num_nodes: int, pair_edges: Sequence[tuple[int, int]]) -> list[list[int]]:
    adjacency: list[list[int]] = [[] for _ in range(num_nodes)]
    for i, j in pair_edges:
        adjacency[i].append(j)
        adjacency[j].append(i)
    seen = [False] * num_nodes
    components: list[list[int]] = []
    for start in range(num_nodes):
        if seen[start]:
            continue
        stack = [start]
        seen[start] = True
        component: list[int] = []
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbor in adjacency[node]:
                if not seen[neighbor]:
                    seen[neighbor] = True
                    stack.append(neighbor)
        components.append(component)
    return components


def solve_sparse_pair_system(
    num_sources: int,
    equations: Sequence[tuple[int, int, float, float]],
    anchors: Sequence[int],
    regularization: float,
) -> np.ndarray:
    if not equations:
        return np.zeros(num_sources, dtype=np.float64)
    weights = [max(eq[3], 1e-6) for eq in equations]
    median_weight = float(np.median(weights)) if weights else 1.0
    row_indices: list[int] = []
    col_indices: list[int] = []
    values: list[float] = []
    rhs: list[float] = []
    row = 0
    for i, j, target, weight in equations:
        sw = math.sqrt(max(weight, 1e-8))
        row_indices.extend([row, row])
        col_indices.extend([i, j])
        values.extend([sw, -sw])
        rhs.append(target * sw)
        row += 1

    anchor_weight = math.sqrt(max(sum(weights), 1.0) * 100.0)
    for anchor in anchors:
        row_indices.append(row)
        col_indices.append(anchor)
        values.append(anchor_weight)
        rhs.append(0.0)
        row += 1

    reg_weight = math.sqrt(max(regularization, 0.0) * max(median_weight, 1e-6))
    if reg_weight > 0:
        for source in range(num_sources):
            row_indices.append(row)
            col_indices.append(source)
            values.append(reg_weight)
            rhs.append(0.0)
            row += 1

    matrix = coo_matrix(
        (np.asarray(values), (np.asarray(row_indices), np.asarray(col_indices))),
        shape=(row, num_sources),
        dtype=np.float64,
    ).tocsr()
    solution = lsqr(matrix, np.asarray(rhs, dtype=np.float64), atol=1e-10, btol=1e-10)[0]
    solution[~np.isfinite(solution)] = 0.0
    components = connected_components(
        num_sources, [(i, j) for i, j, _, _ in equations]
    )
    anchor_set = set(anchors)
    for component in components:
        component_anchor = next((a for a in component if a in anchor_set), component[0])
        solution[component] -= solution[component_anchor]
    return solution


def solve_global_radiometry(
    sources: list[PlanSource],
    edges: list[OverlapEdge],
    plan: OutputPlan,
    args: argparse.Namespace,
) -> dict[str, Any]:
    source_count = len(sources)
    band_count = len(plan.selected_bands)
    gains = np.ones((source_count, band_count), dtype=np.float64)
    offsets = np.zeros((source_count, band_count), dtype=np.float64)
    anchors_by_band: list[list[int]] = []
    priorities = np.asarray([s.info.spec.priority for s in sources], dtype=np.float64)

    if args.balance == "none" or source_count == 1:
        for source in sources:
            source.info.gains = [1.0] * band_count
            source.info.offsets = [0.0] * band_count
        return {
            "mode": args.balance,
            "anchors_by_band": [[0] for _ in range(band_count)],
            "gains": gains.tolist(),
            "offsets": offsets.tolist(),
        }

    for band in range(band_count):
        usable = [
            edge
            for edge in edges
            if edge.counts[band] >= args.min_overlap_samples
            and edge.scale_i[band] is not None
            and edge.scale_j[band] is not None
            and edge.weights[band] > 0
        ]
        components = connected_components(
            source_count, [(edge.source_i, edge.source_j) for edge in usable]
        )
        weighted_degree = np.zeros(source_count, dtype=np.float64)
        for edge in usable:
            weighted_degree[edge.source_i] += edge.weights[band]
            weighted_degree[edge.source_j] += edge.weights[band]
        anchors: list[int] = []
        for component in components:
            anchor = max(
                component,
                key=lambda idx: (weighted_degree[idx], priorities[idx], -idx),
            )
            anchors.append(anchor)
        anchors_by_band.append(anchors)

        if args.balance in {"gain", "gain-offset"} and usable:
            gain_equations: list[tuple[int, int, float, float]] = []
            max_log = math.log(max(args.max_gain, 1.000001))
            min_log = math.log(max(args.min_gain, 1e-6))
            for edge in usable:
                target = math.log(float(edge.scale_j[band]) / float(edge.scale_i[band]))
                target = float(np.clip(target, min_log, max_log))
                gain_equations.append(
                    (edge.source_i, edge.source_j, target, edge.weights[band])
                )
            log_gains = solve_sparse_pair_system(
                source_count,
                gain_equations,
                anchors,
                regularization=args.radiometric_regularization,
            )
            gains[:, band] = np.clip(np.exp(log_gains), args.min_gain, args.max_gain)

        if args.balance in {"offset", "gain-offset"} and usable:
            offset_equations: list[tuple[int, int, float, float]] = []
            for edge in usable:
                target = (
                    gains[edge.source_j, band] * float(edge.med_j[band])
                    - gains[edge.source_i, band] * float(edge.med_i[band])
                )
                offset_equations.append(
                    (edge.source_i, edge.source_j, target, edge.weights[band])
                )
            band_offsets = solve_sparse_pair_system(
                source_count,
                offset_equations,
                anchors,
                regularization=args.radiometric_regularization,
            )
            ranges = [
                source.info.percentiles_high[band] - source.info.percentiles_low[band]
                for source in sources
                if source.info.percentiles_high and source.info.percentiles_low
            ]
            positive_ranges = [r for r in ranges if r > 0 and math.isfinite(r)]
            typical_range = float(np.median(positive_ranges)) if positive_ranges else 1.0
            limit = max(typical_range * args.max_offset_ranges, 1.0)
            offsets[:, band] = np.clip(band_offsets, -limit, limit)

    for source_index, source in enumerate(sources):
        source.info.gains = gains[source_index].tolist()
        source.info.offsets = offsets[source_index].tolist()

    return {
        "mode": args.balance,
        "anchors_by_band": anchors_by_band,
        "gains": gains.tolist(),
        "offsets": offsets.tolist(),
    }


def corrected_display_ranges(
    sources: Sequence[PlanSource],
    plan: OutputPlan,
    max_samples: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    samples: list[np.ndarray] = []
    rng = np.random.default_rng(seed)
    per_source = max(1, max_samples // max(1, len(sources)))
    for source in sources:
        mask = source.clear if source.clear.any() else source.valid
        indices = np.flatnonzero(mask)
        if indices.size == 0:
            continue
        if indices.size > per_source:
            indices = rng.choice(indices, size=per_source, replace=False)
        rgb_rows = []
        for position in plan.rgb_positions:
            values = source.data[position].reshape(-1)[indices].astype(np.float64)
            values = values * source.info.gains[position] + source.info.offsets[position]
            rgb_rows.append(values)
        samples.append(np.stack(rgb_rows, axis=1))
    if not samples:
        return np.zeros(3, dtype=np.float64), np.ones(3, dtype=np.float64)
    joined = np.concatenate(samples, axis=0)
    low = np.nanpercentile(joined, 2.0, axis=0)
    high = np.nanpercentile(joined, 98.0, axis=0)
    high = np.where((high - low) > 1e-9, high, low + 1.0)
    return low.astype(np.float64), high.astype(np.float64)


def make_seam_image(
    source: PlanSource,
    plan: OutputPlan,
    display_low: np.ndarray,
    display_high: np.ndarray,
) -> np.ndarray:
    channels: list[np.ndarray] = []
    for channel, position in enumerate(plan.rgb_positions):
        corrected = (
            source.data[position].astype(np.float32) * np.float32(source.info.gains[position])
            + np.float32(source.info.offsets[position])
        )
        normalized = np.clip(
            (corrected - np.float32(display_low[channel]))
            / np.float32(max(display_high[channel] - display_low[channel], 1e-6)),
            0.0,
            1.0,
        )
        channels.append(normalized * np.float32(255.0))
    image = np.stack(channels, axis=-1).astype(np.float32)
    image[~source.valid] = 0.0
    return np.ascontiguousarray(image)


def normalize_priorities(sources: Sequence[PlanSource]) -> np.ndarray:
    values = np.asarray([s.info.spec.priority for s in sources], dtype=np.float32)
    if values.size == 0 or float(values.max() - values.min()) < 1e-9:
        return np.zeros(values.shape, dtype=np.float32)
    return (values - values.min()) / (values.max() - values.min())


def generate_seam_labels(
    sources: list[PlanSource],
    plan: OutputPlan,
    args: argparse.Namespace,
) -> tuple[np.ndarray, dict[str, Any]]:
    source_count = len(sources)
    label_dtype = np.uint16 if source_count <= np.iinfo(np.uint16).max - 1 else np.uint32
    labels = np.zeros((plan.plan_grid.height, plan.plan_grid.width), dtype=label_dtype)
    if not sources:
        return labels, {"method": args.seam_method, "status": "no sources"}

    display_low, display_high = corrected_display_ranges(
        sources, plan, args.percentile_samples, args.seed + 7717
    )
    images = [make_seam_image(s, plan, display_low, display_high) for s in sources]
    initial_masks: list[np.ndarray] = []
    for source in sources:
        if source.clear.any():
            preferred = source.clear
        elif args.all_cloud_policy == "least-cloudy":
            preferred = source.valid
        else:
            preferred = source.clear
        initial_masks.append((preferred.astype(np.uint8) * 255))
    corners = [(int(s.window.col_off), int(s.window.row_off)) for s in sources]

    cut_masks: list[np.ndarray]
    seam_status = "ok"
    try:
        if source_count == 1 or args.seam_method == "none":
            cut_masks = initial_masks
        elif args.seam_method == "graphcut":
            finder = cv.detail_GraphCutSeamFinder("COST_COLOR_GRAD")
            umat_masks = [cv.UMat(np.ascontiguousarray(m)) for m in initial_masks]
            output_masks = finder.find(images, corners, umat_masks)
            cut_masks = [m.get() if hasattr(m, "get") else np.asarray(m) for m in output_masks]
        elif args.seam_method == "voronoi":
            finder = cv.detail.SeamFinder_createDefault(cv.detail.SeamFinder_VORONOI_SEAM)
            umat_masks = [cv.UMat(np.ascontiguousarray(m)) for m in initial_masks]
            output_masks = finder.find(images, corners, umat_masks)
            cut_masks = [m.get() if hasattr(m, "get") else np.asarray(m) for m in output_masks]
        else:
            raise MosaicError(f"Unknown seam method: {args.seam_method}")
    except cv.error as exc:
        LOGGER.warning("OpenCV seam generation failed; falling back to weighted Voronoi: %s", exc)
        cut_masks = initial_masks
        seam_status = f"fallback after OpenCV error: {exc}"

    priority_norm = normalize_priorities(sources)
    best_score = np.full(labels.shape, -np.inf, dtype=np.float32)
    for idx, (source, cut_mask) in enumerate(zip(sources, cut_masks, strict=True)):
        cut = (np.asarray(cut_mask) > 0) & source.valid
        if not cut.any():
            continue
        distance = ndimage.distance_transform_edt(cut).astype(np.float32)
        score = distance + priority_norm[idx] * np.float32(0.01)
        row = int(source.window.row_off)
        col = int(source.window.col_off)
        h, w = cut.shape
        score_view = best_score[row : row + h, col : col + w]
        label_view = labels[row : row + h, col : col + w]
        update = cut & (score > score_view)
        score_view[update] = score[update]
        label_view[update] = idx + 1

    uncovered = labels == 0
    if uncovered.any():
        fallback_cost = np.full(labels.shape, np.inf, dtype=np.float32)
        fallback_labels = np.zeros(labels.shape, dtype=label_dtype)
        for idx, source in enumerate(sources):
            candidate = source.valid if args.all_cloud_policy == "least-cloudy" else source.clear
            if not candidate.any():
                continue
            edge_distance = ndimage.distance_transform_edt(candidate).astype(np.float32)
            cost = (
                source.cloud_probability.astype(np.float32) * np.float32(args.cloud_cost_weight)
                + np.float32(args.edge_cost_weight) / (edge_distance + np.float32(1.0))
                - priority_norm[idx] * np.float32(args.priority_cost_weight)
            )
            row = int(source.window.row_off)
            col = int(source.window.col_off)
            h, w = candidate.shape
            cost_view = fallback_cost[row : row + h, col : col + w]
            label_view = fallback_labels[row : row + h, col : col + w]
            update = candidate & (cost < cost_view)
            cost_view[update] = cost[update]
            label_view[update] = idx + 1
        use_fallback = uncovered & (fallback_labels > 0)
        labels[use_fallback] = fallback_labels[use_fallback]

    return labels, {
        "method": args.seam_method,
        "status": seam_status,
        "display_low": display_low.tolist(),
        "display_high": display_high.tolist(),
        "assigned_fraction": float((labels > 0).mean()),
    }


def write_seam_labels(path: Path, labels: np.ndarray, plan: OutputPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    block = min(512, max(64, 2 ** int(math.floor(math.log2(max(64, min(labels.shape)))))))
    profile = {
        "driver": "GTiff",
        "width": labels.shape[1],
        "height": labels.shape[0],
        "count": 1,
        "dtype": labels.dtype.name,
        "crs": plan.plan_grid.crs,
        "transform": plan.plan_grid.transform,
        "tiled": True,
        "blockxsize": block,
        "blockysize": block,
        "compress": "deflate",
        "predictor": 2,
        "bigtiff": "IF_SAFER",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(labels, 1)
        dst.set_band_description(1, "source_id_1_based")
        dst.update_tags(plan_scale=plan.plan_scale, zero_means_unassigned="true")


def expanded_window(window: Window, halo: int, width: int, height: int) -> Window:
    col0 = max(0, int(window.col_off) - halo)
    row0 = max(0, int(window.row_off) - halo)
    col1 = min(width, int(window.col_off + window.width) + halo)
    row1 = min(height, int(window.row_off + window.height) + halo)
    return Window(col0, row0, col1 - col0, row1 - row0)


def iter_windows(width: int, height: int, tile_size: int) -> Iterable[Window]:
    for row in range(0, height, tile_size):
        h = min(tile_size, height - row)
        for col in range(0, width, tile_size):
            w = min(tile_size, width - col)
            yield Window(col, row, w, h)


def labels_for_window(labels: np.ndarray, window: Window, plan_scale: int) -> np.ndarray:
    row0 = int(window.row_off)
    col0 = int(window.col_off)
    h = int(window.height)
    w = int(window.width)
    row_indices = np.minimum(
        np.arange(row0, row0 + h, dtype=np.int64) // plan_scale,
        labels.shape[0] - 1,
    )
    col_indices = np.minimum(
        np.arange(col0, col0 + w, dtype=np.int64) // plan_scale,
        labels.shape[1] - 1,
    )
    return labels[np.ix_(row_indices, col_indices)]


def cosine_feather_weight(owner: np.ndarray, feather: int) -> np.ndarray:
    if feather <= 0:
        return owner.astype(np.float32)
    if owner.all():
        return np.ones(owner.shape, dtype=np.float32)
    if not owner.any():
        return np.zeros(owner.shape, dtype=np.float32)
    inside = ndimage.distance_transform_edt(owner).astype(np.float32)
    outside = ndimage.distance_transform_edt(~owner).astype(np.float32)
    signed = inside - outside
    t = np.clip((signed + np.float32(feather)) / np.float32(2 * feather), 0.0, 1.0)
    return (0.5 - 0.5 * np.cos(np.pi * t)).astype(np.float32)


def cast_output(data: np.ndarray, dtype: str) -> np.ndarray:
    dt = np.dtype(dtype)
    if dt.kind in "iu":
        limits = np.iinfo(dt)
        return np.clip(np.rint(data), limits.min, limits.max).astype(dt)
    if dt.kind == "f":
        return data.astype(dt)
    raise MosaicError(f"Unsupported output dtype: {dtype}")


def output_profile(plan: OutputPlan, args: argparse.Namespace) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "width": plan.grid.width,
        "height": plan.grid.height,
        "count": len(plan.selected_bands),
        "dtype": plan.output_dtype,
        "crs": plan.grid.crs,
        "transform": plan.grid.transform,
        "tiled": True,
        "blockxsize": args.block_size,
        "blockysize": args.block_size,
        "compress": args.compression,
        "bigtiff": plan.bigtiff,
        "num_threads": args.threads,
        "sparse_ok": False,
    }
    if plan.output_nodata is not None:
        profile["nodata"] = plan.output_nodata
    if args.compression in {"deflate", "lzw", "zstd"}:
        profile["predictor"] = 3 if np.dtype(plan.output_dtype).kind == "f" else 2
    if args.compression == "deflate":
        profile["zlevel"] = args.compression_level
    elif args.compression == "zstd":
        profile["zstd_level"] = args.compression_level
    if len(plan.selected_bands) <= 4:
        profile["interleave"] = "pixel"
    return profile


def open_runtime_source(
    info: SourceInfo,
    plan: OutputPlan,
    args: argparse.Namespace,
) -> RuntimeSource:
    resampling = resampling_from_name(args.resampling)
    try:
        src = rasterio.open(info.spec.path)
        vrt = _make_data_vrt(src, plan.grid, resampling, args.warp_mem_limit)
        cloud_dataset = None
        cloud_vrt = None
        if info.spec.cloud_mask:
            cloud_dataset = rasterio.open(info.spec.cloud_mask)
            cloud_vrt = _make_cloud_vrt(cloud_dataset, plan.grid, args.warp_mem_limit)
        return RuntimeSource(
            info=info,
            dataset=src,
            vrt=vrt,
            alpha_band=vrt.count,
            cloud_dataset=cloud_dataset,
            cloud_vrt=cloud_vrt,
        )
    except Exception:
        # Close partially opened objects without hiding the original exception.
        for obj in (locals().get("cloud_vrt"), locals().get("cloud_dataset"), locals().get("vrt"), locals().get("src")):
            if obj is not None:
                try:
                    obj.close()
                except Exception:
                    pass
        raise

def apply_cloud_model_full_resolution(
    data: np.ndarray,
    valid: np.ndarray,
    runtime: RuntimeSource,
    window: Window,
    plan: OutputPlan,
    args: argparse.Namespace,
) -> tuple[np.ndarray, np.ndarray]:
    cloud_probability = np.zeros(valid.shape, dtype=np.float32)
    cloud_binary = np.zeros(valid.shape, dtype=bool)
    low = np.asarray(runtime.info.percentiles_low, dtype=np.float64)
    high = np.asarray(runtime.info.percentiles_high, dtype=np.float64)
    if args.auto_cloud and valid.any():
        cloud_probability = automatic_cloud_probability(
            data,
            valid,
            low,
            high,
            plan.rgb_positions,
            plan.nir_position,
        )
        threshold = (
            runtime.info.auto_cloud_threshold
            if runtime.info.auto_cloud_threshold is not None
            else float(args.cloud_threshold)
        )
        cloud_binary |= cloud_probability >= float(threshold)
    if runtime.cloud_vrt is not None:
        values = runtime.cloud_vrt.read(1, window=window)
        mask_valid = runtime.cloud_vrt.read(runtime.cloud_vrt.count, window=window) > 0
        external_probability = cloud_probability_from_values(
            values, runtime.info.spec
        )
        external_probability = np.where(
            mask_valid & valid, external_probability, 0.0
        ).astype(np.float32)
        external = cloud_mask_from_values(values, runtime.info.spec) & mask_valid & valid
        cloud_binary |= external
        cloud_probability = np.maximum(cloud_probability, external_probability)
    if args.cloud_dilate > 0 and cloud_binary.any():
        cloud_binary = (
            ndimage.binary_dilation(cloud_binary, iterations=args.cloud_dilate) & valid
        )
        cloud_probability = np.maximum(
            cloud_probability, cloud_binary.astype(np.float32)
        )
    return cloud_probability, cloud_binary


def blend_and_write(
    plan: OutputPlan,
    labels: np.ndarray,
    output_path: Path,
    args: argparse.Namespace,
    report_path: Path,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_path.with_name(output_path.name + ".partial.tif")
    if partial_path.exists():
        partial_path.unlink()
    if output_path.exists() and not args.overwrite:
        raise MosaicError(f"Output already exists: {output_path}; use --overwrite")

    disk = shutil.disk_usage(output_path.parent)
    if disk.free < plan.conservative_bytes:
        message = (
            f"Free disk space ({disk.free / GIB:.2f} GiB) is below the conservative "
            f"uncompressed estimate ({plan.conservative_bytes / GIB:.2f} GiB)."
        )
        if args.strict_disk_check:
            raise MosaicError(message)
        LOGGER.warning(message)

    source_boxes = [box(*info.target_bounds) for info in plan.source_infos]
    spatial_index = STRtree(source_boxes)
    priority_values = np.asarray([info.spec.priority for info in plan.source_infos], dtype=np.float32)
    if priority_values.size and float(priority_values.max() - priority_values.min()) > 1e-9:
        priority_norm = (priority_values - priority_values.min()) / (
            priority_values.max() - priority_values.min()
        )
    else:
        priority_norm = np.zeros(priority_values.shape, dtype=np.float32)

    profile = output_profile(plan, args)
    total_tiles = math.ceil(plan.grid.width / args.tile_size) * math.ceil(
        plan.grid.height / args.tile_size
    )
    processed_tiles = 0
    start = time.monotonic()
    last_log = start
    valid_pixel_count = 0

    env_options = {
        "GDAL_NUM_THREADS": args.threads,
        "GDAL_TIFF_INTERNAL_MASK": True,
        "BIGTIFF_OVERVIEW": "IF_SAFER",
    }
    with rasterio.Env(**env_options), RuntimeSourceCache(plan, args) as source_cache, rasterio.open(
        partial_path, "w", **profile
    ) as dst:
        dst.update_tags(
            software=f"seamless_mosaic.py {PROGRAM_VERSION}",
            generated_utc=_utc_now(),
            analysis_report=str(report_path.name),
            planning_scale=plan.plan_scale,
            seam_method=args.seam_method,
            radiometric_balance=args.balance,
            cloud_handling=("automatic+external" if args.auto_cloud else "external-only"),
        )
        descriptions = [d or f"band_{band}" for d, band in zip(plan.first_descriptions, plan.selected_bands, strict=True)]
        for band_index, description in enumerate(descriptions, start=1):
            dst.set_band_description(band_index, description)
        try:
            colorinterp = tuple(ColorInterp[name] for name in plan.first_colorinterp)
            if len(colorinterp) == dst.count:
                dst.colorinterp = colorinterp
        except Exception:
            pass

        for core_window in iter_windows(plan.grid.width, plan.grid.height, args.tile_size):
            halo = max(0, args.feather, args.cloud_dilate) + 2
            work_window = expanded_window(
                core_window,
                halo,
                plan.grid.width,
                plan.grid.height,
            )
            work_h = int(work_window.height)
            work_w = int(work_window.width)
            label_window = labels_for_window(labels, work_window, plan.plan_scale)
            bounds = window_bounds(work_window, plan.grid.transform)
            candidate_indices = spatial_index.query(box(*bounds))
            candidate_indices = sorted(
                int(v) for v in np.atleast_1d(np.asarray(candidate_indices)).tolist()
            )

            sum_dtype = (
                np.float64
                if plan.working_dtype == "float64" or plan.output_dtype == "float64"
                else np.float32
            )
            weighted_sum = np.zeros(
                (len(plan.selected_bands), work_h, work_w), dtype=sum_dtype
            )
            weight_sum = np.zeros((work_h, work_w), dtype=np.float32)
            fallback_cost = np.full((work_h, work_w), np.inf, dtype=np.float32)
            fallback_data = np.zeros(
                (len(plan.selected_bands), work_h, work_w),
                dtype=np.dtype(plan.working_dtype),
            )
            fallback_valid = np.zeros((work_h, work_w), dtype=bool)

            for source_index in candidate_indices:
                runtime = source_cache.get(source_index)
                data = runtime.vrt.read(
                    plan.selected_bands,
                    window=work_window,
                    out_dtype=plan.working_dtype,
                )
                alpha = runtime.vrt.read(runtime.alpha_band, window=work_window)
                valid = (alpha > 0) & np.all(np.isfinite(data), axis=0)
                if not valid.any():
                    continue

                cloud_probability, cloud_binary = apply_cloud_model_full_resolution(
                    data, valid, runtime, work_window, plan, args
                )
                corrected = data.copy()
                scalar_type = np.float64 if plan.working_dtype == "float64" else np.float32
                for band in range(len(plan.selected_bands)):
                    corrected[band] = (
                        corrected[band] * scalar_type(runtime.info.gains[band])
                        + scalar_type(runtime.info.offsets[band])
                    )

                owner = label_window == (source_index + 1)
                seam_weight = cosine_feather_weight(owner, args.feather)
                clear_quality = np.power(
                    np.clip(1.0 - cloud_probability, 0.0, 1.0),
                    np.float32(args.cloud_weight_power),
                ).astype(np.float32)
                clear_quality[cloud_binary] = 0.0
                weight = seam_weight * clear_quality * valid.astype(np.float32)
                if np.any(weight > 0):
                    weighted_sum += corrected.astype(sum_dtype, copy=False) * weight[None, :, :]
                    weight_sum += weight

                if args.all_cloud_policy == "nodata":
                    fallback_candidate = valid & ~cloud_binary
                else:
                    fallback_candidate = valid
                if fallback_candidate.any():
                    cost = (
                        cloud_probability * np.float32(args.cloud_cost_weight)
                        - owner.astype(np.float32) * np.float32(0.10)
                        - priority_norm[source_index] * np.float32(args.priority_cost_weight)
                    )
                    update = fallback_candidate & (cost < fallback_cost)
                    if update.any():
                        fallback_cost[update] = cost[update]
                        fallback_valid[update] = True
                        fallback_data[:, update] = corrected[:, update]

            output_data = np.zeros_like(weighted_sum)
            blended = weight_sum > np.float32(1e-6)
            if blended.any():
                output_data[:, blended] = weighted_sum[:, blended] / weight_sum[blended]
            fallback_only = ~blended & fallback_valid
            if fallback_only.any():
                output_data[:, fallback_only] = fallback_data[:, fallback_only]
            valid_output = blended | fallback_only

            row_offset = int(core_window.row_off - work_window.row_off)
            col_offset = int(core_window.col_off - work_window.col_off)
            core_h = int(core_window.height)
            core_w = int(core_window.width)
            row_slice = slice(row_offset, row_offset + core_h)
            col_slice = slice(col_offset, col_offset + core_w)
            core_data = output_data[:, row_slice, col_slice]
            core_valid = valid_output[row_slice, col_slice]

            fill_value: float | int
            if plan.output_nodata is None:
                fill_value = 0
            else:
                fill_value = plan.output_nodata
            core_data[:, ~core_valid] = fill_value
            dst.write(cast_output(core_data, plan.output_dtype), window=core_window)
            dst.write_mask((core_valid.astype(np.uint8) * 255), window=core_window)
            valid_pixel_count += int(core_valid.sum())

            processed_tiles += 1
            now = time.monotonic()
            if now - last_log >= args.progress_interval or processed_tiles == total_tiles:
                elapsed = now - start
                rate = processed_tiles / max(elapsed, 1e-9)
                LOGGER.info(
                    "Full-resolution pass: %d/%d tiles (%.1f%%), %.2f tiles/s",
                    processed_tiles,
                    total_tiles,
                    100.0 * processed_tiles / total_tiles,
                    rate,
                )
                last_log = now

        if args.overviews:
            factors = [
                factor
                for factor in args.overview_factors
                if plan.grid.width // factor >= 1 and plan.grid.height // factor >= 1
            ]
            if factors:
                LOGGER.info("Building internal overviews: %s", factors)
                dst.build_overviews(factors, Resampling.average)
                dst.update_tags(ns="rio_overview", resampling="average")

    os.replace(partial_path, output_path)
    elapsed = time.monotonic() - start
    return {
        "output": str(output_path),
        "tiles": total_tiles,
        "elapsed_seconds": elapsed,
        "valid_pixels": valid_pixel_count,
        "coverage_fraction": valid_pixel_count / (plan.grid.width * plan.grid.height),
        "file_size_bytes": output_path.stat().st_size,
    }


def serialize_edge(edge: OverlapEdge) -> dict[str, Any]:
    return asdict(edge)


def base_report(plan: OutputPlan, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "program": "seamless_mosaic.py",
        "version": PROGRAM_VERSION,
        "generated_utc": _utc_now(),
        "command": getattr(args, "command", sys.argv),
        "output_plan": plan_summary(plan, args),
        "inputs": [
            {
                "index": info.index,
                "path": info.spec.path,
                "name": info.spec.name,
                "cloud_mask": info.spec.cloud_mask,
                "cloud_mask_mode": info.spec.cloud_mask_mode,
                "priority": info.spec.priority,
                "source_crs": info.crs,
                "source_bounds": info.source_bounds,
                "target_bounds": info.target_bounds,
                "source_width": info.source_width,
                "source_height": info.source_height,
                "source_count": info.source_count,
                "source_dtypes": info.source_dtypes,
                "full_window": info.full_window,
                "plan_window": info.plan_window,
            }
            for info in plan.source_infos
        ],
        "settings": {
            "balance": args.balance,
            "seam_method": args.seam_method,
            "feather_pixels": args.feather,
            "auto_cloud": args.auto_cloud,
            "cloud_threshold": args.cloud_threshold,
            "all_cloud_policy": args.all_cloud_policy,
            "resampling": args.resampling,
            "tile_size": args.tile_size,
            "tile_max_memory_mb": args.tile_max_memory_mb,
            "plan_max_memory_mb": args.plan_max_memory_mb,
            "block_size": args.block_size,
            "compression": args.compression,
            "overview_factors": args.overview_factors if args.overviews else [],
        },
    }


def run(args: argparse.Namespace) -> int:
    validate_block_size(args.block_size)
    if args.tile_size <= 0:
        raise MosaicError("--tile-size must be positive")
    if args.max_open_sources <= 0:
        raise MosaicError("--max-open-sources must be positive")
    if args.plan_max_memory_mb <= 0 or args.tile_max_memory_mb <= 0:
        raise MosaicError("Planning and tile memory budgets must be positive")
    if args.feather < 0:
        raise MosaicError("--feather cannot be negative")
    if args.cloud_dilate < 0:
        raise MosaicError("--cloud-dilate cannot be negative")
    if args.plan_max_output_pixels <= 0 or args.plan_max_source_pixels <= 0:
        raise MosaicError("Planning pixel limits must be positive")
    if args.overlap_samples <= 0 or args.min_overlap_samples <= 0:
        raise MosaicError("Overlap sample limits must be positive")
    if args.overlap_samples < args.min_overlap_samples:
        raise MosaicError("--overlap-samples must be at least --min-overlap-samples")
    if args.percentile_samples <= 0:
        raise MosaicError("--percentile-samples must be positive")
    if args.warp_mem_limit <= 0:
        raise MosaicError("--warp-mem-limit must be positive")
    if args.nir_band is not None and args.nir_band < 1:
        raise MosaicError("--nir-band must be a positive 1-based band number")
    if args.progress_interval < 0:
        raise MosaicError("--progress-interval cannot be negative")
    if not (0.0 <= args.cloud_threshold <= 1.0):
        raise MosaicError("--cloud-threshold must be between 0 and 1")
    if not (0.0 <= args.max_auto_cloud_fraction <= 1.0):
        raise MosaicError("--max-auto-cloud-fraction must be between 0 and 1")
    if args.min_gain <= 0 or args.max_gain < args.min_gain:
        raise MosaicError("Invalid gain limits")
    if args.radiometric_regularization < 0:
        raise MosaicError("--radiometric-regularization cannot be negative")
    if args.max_offset_ranges < 0:
        raise MosaicError("--max-offset-ranges cannot be negative")
    for name in (
        "edge_cost_weight",
        "priority_cost_weight",
        "cloud_cost_weight",
        "cloud_weight_power",
    ):
        value = float(getattr(args, name))
        if not math.isfinite(value) or value < 0:
            raise MosaicError(f"--{name.replace('_', '-')} must be finite and nonnegative")
    if args.compression == "deflate" and not (1 <= args.compression_level <= 9):
        raise MosaicError("DEFLATE --compression-level must be from 1 to 9")
    if args.compression == "zstd" and not (1 <= args.compression_level <= 22):
        raise MosaicError("ZSTD --compression-level must be from 1 to 22")
    if args.threads != "ALL_CPUS":
        try:
            thread_count = int(args.threads)
        except ValueError as exc:
            raise MosaicError("--threads must be ALL_CPUS or a positive integer") from exc
        if thread_count <= 0:
            raise MosaicError("--threads must be ALL_CPUS or a positive integer")
    if is_remote_path(args.output):
        raise MosaicError("The output must be a local filesystem path")
    if args.report and is_remote_path(args.report):
        raise MosaicError("The analysis report must be a local filesystem path")
    if args.work_dir and is_remote_path(args.work_dir):
        raise MosaicError("The work directory must be a local filesystem path")

    specs = load_input_specs(args)
    for spec in specs:
        if not math.isfinite(spec.priority):
            raise MosaicError(f"Input priority must be finite: {spec.path}")
        if not math.isfinite(spec.cloud_mask_threshold):
            raise MosaicError(f"Cloud-mask threshold must be finite: {spec.path}")
        if spec.cloud_mask_mode == "probability" and not (
            0.0 <= spec.cloud_mask_threshold <= 1.0
        ):
            raise MosaicError(
                f"Probability cloud-mask threshold must be between 0 and 1: {spec.path}"
            )
    output_path = Path(args.output).expanduser().resolve()
    partial_path = output_path.with_name(output_path.name + ".partial.tif")
    input_local_paths = {
        str(Path(spec.path).resolve())
        for spec in specs
        if not is_remote_path(spec.path)
    }
    input_local_paths.update(
        str(Path(spec.cloud_mask).resolve())
        for spec in specs
        if spec.cloud_mask and not is_remote_path(spec.cloud_mask)
    )
    ensure_artifact_path_is_safe(output_path, input_local_paths, "Output path")
    ensure_artifact_path_is_safe(
        partial_path, input_local_paths, "Partial output path", (output_path,)
    )
    if output_path.exists() and not args.overwrite and not args.dry_run and not args.analysis_only:
        raise MosaicError(f"Output already exists: {output_path}; use --overwrite")
    plan = inspect_and_plan(specs, args)
    adjust_tile_size_for_memory(plan, args)
    summary = plan_summary(plan, args)
    LOGGER.info(
        "Output grid: %dx%d x %d bands, %s, %.2f GiB uncompressed, BIGTIFF=%s",
        plan.grid.width,
        plan.grid.height,
        len(plan.selected_bands),
        plan.output_dtype,
        plan.uncompressed_bytes / GIB,
        plan.bigtiff,
    )
    LOGGER.info(
        "Planning grid: %dx%d at 1:%d (%d total source pixels)",
        plan.plan_grid.width,
        plan.plan_grid.height,
        plan.plan_scale,
        sum(
            (i.plan_window[2] * i.plan_window[3]) if i.plan_window else 0
            for i in plan.source_infos
        ),
    )

    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report
        else output_path.with_name(output_path.name + ".analysis.json")
    )
    ensure_artifact_path_is_safe(
        report_path,
        input_local_paths,
        "Analysis report path",
        (output_path, partial_path),
    )
    report = base_report(plan, args)
    report["status"] = "planned"
    write_json(report_path, report)

    if args.dry_run:
        print(json.dumps(summary, indent=2, default=_json_default))
        LOGGER.info("Dry run complete; report written to %s", report_path)
        return 0

    work_parent = Path(args.work_dir).expanduser().resolve() if args.work_dir else output_path.parent
    work_parent.mkdir(parents=True, exist_ok=True)
    if args.keep_work:
        work_dir = work_parent / (output_path.stem + "_mosaic_work")
        work_dir.mkdir(parents=True, exist_ok=True)
        temp_context = None
    else:
        temp_context = tempfile.TemporaryDirectory(prefix="mosaic_", dir=work_parent)
        work_dir = Path(temp_context.name)

    try:
        LOGGER.info("Loading bounded-resolution planning data")
        planning_sources = load_planning_sources(plan, args)
        edges = compute_overlap_edges(planning_sources, plan, args)
        radiometry = solve_global_radiometry(planning_sources, edges, plan, args)
        LOGGER.info("Global radiometric transforms solved")
        labels, seam_report = generate_seam_labels(planning_sources, plan, args)
        seam_path = work_dir / "seam_labels.tif"
        ensure_artifact_path_is_safe(
            seam_path,
            input_local_paths,
            "Planning seam path",
            (output_path, partial_path, report_path),
        )
        if seam_path.exists() and args.keep_work and not args.overwrite:
            raise MosaicError(f"Planning seam file already exists: {seam_path}; use --overwrite")
        write_seam_labels(seam_path, labels, plan)
        LOGGER.info("Seam ownership written to %s", seam_path)

        report["status"] = "analysis_complete"
        report["radiometry"] = radiometry
        report["sources"] = [
            {
                "index": source.info.index,
                "path": source.info.spec.path,
                "percentiles_low": source.info.percentiles_low,
                "percentiles_high": source.info.percentiles_high,
                "gains": source.info.gains,
                "offsets": source.info.offsets,
                "auto_cloud_threshold": source.info.auto_cloud_threshold,
                "valid_fraction": float(source.valid.mean()) if source.valid.size else 0.0,
                "clear_fraction": float(source.clear.mean()) if source.clear.size else 0.0,
            }
            for source in planning_sources
        ]
        report["overlap_edges"] = [serialize_edge(edge) for edge in edges]
        report["seam"] = seam_report
        report["work_seam_labels"] = str(seam_path) if args.keep_work else None
        write_json(report_path, report)

        # Release the largest planning arrays before the full-resolution pass.
        del planning_sources

        if args.analysis_only:
            if not args.keep_work:
                persistent_seam = output_path.with_name(output_path.name + ".seams.tif")
                ensure_artifact_path_is_safe(
                    persistent_seam,
                    input_local_paths,
                    "Persistent seam path",
                    (output_path, partial_path, report_path),
                )
                if persistent_seam.exists() and not args.overwrite:
                    raise MosaicError(
                        f"Persistent seam file already exists: {persistent_seam}; use --overwrite"
                    )
                shutil.copy2(seam_path, persistent_seam)
                report["work_seam_labels"] = str(persistent_seam)
                write_json(report_path, report)
            LOGGER.info("Analysis-only run complete")
            return 0

        result = blend_and_write(plan, labels, output_path, args, report_path)
        report["status"] = "complete"
        report["result"] = result
        report["completed_utc"] = _utc_now()
        write_json(report_path, report)
        LOGGER.info(
            "Mosaic complete: %s (%.2f GiB, %.1f s)",
            output_path,
            result["file_size_bytes"] / GIB,
            result["elapsed_seconds"],
        )
        return 0
    finally:
        if temp_context is not None:
            temp_context.cleanup()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a radiometrically balanced, cloud-aware, graph-cut and feathered "
            "GeoTIFF mosaic using bounded memory."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=PROGRAM_VERSION)
    parser.add_argument("inputs", nargs="*", help="Input GeoTIFFs")
    parser.add_argument("-o", "--output", required=True, help="Output GeoTIFF")
    parser.add_argument("--manifest", help="JSON manifest containing input objects")
    parser.add_argument(
        "--cloud-mask",
        action="append",
        type=parse_cloud_mapping,
        default=[],
        metavar="INPUT=MASK",
        help="Associate a georeferenced nonzero-is-cloud mask with an input",
    )
    parser.add_argument("--crs", help="Target CRS; defaults to the first input CRS")
    parser.add_argument(
        "--resolution",
        nargs="+",
        type=float,
        help="Target pixel size as X or X Y in target CRS units",
    )
    parser.add_argument(
        "--resolution-policy",
        choices=("first", "finest", "coarsest"),
        default="first",
        help="Resolution selection when --resolution is omitted",
    )
    parser.add_argument(
        "--bands",
        type=parse_csv_ints,
        help=(
            "Comma-separated 1-based bands to mosaic; defaults to all non-alpha "
            "bands of the first input"
        ),
    )
    parser.add_argument(
        "--rgb-bands",
        type=parse_csv_ints,
        help="Three source bands used for cloud scoring and seam costs",
    )
    parser.add_argument("--nir-band", type=int, help="Optional NIR source band used by cloud scoring")
    parser.add_argument("--dtype", default="auto", help="Output NumPy/GDAL dtype or 'auto'")
    parser.add_argument(
        "--working-dtype",
        choices=("auto", "float32", "float64"),
        default="auto",
        help="Internal radiometric/blending precision",
    )
    parser.add_argument(
        "--nodata",
        type=parse_nodata,
        default=None,
        help="Output nodata value; an internal validity mask is always written",
    )
    parser.add_argument(
        "--resampling",
        choices=("nearest", "bilinear", "cubic", "lanczos", "average"),
        default="bilinear",
        help="Input reprojection resampling",
    )

    parser.add_argument(
        "--balance",
        choices=("gain-offset", "gain", "offset", "none"),
        default="gain-offset",
        help="Global radiometric model per source and band",
    )
    parser.add_argument("--overlap-samples", type=int, default=20_000)
    parser.add_argument("--min-overlap-samples", type=int, default=200)
    parser.add_argument("--radiometric-regularization", type=float, default=0.02)
    parser.add_argument(
        "--allow-cloudy-radiometry",
        action="store_true",
        help="Allow cloudy pixels when a clear overlap has too few samples",
    )
    parser.add_argument("--min-gain", type=float, default=0.5)
    parser.add_argument("--max-gain", type=float, default=2.0)
    parser.add_argument(
        "--max-offset-ranges",
        type=float,
        default=2.0,
        help="Clamp offsets to this multiple of a typical per-band dynamic range",
    )

    parser.add_argument(
        "--seam-method",
        choices=("graphcut", "voronoi", "none"),
        default="graphcut",
    )
    parser.add_argument("--feather", type=int, default=64, help="Feather half-width in output pixels")
    parser.add_argument(
        "--plan-max-output-pixels",
        type=int,
        default=4_000_000,
        help="Maximum pixels in the global planning output grid",
    )
    parser.add_argument(
        "--plan-max-source-pixels",
        type=int,
        default=12_000_000,
        help="Maximum summed source-window pixels in the planning pass",
    )
    parser.add_argument(
        "--plan-max-memory-mb",
        type=int,
        default=1024,
        help="Approximate planning/seam memory budget",
    )
    parser.add_argument("--edge-cost-weight", type=float, default=1.0)
    parser.add_argument("--priority-cost-weight", type=float, default=0.15)

    parser.add_argument(
        "--auto-cloud",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use a generic brightness/whiteness cloud heuristic",
    )
    parser.add_argument("--cloud-threshold", type=float, default=0.72)
    parser.add_argument(
        "--cloud-dilate",
        type=int,
        default=1,
        help="Cloud-mask dilation radius in output pixels",
    )
    parser.add_argument("--max-auto-cloud-fraction", type=float, default=0.65)
    parser.add_argument("--cloud-cost-weight", type=float, default=4.0)
    parser.add_argument("--cloud-weight-power", type=float, default=2.0)
    parser.add_argument(
        "--all-cloud-policy",
        choices=("least-cloudy", "nodata"),
        default="least-cloudy",
        help="What to do when every covering source is cloudy",
    )

    parser.add_argument("--tile-size", type=int, default=1024, help="Maximum processing window size")
    parser.add_argument(
        "--tile-max-memory-mb",
        type=int,
        default=1024,
        help="Approximate memory budget for a full-resolution processing window",
    )
    parser.add_argument("--block-size", type=int, default=512, help="GeoTIFF internal tile size")
    parser.add_argument(
        "--compression",
        choices=("deflate", "zstd", "lzw", "none"),
        default="deflate",
    )
    parser.add_argument(
        "--compression-level",
        type=int,
        default=6,
        help="DEFLATE level 1-9 or ZSTD level 1-22",
    )
    parser.add_argument("--threads", default="ALL_CPUS", help="GDAL compression/decode threads")
    parser.add_argument("--warp-mem-limit", type=int, default=512, help="Warp memory limit in MB")
    parser.add_argument(
        "--max-open-sources",
        type=int,
        default=64,
        help="Maximum simultaneously open input/VRT pairs",
    )
    parser.add_argument("--percentile-samples", type=int, default=250_000)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument(
        "--overviews",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Build internal average overviews",
    )
    parser.add_argument(
        "--overview-factors",
        type=parse_overviews,
        default=[2, 4, 8, 16, 32],
    )

    parser.add_argument("--dry-run", action="store_true", help="Only inspect and size the output")
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        help="Stop after global radiometry, cloud analysis, and seam generation",
    )
    parser.add_argument("--report", help="Analysis JSON path")
    parser.add_argument("--work-dir", help="Directory for temporary planning files")
    parser.add_argument("--keep-work", action="store_true", help="Keep seam-label planning data")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--strict-disk-check", action="store_true")
    parser.add_argument("--progress-interval", type=float, default=10.0)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.command = ["seamless_mosaic.py", *(list(argv) if argv is not None else sys.argv[1:])]
    # argparse cannot tell whether a default-valued optional was explicitly passed.
    args.nodata_was_set = any(
        token == "--nodata" or token.startswith("--nodata=")
        for token in (list(argv) if argv is not None else sys.argv[1:])
    )
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        return run(args)
    except MosaicError as exc:
        LOGGER.error("%s", exc)
        return 2
    except KeyboardInterrupt:
        LOGGER.error("Interrupted")
        return 130
    except Exception:
        LOGGER.exception("Unexpected failure")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
