#!/usr/bin/env python3
"""Run a queued Mosaic Workbench job on the host machine.

The API owns archive authentication and job state.  This process owns the
resource-heavy local work: downloading the selected visual assets through the
identity-based worker endpoint, optionally clipping them to the operator AOI,
and invoking the vendored color-balanced seamless mosaicker.  Run it from the
macOS host so the worker can use the host's geospatial libraries and future
Metal/MPS acceleration without putting those dependencies in Hermes Docker.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import settings  # noqa: E402


LOGGER = logging.getLogger("image_mate.mosaic_worker")


class WorkerError(RuntimeError):
    pass


def _json_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    detail = payload.get("detail") if isinstance(payload, dict) else payload
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)[:1000]
    return str(detail or payload)[:1000]


def _api_json(session: requests.Session, base_url: str, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = session.request(method, f"{base_url.rstrip('/')}{path}", timeout=kwargs.pop("timeout", 60), **kwargs)
    if not response.ok:
        raise WorkerError(f"API {method} {path} failed ({response.status_code}): {_json_error(response)}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise WorkerError(f"API {method} {path} returned non-JSON data") from exc
    return payload if isinstance(payload, dict) else {"result": payload}


def _safe_name(value: str, fallback: str = "item") -> str:
    token = "".join(char if char.isalnum() or char in "._-" else "_" for char in str(value))
    return token.strip("._")[:120] or fallback


def _download_input(
    session: requests.Session,
    base_url: str,
    job_id: str,
    item_id: str,
    asset_key: str,
    destination: Path,
    *,
    timeout: int,
) -> int:
    response = session.get(
        f"{base_url.rstrip('/')}/api/mosaics/jobs/{job_id}/input",
        params={"item_id": item_id, "asset_key": asset_key},
        stream=True,
        timeout=timeout,
    )
    if not response.ok:
        if asset_key == "cloud_mask" and response.status_code == 404:
            return 0
        raise WorkerError(f"Could not download {asset_key} for {item_id}: {_json_error(response)}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > int(settings.mosaic_max_input_bytes):
                    raise WorkerError(f"Downloaded {item_id} exceeds IMAGE_MATE_MOSAIC_MAX_INPUT_BYTES")
                handle.write(chunk)
    finally:
        response.close()
    if total == 0:
        raise WorkerError(f"Downloaded {asset_key} for {item_id} was empty")
    return total


def _clip_raster_to_aoi(source_path: Path, aoi: dict[str, Any], destination: Path) -> None:
    """Clip a georeferenced raster to a WGS84 AOI before mosaicking."""

    try:
        import rasterio
        from rasterio.mask import mask
        from rasterio.warp import transform_geom
    except Exception as exc:  # pragma: no cover - exercised in host environments
        raise WorkerError(
            "Polygon mosaics require rasterio in the host worker environment; "
            "install backend/requirements-mosaic.txt"
        ) from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(source_path) as source:
        if source.crs is None:
            raise WorkerError(f"Raster has no CRS and cannot be clipped: {source_path.name}")
        geometry = transform_geom("EPSG:4326", source.crs, aoi, precision=8)
        try:
            data, transform = mask(source, [geometry], crop=True, filled=True)
        except ValueError as exc:
            raise WorkerError(f"Mosaic AOI does not intersect {source_path.name}") from exc
        profile = source.profile.copy()
        # Do not carry JPEG/YCBCR source photometry into a DEFLATE-compressed
        # intermediate. GDAL rejects that combination even though the clipped
        # pixel data itself is valid.
        profile.pop("photometric", None)
        profile.pop("jpeg_quality", None)
        profile.update(
            height=data.shape[1],
            width=data.shape[2],
            transform=transform,
            compress="deflate",
            predictor=2,
        )
        with rasterio.open(destination, "w", **profile) as target:
            target.write(data)


def _prepare_inputs(
    session: requests.Session,
    base_url: str,
    job_id: str,
    payload: dict[str, Any],
    work_dir: Path,
    *,
    timeout: int,
) -> tuple[Path, list[dict[str, Any]]]:
    aoi = payload.get("aoi") if payload.get("mode") == "polygon" else None
    manifest_inputs: list[dict[str, Any]] = []
    input_dir = work_dir / "inputs"
    for index, row in enumerate(payload.get("inputs") or []):
        if not isinstance(row, dict):
            raise WorkerError(f"Mosaic input {index} is not an object")
        item_id = str(row.get("item_id") or "").strip()
        if not item_id:
            raise WorkerError(f"Mosaic input {index} has no item_id")
        stem = f"{index:03d}_{_safe_name(item_id)}"
        downloaded = input_dir / f"{stem}.tif"
        size = _download_input(session, base_url, job_id, item_id, "visual", downloaded, timeout=timeout)
        LOGGER.info("downloaded item=%s bytes=%s", item_id, size)
        source_path = downloaded
        cloud_mask_path = input_dir / f"{stem}_cloud_mask.tif"
        cloud_size = _download_input(session, base_url, job_id, item_id, "cloud_mask", cloud_mask_path, timeout=timeout)
        if aoi:
            clipped = input_dir / f"{stem}_aoi.tif"
            _clip_raster_to_aoi(source_path, aoi, clipped)
            source_path = clipped
            if cloud_size:
                clipped_mask = input_dir / f"{stem}_cloud_mask_aoi.tif"
                _clip_raster_to_aoi(cloud_mask_path, aoi, clipped_mask)
                cloud_mask_path = clipped_mask
        entry: dict[str, Any] = {"path": str(source_path), "name": item_id}
        if cloud_size:
            entry["cloud_mask"] = str(cloud_mask_path)
        manifest_inputs.append(entry)

    if len(manifest_inputs) < 2:
        raise WorkerError("A mosaic worker requires at least two downloaded inputs")
    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"inputs": manifest_inputs}, indent=2) + "\n", encoding="utf-8")
    return manifest_path, manifest_inputs


def _run_engine(
    job: dict[str, Any],
    manifest_path: Path,
    output_path: Path,
    report_path: Path,
    *,
    accelerator_override: str | None = None,
) -> dict[str, Any]:
    try:
        from qgis_plugin.image_mate_qgis_plugin.vendor.mosaicker import main as mosaicker_main
    except Exception as exc:  # pragma: no cover - depends on host-only geospatial packages
        raise WorkerError(
            "The host mosaicker dependencies are not installed. "
            "Install backend/requirements-mosaic.txt, then rerun the worker."
        ) from exc

    preflight = job.get("preflight") if isinstance(job.get("preflight"), dict) else {}
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    resolution = float(preflight.get("output_resolution_m") or 1.0)
    accelerator = str(accelerator_override or payload.get("accelerator") or "auto").strip().lower()
    if accelerator not in {"auto", "cpu", "mps", "cuda", "opencl"}:
        accelerator = "auto"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "--manifest", str(manifest_path),
        "--output", str(output_path),
        "--report", str(report_path),
        "--crs", "EPSG:3857",
        "--resolution", str(resolution),
        "--resolution-policy", "coarsest",
        "--accelerator", accelerator,
        "--overwrite",
        "--progress-interval", "0",
        "--log-level", "INFO",
    ]
    code = int(mosaicker_main(args))
    if code != 0:
        raise WorkerError(f"Mosaicker exited with status {code}; inspect {report_path}")
    result = {}
    if report_path.is_file():
        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
            result = parsed.get("result") if isinstance(parsed, dict) and isinstance(parsed.get("result"), dict) else {}
            report_settings = parsed.get("settings") if isinstance(parsed, dict) and isinstance(parsed.get("settings"), dict) else {}
            if isinstance(report_settings.get("accelerator"), dict):
                result["accelerator"] = report_settings["accelerator"]
        except (OSError, json.JSONDecodeError):
            result = {}
    result.update({"output_path": str(output_path), "report_path": str(report_path), "engine": "seamless_mosaic", "accelerator_requested": accelerator})
    return result


def _progress(session: requests.Session, base_url: str, job_id: str, *, status: str, progress: float, message: str, error: str = "", result: dict[str, Any] | None = None) -> None:
    _api_json(
        session,
        base_url,
        "POST",
        f"/api/mosaics/jobs/{job_id}/progress",
        json={"status": status, "progress": progress, "message": message, "error": error, "result": result},
    )


def run_job(
    base_url: str,
    job_id: str,
    *,
    work_root: Path | None,
    timeout: int,
    keep_work: bool,
    accelerator_override: str | None = None,
) -> int:
    session = requests.Session()
    try:
        claimed = _api_json(session, base_url, "POST", f"/api/mosaics/jobs/{job_id}/claim")
        job = claimed.get("job") if isinstance(claimed.get("job"), dict) else None
        if not job:
            raise WorkerError("Claim response did not include a job")
        work_dir = (work_root or (settings.output_dir / "mosaic-worker")) / _safe_name(job_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        _progress(session, base_url, job_id, status="running", progress=5, message="Preparing host mosaic worker")
        manifest_path, _ = _prepare_inputs(session, base_url, job_id, job.get("payload") or {}, work_dir, timeout=timeout)
        _progress(session, base_url, job_id, status="running", progress=50, message="Inputs downloaded; running radiometric mosaic")
        output_path = work_dir / "mosaic.tif"
        report_path = work_dir / "mosaic_report.json"
        result = _run_engine(
            job,
            manifest_path,
            output_path,
            report_path,
            accelerator_override=accelerator_override,
        )
        result["manifest_path"] = str(manifest_path)
        result["worker_host"] = str(Path.cwd())
        _progress(session, base_url, job_id, status="succeeded", progress=100, message="Mosaic complete", result=result)
        LOGGER.info("mosaic job succeeded job_id=%s output=%s", job_id, output_path)
        if not keep_work:
            shutil.rmtree(work_dir / "inputs", ignore_errors=True)
            LOGGER.info("removed downloaded source inputs; retained output artifacts in %s", work_dir)
        return 0
    except Exception as exc:
        message = str(exc)[:4000]
        LOGGER.error("mosaic job failed job_id=%s error=%s", job_id, message)
        try:
            _progress(session, base_url, job_id, status="failed", progress=100, message="Mosaic worker failed", error=message)
        except Exception:
            LOGGER.exception("could not report worker failure")
        return 2
    finally:
        session.close()


def _next_job(session: requests.Session, base_url: str) -> str | None:
    payload = _api_json(session, base_url, "GET", "/api/mosaics/jobs?limit=50")
    for job in payload.get("jobs") or []:
        if isinstance(job, dict) and job.get("status") == "queued" and job.get("job_id"):
            return str(job["job_id"])
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Image-Mate Mosaic Workbench jobs on the host")
    parser.add_argument("--api", default=f"http://{settings.host}:{settings.port}", help="Image-Mate API base URL")
    parser.add_argument("--job-id", help="Run one specific queued job")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--once", action="store_true", help="Exit when no queued job is available")
    parser.add_argument("--workdir", type=Path, help="Host directory for downloaded inputs and outputs")
    parser.add_argument("--timeout", type=int, default=900, help="Per-input API download timeout in seconds")
    parser.add_argument("--keep-work", action="store_true", help="Keep downloaded source inputs after completion")
    parser.add_argument("--accelerator", choices=("auto", "cpu", "mps", "cuda", "opencl"), default=None, help="Override the job accelerator")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    base_url = str(args.api).rstrip("/")
    if args.job_id:
        return run_job(
            base_url,
            str(args.job_id),
            work_root=args.workdir,
            timeout=args.timeout,
            keep_work=args.keep_work,
            accelerator_override=args.accelerator,
        )

    session = requests.Session()
    try:
        while True:
            job_id = _next_job(session, base_url)
            if job_id:
                return run_job(
                    base_url,
                    job_id,
                    work_root=args.workdir,
                    timeout=args.timeout,
                    keep_work=args.keep_work,
                    accelerator_override=args.accelerator,
                )
            if args.once:
                LOGGER.info("no queued mosaic jobs")
                return 0
            time.sleep(max(0.5, float(args.poll_seconds)))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        LOGGER.error("mosaic worker stopped: %s", exc)
        return 2
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
