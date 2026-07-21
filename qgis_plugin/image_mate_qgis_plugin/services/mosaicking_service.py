# -*- coding: utf-8 -*-
"""Backend adapter for the vendored seamless GeoTIFF mosaicker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import platform
from queue import Empty, SimpleQueue
import re
import threading
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


class MosaickingLogBuffer:
    """Thread-safe worker-to-GUI text bridge drained by the GUI event loop."""

    def __init__(self) -> None:
        self._messages = SimpleQueue()

    def publish(self, message: str) -> None:
        text = str(message or "").strip()
        if text:
            self._messages.put(text)

    def drain(self, callback: Callable[[str], None]) -> int:
        delivered = 0
        while True:
            try:
                message = self._messages.get_nowait()
            except Empty:
                return delivered
            callback(message)
            delivered += 1


_PLANNING_SOURCE_RE = re.compile(r"Planning source\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
_FULL_PASS_RE = re.compile(
    r"Full-resolution pass:\s*\d+\s*/\s*\d+\s+tiles\s*\(([0-9.]+)%\)",
    re.IGNORECASE,
)


def mosaicking_progress_from_log(message: str) -> Optional[float]:
    """Map stable Mosaicker_v2 log phases to a coarse 0-100 percentage."""

    text = str(message or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if "mosaic complete:" in lowered:
        return 100.0
    if "building internal overviews" in lowered:
        return 95.0
    full_pass = _FULL_PASS_RE.search(text)
    if full_pass:
        tile_percent = min(100.0, max(0.0, float(full_pass.group(1))))
        return 30.0 + (tile_percent * 0.60)
    if "seam ownership written" in lowered:
        return 30.0
    if "global radiometric transforms solved" in lowered:
        return 25.0
    if "usable overlap relationships" in lowered:
        return 22.0
    planning_source = _PLANNING_SOURCE_RE.search(text)
    if planning_source:
        current = max(0, int(planning_source.group(1)))
        total = max(1, int(planning_source.group(2)))
        return 5.0 + (15.0 * min(current, total) / total)
    if "loading bounded-resolution planning data" in lowered:
        return 5.0
    if "planning grid:" in lowered:
        return 4.0
    if "output grid:" in lowered:
        return 2.0
    return None


class _MosaickingCallbackHandler(logging.Handler):
    def __init__(self, *, log_callback=None, progress_callback=None):
        super().__init__(level=logging.INFO)
        self._log_callback = log_callback
        self._progress_callback = progress_callback

    def emit(self, record):
        try:
            message = record.getMessage()
            if self._log_callback is not None:
                self._log_callback(message)
            progress = mosaicking_progress_from_log(message)
            if progress is not None and self._progress_callback is not None:
                self._progress_callback(progress)
        except Exception:
            self.handleError(record)


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
        progress_callback: Optional[Callable[[float], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        debug_callback: Optional[Callable[[str], None]] = None,
    ) -> dict:
        last_progress = -1.0

        def _emit_progress(value):
            nonlocal last_progress
            progress = min(100.0, max(0.0, float(value)))
            if progress <= last_progress:
                return
            last_progress = progress
            if progress_callback is not None:
                progress_callback(progress)

        def _emit_log(message):
            if log_callback is not None:
                log_callback(str(message or "").strip())

        def _emit_debug(message):
            if debug_callback is not None:
                debug_callback(f"DEBUG: {str(message or '').strip()}")

        _emit_debug(
            f"Service entered on thread={threading.current_thread().name}; "
            f"Python={platform.python_version()}."
        )
        _emit_debug("Normalizing and revalidating mosaic paths.")
        request = normalize_mosaicking_request(
            input_paths=input_paths,
            output_path=output_path,
            overwrite=overwrite,
        )
        _emit_debug(
            f"Request normalized: inputs={len(request.input_paths)}; "
            f"output={request.output_path}; overwrite={request.overwrite}."
        )
        if self._runner is None:
            _emit_debug("Loading the vendored Mosaicker_v2 engine and optional dependencies.")
            runner = self._load_default_runner()
            _emit_debug("Vendored Mosaicker_v2 engine loaded successfully.")
        else:
            runner = self._runner
            _emit_debug("Using the injected mosaicker runner.")

        argv = [
            *(str(path) for path in request.input_paths),
            "--output",
            str(request.output_path),
            "--progress-interval",
            "10",
        ]
        if request.overwrite:
            argv.append("--overwrite")

        engine_logger = logging.getLogger("seamless_mosaic")
        original_logger_level = engine_logger.level
        callback_handler = _MosaickingCallbackHandler(
            log_callback=_emit_log,
            progress_callback=_emit_progress,
        )
        if not engine_logger.isEnabledFor(logging.INFO):
            engine_logger.setLevel(logging.INFO)
        engine_logger.addHandler(callback_handler)
        _emit_progress(0.0)
        _emit_log(f"Starting Mosaicker_v2 with {len(request.input_paths)} input raster(s).")
        _emit_debug("Invoking the mosaicker runner; the next messages come from the engine.")
        started_at = time.monotonic()
        try:
            exit_code = runner(argv)
        except Exception as exc:
            _emit_debug(
                f"Mosaicker runner raised {type(exc).__name__}: {exc}"
            )
            raise
        finally:
            engine_logger.removeHandler(callback_handler)
            callback_handler.close()
            engine_logger.setLevel(original_logger_level)
        elapsed_seconds = max(0.0, time.monotonic() - started_at)
        _emit_debug(
            f"Mosaicker runner returned exit_code={exit_code!r} after "
            f"{elapsed_seconds:.3f} seconds."
        )
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
        _emit_debug(
            f"Output verification passed; analysis_report_exists={report_path.exists()}."
        )
        _emit_progress(100.0)
        _emit_log(f"Mosaic output verified: {request.output_path}")
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
