# -*- coding: utf-8 -*-
"""Backend adapter for the vendored seamless GeoTIFF mosaicker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable, Optional, Sequence, Union


MOSAICKER_DEPENDENCIES = (
    "numpy",
    "rasterio",
    "scipy",
    "cv2",
    "shapely",
    "affine",
)


class MosaickingDependencyError(RuntimeError):
    """Raised when the QGIS Python runtime cannot import the vendored engine."""


@dataclass(frozen=True)
class MosaickingRequest:
    input_paths: tuple[Path, ...]
    output_path: Path
    overwrite: bool = False


def normalize_mosaicking_request(
    *,
    input_paths: Sequence[Union[str, Path]],
    output_path: Union[str, Path],
    overwrite: bool = False,
) -> MosaickingRequest:
    """Validate and normalize the MVP's filesystem request contract."""

    normalized_inputs: list[Path] = []
    seen_inputs: set[str] = set()
    for value in input_paths or ():
        text = str(value or "").strip()
        if not text:
            continue
        path = Path(text).expanduser().resolve()
        key = str(path).casefold()
        if key in seen_inputs:
            continue
        if not path.exists():
            raise ValueError(f"Mosaic input does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Mosaic input is not a file: {path}")
        normalized_inputs.append(path)
        seen_inputs.add(key)

    if len(normalized_inputs) < 2:
        raise ValueError("Select at least two distinct local raster inputs.")

    output_text = str(output_path or "").strip()
    if not output_text:
        raise ValueError("Choose an output GeoTIFF path.")
    output = Path(output_text).expanduser().resolve()
    if output.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("Mosaic output must use a .tif or .tiff extension.")
    if str(output).casefold() in seen_inputs:
        raise ValueError("Mosaic output cannot replace one of its input rasters.")
    if output.exists() and not bool(overwrite):
        raise FileExistsError(
            f"Mosaic output already exists; enable overwrite or choose another path: {output}"
        )
    if output.exists() and not output.is_file():
        raise ValueError(f"Mosaic output path is not a file: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    return MosaickingRequest(
        input_paths=tuple(normalized_inputs),
        output_path=output,
        overwrite=bool(overwrite),
    )


class MosaickingService:
    """Translate a QGIS studio request to the unchanged Mosaicker_v2 CLI API."""

    def __init__(self, *, runner: Optional[Callable[[Sequence[str]], int]] = None) -> None:
        self._runner = runner

    def create_mosaic(
        self,
        *,
        input_paths: Sequence[Union[str, Path]],
        output_path: Union[str, Path],
        overwrite: bool = False,
    ) -> dict:
        request = normalize_mosaicking_request(
            input_paths=input_paths,
            output_path=output_path,
            overwrite=overwrite,
        )
        runner = self._runner or self._load_default_runner()
        argv = [
            *(str(path) for path in request.input_paths),
            "--output",
            str(request.output_path),
            "--progress-interval",
            "10",
        ]
        if request.overwrite:
            argv.append("--overwrite")

        started_at = time.monotonic()
        exit_code = runner(argv)
        elapsed_seconds = max(0.0, time.monotonic() - started_at)
        if exit_code not in (None, 0):
            missing_inputs = [path for path in request.input_paths if not path.exists()]
            if missing_inputs:
                missing_text = ", ".join(str(path) for path in missing_inputs)
                raise RuntimeError(
                    "Mosaicker_v2 stopped because input file(s) became unavailable during "
                    f"processing: {missing_text}"
                )
            raise RuntimeError(f"Mosaicker_v2 exited with code {exit_code}.")
        if not request.output_path.exists() or not request.output_path.is_file():
            raise RuntimeError(
                f"Mosaicker_v2 completed without creating the output: {request.output_path}"
            )

        report_path = request.output_path.with_name(request.output_path.name + ".analysis.json")
        return {
            "output_path": str(request.output_path),
            "analysis_path": str(report_path) if report_path.exists() else "",
            "input_count": len(request.input_paths),
            "elapsed_seconds": elapsed_seconds,
        }

    @staticmethod
    def _load_default_runner() -> Callable[[Sequence[str]], int]:
        try:
            from ..vendor.mosaicker.seamless_mosaic import main
        except Exception as exc:
            dependency_list = ", ".join(MOSAICKER_DEPENDENCIES)
            raise MosaickingDependencyError(
                "Mosaicking Studio requires Python 3.10 or newer and could not load its "
                "processing engine. Install the "
                f"following packages into the QGIS Python environment: {dependency_list}. "
                f"Import error: {exc}"
            ) from exc
        return main
