# -*- coding: utf-8 -*-
"""ONNX vessel detection service for local georeferenced rasters."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import math
import uuid


_VESSEL_CLASS_KEYWORDS = (
    "vessel",
    "ship",
    "boat",
    "tanker",
    "ferry",
    "cargo",
)


@dataclass
class _ResolvedInputShape:
    width: int
    height: int


class VesselDetectionService:
    """Runs ONNX vessel detection and normalizes detections to plugin payloads."""

    def __init__(self):
        self._class_names = {0: "vessel"}

    def detect(
        self,
        layer_path: str,
        model_path: str,
        conf: float = 0.25,
        iou: float = 0.45,
        max_det: int = 20,
    ) -> list[dict[str, Any]]:
        raster_path = str(layer_path or "").strip()
        model_file = str(model_path or "").strip()
        if not raster_path:
            raise RuntimeError("Vessel detection requires a local raster path.")
        if not model_file:
            raise RuntimeError("Vessel detection requires an ONNX model path.")
        if not Path(model_file).exists():
            raise RuntimeError(f"ONNX model file not found: {model_file}")

        conf_value = max(0.01, min(1.0, float(conf if conf is not None else 0.25)))
        iou_value = max(0.01, min(1.0, float(iou if iou is not None else 0.45)))
        max_det_value = max(1, min(int(max_det if max_det is not None else 20), 500))

        external_runner = self._resolve_external_inference_runner()
        if external_runner is not None:
            return self._detect_with_external_runner(
                runner_python=external_runner["python_path"],
                runner_script=external_runner["script_path"],
                layer_path=raster_path,
                model_path=model_file,
                conf=conf_value,
                iou=iou_value,
                max_det=max_det_value,
            )

        image_rgb = self._read_raster_rgb_uint8(raster_path)
        outputs = self._run_onnx_inference(
            image_rgb=image_rgb,
            model_path=model_file,
            conf=conf_value,
            iou=iou_value,
            max_det=max_det_value,
        )

        height, width = int(image_rgb.shape[0]), int(image_rgb.shape[1])
        rows: list[dict[str, Any]] = []
        for idx, row in enumerate(outputs, start=1):
            class_id = int(row.get("class_id", 0))
            class_name = str(row.get("class_name") or self._class_names.get(class_id, f"class_{class_id}"))
            confidence = float(row.get("confidence", 0.0))
            bbox = row.get("bbox_px") if isinstance(row.get("bbox_px"), list) else [0.0, 0.0, 0.0, 0.0]
            obb = row.get("obb_px") if isinstance(row.get("obb_px"), list) else self._bbox_to_obb(bbox)
            rows.append(
                {
                    "detection_id": f"det_{idx:03d}",
                    "class_id": class_id,
                    "class_name": class_name,
                    "confidence": round(confidence, 6),
                    "bbox_px": [float(v) for v in bbox[:4]],
                    "obb_px": [[float(pair[0]), float(pair[1])] for pair in obb[:4]],
                    "source_width_px": width,
                    "source_height_px": height,
                }
            )
        return rows

    def _resolve_external_inference_runner(self) -> dict[str, str] | None:
        override_script = str(os.getenv("IMAGE_MATE_VESSEL_INFERENCE_SCRIPT", "") or "").strip()
        script_candidates = []
        if override_script:
            script_candidates.append(Path(override_script).expanduser())
        # Bundled runner is always preferred because it ships with the plugin package.
        script_candidates.append(Path(__file__).resolve().parent / "vessel_inference_runner.py")

        script_path = next((path for path in script_candidates if path.exists()), None)
        if script_path is None:
            return None

        python_path = self._resolve_qgis_python_path()
        if python_path is None:
            return None

        return {
            "python_path": str(python_path),
            "script_path": str(script_path),
        }

    @staticmethod
    def _resolve_qgis_python_path() -> Path | None:
        override_python = str(os.getenv("IMAGE_MATE_VESSEL_INFERENCE_PYTHON", "") or "").strip()
        if override_python:
            override_path = Path(override_python).expanduser()
            if override_path.exists():
                return override_path

        candidates: list[Path] = []

        current_exec = Path(str(sys.executable or "")).expanduser()
        if current_exec.exists():
            name = str(current_exec.name or "").strip().lower()
            if "python" in name:
                candidates.append(current_exec)

        if os.name == "nt":
            for raw_prefix in (sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix):
                prefix = str(raw_prefix or "").strip()
                if not prefix:
                    continue
                candidates.append(Path(prefix) / "python.exe")

        try:
            from qgis.core import QgsApplication

            prefix_path = str(QgsApplication.prefixPath() or "").strip()
        except Exception:
            prefix_path = ""
        if prefix_path:
            prefix = Path(prefix_path)
            # Typical structure: <osgeo_root>/apps/qgis
            osgeo_root = prefix.parent.parent if len(prefix.parts) >= 3 else None
            if osgeo_root is not None:
                if os.name == "nt":
                    # Prefer the real CPython install first; fallback to OSGeo wrapper last.
                    candidates.extend(
                        [
                            osgeo_root / "apps" / "Python313" / "python.exe",
                            osgeo_root / "apps" / "Python312" / "python.exe",
                            osgeo_root / "apps" / "Python311" / "python.exe",
                            osgeo_root / "apps" / "Python310" / "python.exe",
                            osgeo_root / "bin" / "python.exe",
                        ]
                    )
                else:
                    candidates.extend(
                        [
                            Path("/usr/bin/python3"),
                            Path("/usr/bin/python"),
                        ]
                    )

        seen: set[str] = set()
        for candidate in candidates:
            try:
                resolved = str(candidate.resolve())
            except Exception:
                resolved = str(candidate)
            key = resolved.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            if candidate.exists():
                return candidate
        return None

    def _detect_with_external_runner(
        self,
        *,
        runner_python: str,
        runner_script: str,
        layer_path: str,
        model_path: str,
        conf: float,
        iou: float,
        max_det: int,
    ) -> list[dict[str, Any]]:
        output_path = Path(tempfile.gettempdir()) / f"image_mate_vessel_detect_{os.getpid()}_{uuid.uuid4().hex}.json"
        if output_path.exists():
            try:
                output_path.unlink()
            except Exception:
                pass
        command = [
            str(runner_python),
            str(runner_script),
            "--layer-path",
            str(layer_path),
            "--model-path",
            str(model_path),
            "--conf",
            f"{float(conf):.6f}",
            "--iou",
            f"{float(iou):.6f}",
            "--max-det",
            str(int(max_det)),
            "--output-json",
            str(output_path),
        ]
        run_env = self._build_runner_env(runner_python=str(runner_python))
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=360,
                env=run_env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "External vessel inference timed out after 360s "
                f"(python={runner_python}, script={runner_script})."
            ) from exc
        if completed.returncode != 0:
            stderr = str(completed.stderr or "").strip()
            stdout = str(completed.stdout or "").strip()
            detail = f"exit_code={completed.returncode} python={runner_python} script={runner_script}"
            path_head = ";".join([part for part in str(run_env.get("PATH") or "").split(os.pathsep)[:5] if part])
            detail = (
                f"{detail} pyhome={str(run_env.get('PYTHONHOME') or '')} "
                f"gdal_data={str(run_env.get('GDAL_DATA') or '')} "
                f"proj_lib={str(run_env.get('PROJ_LIB') or '')} "
                f"path_head={path_head}"
            )
            if stderr:
                detail = f"{detail} stderr={stderr}"
            elif stdout:
                detail = f"{detail} stdout={stdout}"
            raise RuntimeError(f"External vessel inference failed: {detail}")
        if not output_path.exists():
            raise RuntimeError("External vessel inference failed: output JSON file was not created.")
        try:
            parsed = json.loads(output_path.read_text(encoding="utf-8"))
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass
        if not isinstance(parsed, list):
            raise RuntimeError("External vessel inference returned invalid payload.")

        normalized: list[dict[str, Any]] = []
        for idx, row in enumerate(parsed, start=1):
            if not isinstance(row, dict):
                continue
            bbox = row.get("bbox_px") if isinstance(row.get("bbox_px"), list) else [0.0, 0.0, 0.0, 0.0]
            obb = row.get("obb_px") if isinstance(row.get("obb_px"), list) else self._bbox_to_obb(bbox)
            class_id = int(row.get("class_id", 0))
            normalized.append(
                {
                    "detection_id": str(row.get("detection_id") or f"det_{idx:03d}"),
                    "class_id": class_id,
                    "class_name": str(row.get("class_name") or self._class_names.get(class_id, f"class_{class_id}")),
                    "confidence": round(float(row.get("confidence") or 0.0), 6),
                    "bbox_px": [float(v) for v in bbox[:4]],
                    "obb_px": [[float(pair[0]), float(pair[1])] for pair in obb[:4]],
                    "source_width_px": int(row.get("source_width_px") or 0),
                    "source_height_px": int(row.get("source_height_px") or 0),
                }
            )
        return normalized

    @staticmethod
    def _prepend_env_path(env: dict[str, str], key: str, entries: list[Path | str]):
        current = str(env.get(key) or "")
        current_parts = [part for part in current.split(os.pathsep) if part]
        existing = {part.strip().lower() for part in current_parts if part.strip()}
        new_parts: list[str] = []
        for entry in entries:
            raw = str(entry or "").strip()
            if not raw:
                continue
            try:
                path_obj = Path(raw)
                if not path_obj.exists():
                    continue
            except Exception:
                continue
            norm = raw.lower()
            if norm in existing:
                continue
            existing.add(norm)
            new_parts.append(raw)
        env[key] = os.pathsep.join(new_parts + current_parts)

    def _build_runner_env(self, *, runner_python: str) -> dict[str, str]:
        run_env = dict(os.environ)
        runner_path = Path(str(runner_python)).expanduser()
        osgeo_root = self._resolve_osgeo_root_from_python(runner_path)
        python_home = self._resolve_python_home_from_runner(runner_path, osgeo_root)

        if osgeo_root is not None:
            # Ensure native GDAL/PROJ/Qt DLLs are resolvable for child interpreter.
            path_candidates = [
                osgeo_root / "bin",
                osgeo_root / "apps" / "qgis" / "bin",
                osgeo_root / "apps" / "qt6" / "bin",
                osgeo_root / "apps" / "qt5" / "bin",
            ]
            if python_home is not None:
                path_candidates.append(python_home / "Scripts")
            self._prepend_env_path(run_env, "PATH", path_candidates)

            if not str(run_env.get("OSGEO4W_ROOT") or "").strip():
                run_env["OSGEO4W_ROOT"] = str(osgeo_root)

            gdal_data = self._resolve_existing_path(
                [
                    osgeo_root / "apps" / "gdal" / "share" / "gdal",
                    osgeo_root / "share" / "gdal",
                ]
            )
            if gdal_data is not None and not str(run_env.get("GDAL_DATA") or "").strip():
                run_env["GDAL_DATA"] = str(gdal_data)

            proj_lib = self._resolve_existing_path(
                [
                    osgeo_root / "share" / "proj",
                    osgeo_root / "apps" / "proj" / "share" / "proj",
                ]
            )
            if proj_lib is not None and not str(run_env.get("PROJ_LIB") or "").strip():
                run_env["PROJ_LIB"] = str(proj_lib)

        # bin/python.exe wrapper needs explicit PYTHONHOME on some installs.
        if (
            python_home is not None
            and runner_path.name.lower() == "python.exe"
            and runner_path.parent.name.lower() == "bin"
            and not str(run_env.get("PYTHONHOME") or "").strip()
        ):
            run_env["PYTHONHOME"] = str(python_home)

        return run_env

    @staticmethod
    def _resolve_osgeo_root_from_python(runner_path: Path) -> Path | None:
        try:
            resolved = runner_path.resolve()
        except Exception:
            resolved = runner_path
        if os.name != "nt" or not str(resolved).lower().endswith("python.exe"):
            return None

        parent = resolved.parent
        if parent.name.lower() == "bin":
            # ...\OSGeo4W\bin\python.exe
            return parent.parent if parent.parent.exists() else None
        if parent.parent.name.lower() == "apps":
            # ...\OSGeo4W\apps\Python3xx\python.exe
            return parent.parent.parent if parent.parent.parent.exists() else None
        return None

    def _resolve_python_home_from_runner(self, runner_path: Path, osgeo_root: Path | None) -> Path | None:
        if os.name != "nt":
            return None
        try:
            resolved = runner_path.resolve()
        except Exception:
            resolved = runner_path
        if resolved.parent.name.lower().startswith("python3"):
            if (resolved.parent / "Lib").exists():
                return resolved.parent
        if osgeo_root is None:
            return None
        return self._resolve_osgeo_python_home(osgeo_root)

    @staticmethod
    def _resolve_existing_path(candidates: list[Path]) -> Path | None:
        for candidate in candidates:
            try:
                if candidate.exists():
                    return candidate
            except Exception:
                continue
        return None

    @staticmethod
    def _resolve_osgeo_python_home(osgeo_root: Path) -> Path | None:
        if os.name != "nt":
            return None
        for version in ("Python313", "Python312", "Python311", "Python310"):
            candidate = Path(osgeo_root) / "apps" / version
            if (candidate / "python.exe").exists() and (candidate / "Lib").exists():
                return candidate
        return None

    @staticmethod
    def _read_raster_rgb_uint8(raster_path: str):
        try:
            import numpy as np
        except Exception as exc:
            raise RuntimeError(f"NumPy is required for vessel detection: {exc}") from exc

        try:
            from osgeo import gdal
        except Exception as exc:
            raise RuntimeError(f"GDAL Python bindings are unavailable: {exc}") from exc

        ds = gdal.Open(str(raster_path), gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError(f"Could not open raster for detection: {raster_path}")
        try:
            width = int(ds.RasterXSize or 0)
            height = int(ds.RasterYSize or 0)
            bands = int(ds.RasterCount or 0)
            if width <= 0 or height <= 0 or bands <= 0:
                raise RuntimeError("Input raster has invalid size or no bands.")

            band_arrays = []
            pick_count = 3 if bands >= 3 else 1
            for band_idx in range(1, pick_count + 1):
                band = ds.GetRasterBand(band_idx)
                if band is None:
                    continue
                arr = band.ReadAsArray()
                if arr is None:
                    continue
                band_arrays.append(arr)

            if not band_arrays:
                raise RuntimeError("Could not read raster bands for detection.")

            if len(band_arrays) == 1:
                band_arrays = [band_arrays[0], band_arrays[0], band_arrays[0]]

            norm_bands = [VesselDetectionService._normalize_band_uint8(arr, np) for arr in band_arrays[:3]]
            rgb = np.stack(norm_bands, axis=-1)
            return rgb.astype(np.uint8, copy=False)
        finally:
            ds = None

    @staticmethod
    def _normalize_band_uint8(arr, np):
        values = arr.astype(np.float32, copy=False)
        finite = np.isfinite(values)
        if not np.any(finite):
            return np.zeros(values.shape, dtype=np.uint8)
        valid = values[finite]
        low = float(np.percentile(valid, 2.0))
        high = float(np.percentile(valid, 98.0))
        if not math.isfinite(low) or not math.isfinite(high) or high <= low:
            low = float(np.min(valid))
            high = float(np.max(valid))
        if not math.isfinite(low) or not math.isfinite(high) or high <= low:
            out = np.zeros(values.shape, dtype=np.uint8)
            out[finite] = 127
            return out
        scaled = (values - low) / max(1e-6, high - low)
        scaled = np.clip(scaled, 0.0, 1.0)
        return np.rint(scaled * 255.0).astype(np.uint8)

    @staticmethod
    def _normalize_conf_score(value: float) -> float:
        if not math.isfinite(value):
            return 0.0
        if value < 0.0 or value > 1.0:
            return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, value))))
        return value

    @staticmethod
    def _parse_names_metadata(raw_value: Any) -> dict[int, str]:
        if raw_value is None:
            return {}
        parsed = None
        if isinstance(raw_value, dict):
            parsed = raw_value
        else:
            text = str(raw_value or "").strip()
            if not text:
                return {}
            try:
                parsed = ast.literal_eval(text)
            except Exception:
                parsed = None
        if not isinstance(parsed, dict):
            return {}
        out: dict[int, str] = {}
        for raw_key, raw_name in parsed.items():
            try:
                key = int(raw_key)
            except Exception:
                continue
            out[key] = str(raw_name or "").strip()
        return out

    @classmethod
    def _extract_model_metadata(cls, session) -> dict[str, Any]:
        task = ""
        class_names: dict[int, str] = {}
        try:
            meta = session.get_modelmeta()
            custom = dict(getattr(meta, "custom_metadata_map", {}) or {})
            task = str(custom.get("task") or "").strip().lower()
            class_names = cls._parse_names_metadata(custom.get("names"))
        except Exception:
            task = ""
            class_names = {}
        if class_names:
            class_count = max([idx for idx in class_names.keys() if idx >= 0], default=-1) + 1
        else:
            class_count = None
        vessel_class_ids = sorted(
            [
                idx
                for idx, name in class_names.items()
                if any(keyword in str(name or "").strip().lower() for keyword in _VESSEL_CLASS_KEYWORDS)
            ]
        )
        return {
            "task": task,
            "class_names": class_names,
            "class_count": class_count if class_count and class_count > 0 else None,
            "vessel_class_ids": vessel_class_ids,
        }

    @staticmethod
    def _letterbox_image(*, image_rgb, target_w: int, target_h: int, np, Image):
        src_h = int(image_rgb.shape[0])
        src_w = int(image_rgb.shape[1])
        if src_w <= 0 or src_h <= 0:
            raise RuntimeError("Input raster has invalid dimensions for preprocessing.")
        gain = min(float(target_w) / float(src_w), float(target_h) / float(src_h))
        resized_w = max(1, min(int(target_w), int(round(float(src_w) * gain))))
        resized_h = max(1, min(int(target_h), int(round(float(src_h) * gain))))
        resized = Image.fromarray(image_rgb, mode="RGB").resize((resized_w, resized_h))
        canvas = np.full((int(target_h), int(target_w), 3), 114, dtype=np.uint8)
        pad_x = max(0, int((int(target_w) - resized_w) // 2))
        pad_y = max(0, int((int(target_h) - resized_h) // 2))
        canvas[pad_y : pad_y + resized_h, pad_x : pad_x + resized_w] = np.asarray(resized, dtype=np.uint8)
        return canvas, float(gain), float(pad_x), float(pad_y)

    @staticmethod
    def _unletterbox_coord(value: float, *, pad: float, gain: float, max_value: int) -> float:
        raw = (float(value) - float(pad)) / max(1e-6, float(gain))
        return max(0.0, min(float(max_value), raw))

    def _run_onnx_inference(
        self,
        *,
        image_rgb,
        model_path: str,
        conf: float,
        iou: float,
        max_det: int,
    ) -> list[dict[str, Any]]:
        try:
            import numpy as np
        except Exception as exc:
            raise RuntimeError(f"NumPy is required for ONNX inference: {exc}") from exc

        try:
            import onnxruntime as ort
        except Exception as exc:
            raise RuntimeError(f"ONNX Runtime is required for vessel detection: {exc}") from exc

        try:
            from PIL import Image
        except Exception as exc:
            raise RuntimeError(f"Pillow is required for vessel detection preprocessing: {exc}") from exc

        providers = []
        available = set(str(v) for v in ort.get_available_providers())
        use_cuda = str(os.getenv("IMAGE_MATE_VESSEL_USE_CUDA", "") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if use_cuda and "CUDAExecutionProvider" in available:
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")

        session = ort.InferenceSession(str(model_path), providers=providers)
        input_info = session.get_inputs()
        if not input_info:
            raise RuntimeError("ONNX model has no inputs.")
        input_tensor = input_info[0]
        input_name = str(input_tensor.name or "").strip()
        if not input_name:
            raise RuntimeError("ONNX model input name is empty.")
        model_meta = self._extract_model_metadata(session)
        task_hint = str(model_meta.get("task") or "").strip().lower()
        class_names = dict(model_meta.get("class_names") or {})
        class_count = model_meta.get("class_count")
        vessel_class_ids = set(int(v) for v in (model_meta.get("vessel_class_ids") or []))

        resolved = self._resolve_input_shape(input_tensor.shape)
        target_w, target_h = resolved.width, resolved.height
        preprocessed, gain, pad_x, pad_y = self._letterbox_image(
            image_rgb=image_rgb,
            target_w=target_w,
            target_h=target_h,
            np=np,
            Image=Image,
        )
        arr = np.asarray(preprocessed).astype(np.float32) / 255.0
        # Some Windows/OSGeo onnxruntime builds crash on non-contiguous tensors.
        arr = np.ascontiguousarray(np.transpose(arr, (2, 0, 1))[None, :, :, :], dtype=np.float32)

        outputs = session.run(None, {input_name: arr})
        if not outputs:
            return []
        candidates = self._parse_onnx_outputs(
            outputs=outputs,
            input_width=target_w,
            input_height=target_h,
            conf=conf,
            expected_task=task_hint,
            expected_class_count=(int(class_count) if class_count is not None else None),
        )
        if not candidates:
            return []

        orig_h, orig_w = int(image_rgb.shape[0]), int(image_rgb.shape[1])
        if vessel_class_ids:
            candidates = [row for row in candidates if int(row.get("class_id", -1)) in vessel_class_ids]
            if not candidates:
                return []

        projected: list[dict[str, Any]] = []
        for row in candidates:
            x1, y1, x2, y2 = row.get("bbox_px", [0.0, 0.0, 0.0, 0.0])[:4]
            bbox = [
                self._unletterbox_coord(float(x1), pad=pad_x, gain=gain, max_value=orig_w),
                self._unletterbox_coord(float(y1), pad=pad_y, gain=gain, max_value=orig_h),
                self._unletterbox_coord(float(x2), pad=pad_x, gain=gain, max_value=orig_w),
                self._unletterbox_coord(float(y2), pad=pad_y, gain=gain, max_value=orig_h),
            ]
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            obb = row.get("obb_px")
            if isinstance(obb, list) and len(obb) >= 4:
                scaled: list[list[float]] = []
                for pair in obb[:4]:
                    if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                        continue
                    try:
                        ox = self._unletterbox_coord(float(pair[0]), pad=pad_x, gain=gain, max_value=orig_w)
                        oy = self._unletterbox_coord(float(pair[1]), pad=pad_y, gain=gain, max_value=orig_h)
                        scaled.append([ox, oy])
                    except Exception:
                        continue
                row["obb_px"] = scaled if len(scaled) == 4 else self._bbox_to_obb(bbox)
            else:
                row["obb_px"] = self._bbox_to_obb(bbox)
            row["bbox_px"] = bbox
            row["class_name"] = str(class_names.get(int(row.get("class_id", -1))) or row.get("class_name") or "")
            projected.append(row)
        candidates = projected
        if not candidates:
            return []

        pre_nms_limit = max(400, min(4000, int(max_det) * 200))
        if len(candidates) > pre_nms_limit:
            candidates.sort(key=lambda r: float(r.get("confidence", 0.0)), reverse=True)
            candidates = candidates[:pre_nms_limit]

        filtered = self._nms(candidates, iou_threshold=iou)
        filtered.sort(key=lambda r: float(r.get("confidence", 0.0)), reverse=True)
        return filtered[:max_det]

    @staticmethod
    def _resolve_input_shape(shape: list[Any] | tuple[Any, ...]) -> _ResolvedInputShape:
        width = 640
        height = 640
        if isinstance(shape, (list, tuple)) and len(shape) >= 4:
            maybe_h = shape[2]
            maybe_w = shape[3]
            try:
                maybe_h_int = int(maybe_h)
                if maybe_h_int > 0:
                    height = maybe_h_int
            except Exception:
                pass
            try:
                maybe_w_int = int(maybe_w)
                if maybe_w_int > 0:
                    width = maybe_w_int
            except Exception:
                pass
        return _ResolvedInputShape(width=width, height=height)

    def _parse_onnx_outputs(
        self,
        *,
        outputs: list[Any],
        input_width: int,
        input_height: int,
        conf: float,
        expected_task: str = "",
        expected_class_count: int | None = None,
    ):
        try:
            import numpy as np
        except Exception as exc:
            raise RuntimeError(f"NumPy is required for output parsing: {exc}") from exc

        primary = None
        for row in outputs:
            if isinstance(row, np.ndarray) and row.ndim >= 2:
                primary = row
                break
        if primary is None:
            return []

        arr = primary
        if arr.ndim == 3 and int(arr.shape[0]) == 1:
            arr = arr[0]
        if arr.ndim != 2:
            arr = np.reshape(arr, (-1, arr.shape[-1])) if arr.ndim > 2 else np.reshape(arr, (-1, 1))

        # Typical YOLO export format can be [84, N] or [N, 84].
        if arr.shape[0] <= 128 and arr.shape[1] > arr.shape[0]:
            arr = arr.T
        if arr.shape[1] < 6 and arr.shape[0] >= 6:
            arr = arr.T
        if arr.shape[1] < 6:
            return []

        force_obb = str(expected_task or "").strip().lower() == "obb"
        obb_layout = self._select_obb_layout(arr, np, force_obb=force_obb)
        if obb_layout is not None:
            parse_modes: list[bool]
            if expected_class_count is not None:
                non_angle_columns = int(arr.shape[1]) - 5
                if non_angle_columns == int(expected_class_count):
                    parse_modes = [False]
                elif non_angle_columns == int(expected_class_count) + 1:
                    parse_modes = [True]
                else:
                    parse_modes = [False, True]
            else:
                parse_modes = [False, True]
            for use_objectness in parse_modes:
                parsed_rows = self._parse_xywhr_classprob_candidates(
                    arr=arr,
                    input_width=input_width,
                    input_height=input_height,
                    conf=conf,
                    angle_layout=obb_layout,
                    use_objectness=use_objectness,
                    expected_class_count=expected_class_count,
                )
                if parsed_rows:
                    return parsed_rows
            alt_layout = "fifth" if obb_layout == "last" else "last"
            for use_objectness in parse_modes:
                parsed_rows = self._parse_xywhr_classprob_candidates(
                    arr=arr,
                    input_width=input_width,
                    input_height=input_height,
                    conf=conf,
                    angle_layout=alt_layout,
                    use_objectness=use_objectness,
                    expected_class_count=expected_class_count,
                )
                if parsed_rows:
                    return parsed_rows

        parsed_xywh = self._parse_xywh_classprob_candidates(
            arr=arr,
            input_width=input_width,
            input_height=input_height,
            conf=conf,
            expected_class_count=expected_class_count,
        )
        if parsed_xywh:
            return parsed_xywh
        return self._parse_xyxy_score_class_candidates(
            arr=arr,
            input_width=input_width,
            input_height=input_height,
            conf=conf,
            expected_class_count=expected_class_count,
        )

    @staticmethod
    def _parse_xywh_classprob_candidates(
        *,
        arr,
        input_width: int,
        input_height: int,
        conf: float,
        expected_class_count: int | None = None,
    ):
        out: list[dict[str, Any]] = []
        class_count = int(arr.shape[1] - 4)
        if class_count <= 0:
            return out
        for row in arr:
            try:
                cx, cy, w, h = (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
            except Exception:
                continue
            class_scores = row[4:]
            if class_scores.size <= 0:
                continue
            class_id = int(class_scores.argmax())
            if expected_class_count is not None and class_id >= int(expected_class_count):
                continue
            score = VesselDetectionService._normalize_conf_score(float(class_scores[class_id]))
            if score < conf:
                continue
            if max(abs(cx), abs(cy), abs(w), abs(h)) <= 2.0:
                cx *= float(input_width)
                w *= float(input_width)
                cy *= float(input_height)
                h *= float(input_height)
            x1 = cx - (w * 0.5)
            y1 = cy - (h * 0.5)
            x2 = cx + (w * 0.5)
            y2 = cy + (h * 0.5)
            if x2 <= x1 or y2 <= y1:
                continue
            out.append(
                {
                    "class_id": class_id,
                    "confidence": score,
                    "bbox_px": [x1, y1, x2, y2],
                }
            )
        return out

    @staticmethod
    def _xywhr_to_obb(cx: float, cy: float, w: float, h: float, angle_rad: float) -> list[list[float]]:
        hw = float(w) * 0.5
        hh = float(h) * 0.5
        ca = math.cos(float(angle_rad))
        sa = math.sin(float(angle_rad))
        corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
        out: list[list[float]] = []
        for dx, dy in corners:
            x = float(cx) + (dx * ca) - (dy * sa)
            y = float(cy) + (dx * sa) + (dy * ca)
            out.append([x, y])
        return out

    @staticmethod
    def _parse_xywhr_classprob_candidates(
        *,
        arr,
        input_width: int,
        input_height: int,
        conf: float,
        angle_layout: str,
        use_objectness: bool = False,
        expected_class_count: int | None = None,
    ):
        out: list[dict[str, Any]] = []
        class_count = int(arr.shape[1] - 5)
        if class_count <= 0:
            return out
        for row in arr:
            try:
                cx, cy, w, h = (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
            except Exception:
                continue
            if angle_layout == "last":
                try:
                    angle = float(row[-1])
                except Exception:
                    continue
                tail = row[4:-1]
            else:
                try:
                    angle = float(row[4])
                except Exception:
                    continue
                tail = row[5:]
            if tail.size <= 0:
                continue
            obj_score = 1.0
            class_scores = tail
            if use_objectness:
                if tail.size <= 1:
                    continue
                obj_score = VesselDetectionService._normalize_conf_score(float(tail[0]))
                class_scores = tail[1:]
                if obj_score <= 0.0:
                    continue
            if class_scores.size <= 0:
                continue
            class_id = int(class_scores.argmax())
            if expected_class_count is not None and class_id >= int(expected_class_count):
                continue
            cls_score = VesselDetectionService._normalize_conf_score(float(class_scores[class_id]))
            score = float(cls_score) * float(obj_score)
            if score < conf:
                continue
            if max(abs(cx), abs(cy), abs(w), abs(h)) <= 2.0:
                cx *= float(input_width)
                w *= float(input_width)
                cy *= float(input_height)
                h *= float(input_height)
            if w <= 1e-6 or h <= 1e-6:
                continue
            x1 = cx - (w * 0.5)
            y1 = cy - (h * 0.5)
            x2 = cx + (w * 0.5)
            y2 = cy + (h * 0.5)
            if x2 <= x1 or y2 <= y1:
                continue
            out.append(
                {
                    "class_id": class_id,
                    "confidence": score,
                    "bbox_px": [x1, y1, x2, y2],
                    "obb_px": VesselDetectionService._xywhr_to_obb(cx, cy, w, h, angle),
                }
            )
        return out

    @staticmethod
    def _sample_out_of_unit_ratio(col, np) -> float:
        if col.size > 2048:
            step = max(1, int(col.size // 2048))
            col = col[::step]
        finite = col[np.isfinite(col)]
        if finite.size <= 0:
            return 0.0
        return float(np.mean((finite < -0.05) | (finite > 1.05)))

    @staticmethod
    def _select_obb_layout(arr, np, *, force_obb: bool = False) -> str | None:
        if arr.shape[1] < 7 or arr.shape[1] > 50:
            return None
        col4_ratio = VesselDetectionService._sample_out_of_unit_ratio(arr[:, 4], np)
        col_last_ratio = VesselDetectionService._sample_out_of_unit_ratio(arr[:, -1], np)
        if col_last_ratio >= col4_ratio + 0.01:
            return "last"
        if col4_ratio >= col_last_ratio + 0.01:
            return "fifth"
        # Prefer Ultralytics OBB export layout when both columns look similar or ambiguous.
        if force_obb:
            return "last"
        return "last"

    @staticmethod
    def _parse_xyxy_score_class_candidates(
        *,
        arr,
        input_width: int,
        input_height: int,
        conf: float,
        expected_class_count: int | None = None,
    ):
        out: list[dict[str, Any]] = []
        for row in arr:
            if len(row) < 6:
                continue
            try:
                x1, y1, x2, y2 = (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
                score = VesselDetectionService._normalize_conf_score(float(row[4]))
                class_id = int(round(float(row[5])))
            except Exception:
                continue
            if expected_class_count is not None and class_id >= int(expected_class_count):
                continue
            if score < conf:
                continue
            if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 2.0:
                x1 *= float(input_width)
                x2 *= float(input_width)
                y1 *= float(input_height)
                y2 *= float(input_height)
            if x2 <= x1 or y2 <= y1:
                continue
            out.append(
                {
                    "class_id": class_id,
                    "confidence": score,
                    "bbox_px": [x1, y1, x2, y2],
                }
            )
        return out

    @staticmethod
    def _bbox_iou(left: list[float], right: list[float]) -> float:
        lx1, ly1, lx2, ly2 = left
        rx1, ry1, rx2, ry2 = right
        ix1 = max(lx1, rx1)
        iy1 = max(ly1, ry1)
        ix2 = min(lx2, rx2)
        iy2 = min(ly2, ry2)
        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        inter = iw * ih
        left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
        right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
        union = left_area + right_area - inter
        if union <= 0:
            return 0.0
        return inter / union

    @classmethod
    def _nms(cls, rows: list[dict[str, Any]], *, iou_threshold: float) -> list[dict[str, Any]]:
        ordered = sorted(rows, key=lambda r: float(r.get("confidence", 0.0)), reverse=True)
        kept: list[dict[str, Any]] = []
        for row in ordered:
            bbox = row.get("bbox_px")
            if not isinstance(bbox, list) or len(bbox) < 4:
                continue
            should_keep = True
            for selected in kept:
                selected_bbox = selected.get("bbox_px")
                if not isinstance(selected_bbox, list) or len(selected_bbox) < 4:
                    continue
                if cls._bbox_iou(bbox[:4], selected_bbox[:4]) > iou_threshold:
                    should_keep = False
                    break
            if should_keep:
                kept.append(row)
        return kept

    @staticmethod
    def _bbox_to_obb(bbox: list[float]) -> list[list[float]]:
        if not isinstance(bbox, list) or len(bbox) < 4:
            return [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
        x1, y1, x2, y2 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
