"""Local aircraft detection for one high-resolution image tile.

The service is intentionally independent of provider analytics.  It consumes image
bytes plus optional tile provenance and runs an ONNX detector locally.  The default
artifact in image-mate is the existing YOLO11n-OBB model trained on DOTAv1.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
import threading
import time
from typing import Any

from PIL import Image, ImageOps


AIRCRAFT_NAME_TOKENS = ("aircraft", "airplane", "plane", "helicopter")
SUPPORTED_GEO_TILE_MATRIX_SETS = {"webmercatorquad", "epsg:3857", "web-mercator"}


class AircraftDetectorError(RuntimeError):
    """Base error for actionable local-detector failures."""


class AircraftDetectorUnavailable(AircraftDetectorError):
    """Raised when the model or ONNX Runtime is unavailable."""


@dataclass(frozen=True)
class AircraftDetectorConfig:
    model_path: Path
    provider_mode: str = "auto"
    confidence: float = 0.25
    iou: float = 0.45
    max_detections: int = 200
    window_size_px: int = 1024
    window_overlap: float = 0.20
    max_image_bytes: int = 16 * 1024 * 1024
    max_image_pixels: int = 4096 * 4096
    aircraft_classes: tuple[str, ...] = ("plane", "airplane", "aircraft", "helicopter")


def _normalize_confidence(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    if 0.0 <= value <= 1.0:
        return float(value)
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, float(value)))))


def _parse_names(raw_value: Any) -> dict[int, str]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        parsed = raw_value
    else:
        text = str(raw_value or "").strip()
        if not text:
            return {}
        try:
            parsed = ast.literal_eval(text)
        except Exception:
            return {}
    if not isinstance(parsed, dict):
        return {}
    names: dict[int, str] = {}
    for raw_key, raw_name in parsed.items():
        try:
            names[int(raw_key)] = str(raw_name or "").strip()
        except (TypeError, ValueError):
            continue
    return names


def _resolve_input_shape(shape: Any, fallback: int = 1024) -> tuple[int, int]:
    width = height = int(fallback)
    if isinstance(shape, (list, tuple)) and len(shape) >= 4:
        try:
            candidate_h = int(shape[2])
            if candidate_h > 0:
                height = candidate_h
        except (TypeError, ValueError):
            pass
        try:
            candidate_w = int(shape[3])
            if candidate_w > 0:
                width = candidate_w
        except (TypeError, ValueError):
            pass
    return max(32, width), max(32, height)


def _letterbox(image: Image.Image, target_width: int, target_height: int, np):
    src_width, src_height = image.size
    if src_width <= 0 or src_height <= 0:
        raise AircraftDetectorError("Input tile has invalid dimensions.")
    gain = min(target_width / src_width, target_height / src_height)
    resized_width = max(1, min(target_width, round(src_width * gain)))
    resized_height = max(1, min(target_height, round(src_height * gain)))
    resized = image.resize((resized_width, resized_height), Image.Resampling.BILINEAR)
    canvas = np.full((target_height, target_width, 3), 114, dtype=np.uint8)
    pad_x = (target_width - resized_width) // 2
    pad_y = (target_height - resized_height) // 2
    canvas[pad_y : pad_y + resized_height, pad_x : pad_x + resized_width] = np.asarray(resized, dtype=np.uint8)
    return canvas, float(gain), float(pad_x), float(pad_y)


def _unletterbox(value: float, pad: float, gain: float, maximum: int) -> float:
    return max(0.0, min(float(maximum), (float(value) - pad) / max(gain, 1e-6)))


def _xywhr_to_obb(cx: float, cy: float, width: float, height: float, angle: float) -> list[list[float]]:
    half_width = width * 0.5
    half_height = height * 0.5
    cosine = math.cos(angle)
    sine = math.sin(angle)
    corners = [(-half_width, -half_height), (half_width, -half_height), (half_width, half_height), (-half_width, half_height)]
    return [
        [cx + dx * cosine - dy * sine, cy + dx * sine + dy * cosine]
        for dx, dy in corners
    ]


def _bbox_from_points(points: list[list[float]]) -> list[float]:
    if not points:
        return [0.0, 0.0, 0.0, 0.0]
    xs = [float(point[0]) for point in points if len(point) >= 2]
    ys = [float(point[1]) for point in points if len(point) >= 2]
    if not xs or not ys:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bbox_iou(left: list[float], right: list[float]) -> float:
    ix1 = max(float(left[0]), float(right[0]))
    iy1 = max(float(left[1]), float(right[1]))
    ix2 = min(float(left[2]), float(right[2]))
    iy2 = min(float(left[3]), float(right[3]))
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    left_area = max(0.0, float(left[2]) - float(left[0])) * max(0.0, float(left[3]) - float(left[1]))
    right_area = max(0.0, float(right[2]) - float(right[0])) * max(0.0, float(right[3]) - float(right[1]))
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _class_aware_nms(rows: list[dict[str, Any]], iou_threshold: float) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: float(row.get("confidence", 0.0)), reverse=True)
    kept: list[dict[str, Any]] = []
    for row in ordered:
        bbox = row.get("bbox_px")
        if not isinstance(bbox, list) or len(bbox) < 4:
            continue
        class_id = row.get("class_id")
        if any(
            selected.get("class_id") == class_id
            and _bbox_iou(bbox[:4], selected.get("bbox_px", [0, 0, 0, 0])[:4]) > iou_threshold
            for selected in kept
        ):
            continue
        kept.append(row)
    return kept


def _sample_out_of_unit_ratio(column, np) -> float:
    if column.size > 2048:
        column = column[:: max(1, int(column.size // 2048))]
    finite = column[np.isfinite(column)]
    if finite.size == 0:
        return 0.0
    return float(np.mean((finite < -0.05) | (finite > 1.05)))


def _parse_xywhr_candidates(arr, *, input_width: int, input_height: int, confidence: float, class_count: int | None, np):
    """Parse Ultralytics OBB export layout: cx,cy,w,h,class scores,angle."""
    rows: list[dict[str, Any]] = []
    if arr.shape[1] < 7:
        return rows
    for row in arr:
        try:
            cx, cy, width, height = (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
            angle = float(row[-1])
        except (TypeError, ValueError):
            continue
        scores = row[4:-1]
        if scores.size == 0:
            continue
        class_id = int(scores.argmax())
        if class_count is not None and class_id >= class_count:
            continue
        score = _normalize_confidence(float(scores[class_id]))
        if score < confidence:
            continue
        if max(abs(cx), abs(cy), abs(width), abs(height)) <= 2.0:
            cx *= input_width
            cy *= input_height
            width *= input_width
            height *= input_height
        if width <= 0 or height <= 0:
            continue
        obb = _xywhr_to_obb(cx, cy, width, height, angle)
        bbox = _bbox_from_points(obb)
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        rows.append({"class_id": class_id, "confidence": score, "bbox_px": bbox, "obb_px": obb})
    return rows


def _parse_xywh_candidates(arr, *, input_width: int, input_height: int, confidence: float, class_count: int | None):
    rows: list[dict[str, Any]] = []
    if arr.shape[1] < 5:
        return rows
    for row in arr:
        try:
            cx, cy, width, height = (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
        except (TypeError, ValueError):
            continue
        scores = row[4:]
        if scores.size == 0:
            continue
        class_id = int(scores.argmax())
        if class_count is not None and class_id >= class_count:
            continue
        score = _normalize_confidence(float(scores[class_id]))
        if score < confidence:
            continue
        if max(abs(cx), abs(cy), abs(width), abs(height)) <= 2.0:
            cx *= input_width
            cy *= input_height
            width *= input_width
            height *= input_height
        bbox = [cx - width * 0.5, cy - height * 0.5, cx + width * 0.5, cy + height * 0.5]
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        rows.append({"class_id": class_id, "confidence": score, "bbox_px": bbox})
    return rows


def _parse_outputs(outputs: list[Any], *, input_width: int, input_height: int, confidence: float, task: str, class_count: int | None, np):
    primary = next((row for row in outputs if isinstance(row, np.ndarray) and row.ndim >= 2), None)
    if primary is None:
        return []
    arr = primary
    if arr.ndim == 3 and int(arr.shape[0]) == 1:
        arr = arr[0]
    if arr.ndim != 2:
        arr = np.reshape(arr, (-1, arr.shape[-1]))
    # Ultralytics exports [channels, candidates] for a single image, but a
    # mocked/small export can already be [candidates, channels]. Only transpose
    # when the small dimension matches a plausible feature count.
    if arr.shape[0] <= 128 and arr.shape[1] > arr.shape[0]:
        expected_features = set()
        if class_count is not None:
            expected_features.update({int(class_count) + 4, int(class_count) + 5})
        if (arr.shape[0] >= 5 and ((expected_features and arr.shape[0] in expected_features) or (not expected_features and arr.shape[0] >= 7))):
            arr = arr.T
    if arr.shape[1] < 5:
        return []
    if task == "obb" or (class_count is not None and arr.shape[1] == class_count + 5):
        parsed = _parse_xywhr_candidates(
            arr,
            input_width=input_width,
            input_height=input_height,
            confidence=confidence,
            class_count=class_count,
            np=np,
        )
        if parsed:
            return parsed
    return _parse_xywh_candidates(
        arr,
        input_width=input_width,
        input_height=input_height,
        confidence=confidence,
        class_count=class_count,
    )


def _tile_starts(length: int, window: int, overlap: float) -> list[int]:
    if length <= window:
        return [0]
    step = max(1, int(round(window * (1.0 - overlap))))
    starts = list(range(0, max(1, length - window + 1), step))
    last = length - window
    if starts[-1] != last:
        starts.append(last)
    return sorted(set(starts))


def webmercator_tile_bounds(z: int, x: int, y: int) -> list[float]:
    if z < 0 or x < 0 or y < 0 or x >= 2**z or y >= 2**z:
        raise AircraftDetectorError("Invalid WebMercator tile coordinates.")
    n = 2.0**z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))
    return [west, south, east, north]


def _bounds_to_wgs84(bounds: list[float], crs: str) -> list[float]:
    if len(bounds) != 4:
        raise AircraftDetectorError("Geospatial bounds must be [minx, miny, maxx, maxy].")
    min_x, min_y, max_x, max_y = (float(value) for value in bounds)
    if not all(math.isfinite(value) for value in (min_x, min_y, max_x, max_y)) or max_x <= min_x or max_y <= min_y:
        raise AircraftDetectorError("Geospatial bounds are invalid.")
    normalized_crs = str(crs or "EPSG:4326").strip().lower()
    if normalized_crs in {"epsg:4326", "4326", "wgs84", "wgs 84"}:
        return [min_x, min_y, max_x, max_y]
    if normalized_crs not in {"epsg:3857", "3857", "webmercator", "web mercator"}:
        raise AircraftDetectorError(f"Unsupported geospatial CRS for detector output: {crs}")
    try:
        from pyproj import Transformer
    except Exception as exc:  # pragma: no cover - pyproj is a backend dependency
        raise AircraftDetectorError(f"pyproj is required for CRS conversion: {exc}") from exc
    transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    points = [
        transformer.transform(min_x, min_y),
        transformer.transform(max_x, max_y),
    ]
    return [points[0][0], points[0][1], points[1][0], points[1][1]]


def _project_point(x: float, y: float, width: int, height: int, bounds: list[float]) -> list[float]:
    west, south, east, north = bounds
    lon = west + (float(x) / max(1, width)) * (east - west)
    lat = north - (float(y) / max(1, height)) * (north - south)
    return [lon, lat]


def _project_detection_geometry(row: dict[str, Any], width: int, height: int, bounds: list[float]) -> list[list[float]]:
    points = row.get("obb_px")
    if not isinstance(points, list) or len(points) < 4:
        bbox = row.get("bbox_px") or [0.0, 0.0, 0.0, 0.0]
        x1, y1, x2, y2 = (float(value) for value in bbox[:4])
        points = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    projected = [_project_point(float(point[0]), float(point[1]), width, height, bounds) for point in points[:4]]
    projected.append(projected[0])
    return projected


def _safe_model_name(path: Path) -> str:
    return path.name or "aircraft-model.onnx"


class AircraftDetector:
    """Thread-safe lazy ONNX Runtime detector for local aircraft inference."""

    def __init__(self, config: AircraftDetectorConfig):
        self.config = config
        self._lock = threading.Lock()
        self._loaded_key: tuple[str, str] | None = None
        self._session = None
        self._np = None
        self._metadata: dict[str, Any] = {}
        self._providers: list[str] = []
        self._input_width = 1024
        self._input_height = 1024

    def _provider_chain(self, available: list[str]) -> list[str]:
        available_set = set(str(value) for value in available)
        requested = str(self.config.provider_mode or "auto").strip().lower()
        wants_cuda = requested in {"cuda", "gpu", "cudaexecutionprovider"} or requested.startswith("cuda,")
        wants_coreml = requested in {"coreml", "metal", "mps", "coremlexecutionprovider"} or requested.startswith("coreml,")
        if wants_cuda and "CUDAExecutionProvider" not in available_set:
            raise AircraftDetectorUnavailable(
                "CUDAExecutionProvider is not available in this ONNX Runtime installation. "
                "Install the GPU build and verify CUDA/cuDNN libraries."
            )
        if wants_coreml and "CoreMLExecutionProvider" not in available_set:
            raise AircraftDetectorUnavailable(
                "CoreMLExecutionProvider is not available in this ONNX Runtime installation. "
                "Install a macOS/CoreML ONNX Runtime build and verify the host provider list."
            )
        if requested in {"cpu", "cpuexecutionprovider"}:
            candidates = ["CPUExecutionProvider"]
        elif requested in {"coreml", "metal", "mps", "coremlexecutionprovider"}:
            candidates = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        elif requested in {"auto", "", "cuda", "gpu", "cudaexecutionprovider"}:
            candidates = ["CoreMLExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            candidates = [part.strip() for part in str(self.config.provider_mode).split(",") if part.strip()]
        chain = [provider for provider in candidates if provider in available_set]
        if not chain:
            raise AircraftDetectorUnavailable(
                f"No requested ONNX Runtime execution provider is available; installed providers: {available}."
            )
        return chain

    def _load(self):
        model_path = self.config.model_path.expanduser().resolve()
        if not model_path.exists():
            raise AircraftDetectorUnavailable(f"Aircraft model not found: {model_path}")
        try:
            import numpy as np
        except Exception as exc:
            raise AircraftDetectorUnavailable(f"NumPy is required for aircraft inference: {exc}") from exc
        try:
            import onnxruntime as ort
        except Exception as exc:
            raise AircraftDetectorUnavailable(
                "ONNX Runtime is not installed. Install backend/requirements-aircraft-gpu.txt "
                "for CUDA or backend/requirements-aircraft-cpu.txt for CPU verification."
            ) from exc

        available = [str(value) for value in ort.get_available_providers()]
        providers = self._provider_chain(available)
        key = (str(model_path), ",".join(providers))
        with self._lock:
            if self._loaded_key == key and self._session is not None:
                return self._session, np
            try:
                session = ort.InferenceSession(str(model_path), providers=providers)
            except Exception as exc:
                raise AircraftDetectorUnavailable(f"Could not load aircraft ONNX model: {exc}") from exc
            inputs = session.get_inputs()
            if not inputs:
                raise AircraftDetectorError("Aircraft ONNX model has no input tensor.")
            first_input = inputs[0]
            self._input_width, self._input_height = _resolve_input_shape(first_input.shape, fallback=self.config.window_size_px)
            custom: dict[str, Any] = {}
            try:
                custom = dict(getattr(session.get_modelmeta(), "custom_metadata_map", {}) or {})
            except Exception:
                custom = {}
            names = _parse_names(custom.get("names"))
            task = str(custom.get("task") or "detect").strip().lower()
            self._metadata = {
                "task": task,
                "names": names,
                "class_count": max(names.keys(), default=-1) + 1 if names else None,
                "imgsz": custom.get("imgsz"),
                "description": str(custom.get("description") or "").strip(),
                "license": str(custom.get("license") or "").strip(),
                "available_providers": available,
            }
            self._providers = [str(value) for value in session.get_providers()]
            self._loaded_key = key
            self._session = session
            self._np = np
            return session, np

    def capability(self) -> dict[str, Any]:
        model_path = self.config.model_path.expanduser()
        result: dict[str, Any] = {
            "enabled": True,
            "model_exists": model_path.exists(),
            "model_name": _safe_model_name(model_path),
            "runtime_available": False,
            "available_providers": [],
            "selected_providers": list(self._providers),
            "aircraft_classes": list(self.config.aircraft_classes),
        }
        if not model_path.exists():
            result["error"] = "model_not_found"
            return result
        try:
            import onnxruntime as ort
            result["runtime_available"] = True
            result["available_providers"] = [str(value) for value in ort.get_available_providers()]
            result["selected_providers"] = self._provider_chain(result["available_providers"])
        except Exception as exc:
            result["error"] = str(exc)[:240]
        if self._metadata:
            result["task"] = self._metadata.get("task")
            result["model_classes"] = self._metadata.get("names", {})
            result["license"] = self._metadata.get("license")
        return result

    def _infer_window(self, image: Image.Image, session, np, *, confidence: float) -> list[dict[str, Any]]:
        tensor, gain, pad_x, pad_y = _letterbox(image, self._input_width, self._input_height, np)
        array = np.ascontiguousarray(np.transpose(tensor, (2, 0, 1))[None, :, :, :], dtype=np.float32) / 255.0
        input_name = str(session.get_inputs()[0].name or "").strip()
        if not input_name:
            raise AircraftDetectorError("Aircraft ONNX model input name is empty.")
        outputs = session.run(None, {input_name: array})
        candidates = _parse_outputs(
            outputs,
            input_width=self._input_width,
            input_height=self._input_height,
            confidence=confidence,
            task=str(self._metadata.get("task") or "detect"),
            class_count=self._metadata.get("class_count"),
            np=np,
        )
        names: dict[int, str] = self._metadata.get("names") or {}
        class_tokens = {str(value).strip().lower() for value in self.config.aircraft_classes}
        filtered: list[dict[str, Any]] = []
        for row in candidates:
            class_id = int(row.get("class_id", -1))
            class_name = str(names.get(class_id) or f"class_{class_id}").strip()
            normalized_name = class_name.lower()
            if class_tokens and not any(token in normalized_name for token in class_tokens):
                continue
            bbox = row.get("bbox_px") or [0.0, 0.0, 0.0, 0.0]
            projected_bbox = [
                _unletterbox(float(bbox[0]), pad_x, gain, image.width),
                _unletterbox(float(bbox[1]), pad_y, gain, image.height),
                _unletterbox(float(bbox[2]), pad_x, gain, image.width),
                _unletterbox(float(bbox[3]), pad_y, gain, image.height),
            ]
            if projected_bbox[2] <= projected_bbox[0] or projected_bbox[3] <= projected_bbox[1]:
                continue
            projected_obb: list[list[float]] = []
            for point in row.get("obb_px") or []:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    projected_obb.append([
                        _unletterbox(float(point[0]), pad_x, gain, image.width),
                        _unletterbox(float(point[1]), pad_y, gain, image.height),
                    ])
            filtered.append({
                "class_id": class_id,
                "class_name": class_name,
                "confidence": round(float(row.get("confidence", 0.0)), 6),
                "bbox_px": projected_bbox,
                "obb_px": projected_obb if len(projected_obb) == 4 else [
                    [projected_bbox[0], projected_bbox[1]],
                    [projected_bbox[2], projected_bbox[1]],
                    [projected_bbox[2], projected_bbox[3]],
                    [projected_bbox[0], projected_bbox[3]],
                ],
            })
        return filtered

    def detect_bytes(self, image_bytes: bytes, *, provenance: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = bytes(image_bytes or b"")
        if not raw:
            raise AircraftDetectorError("Detector input image is empty.")
        if len(raw) > int(self.config.max_image_bytes):
            raise AircraftDetectorError(f"Detector input exceeds {self.config.max_image_bytes} byte limit.")
        session, np = self._load()
        started = time.perf_counter()
        try:
            with Image.open(BytesIO(raw)) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
        except Exception as exc:
            raise AircraftDetectorError(f"Detector input is not a supported image: {exc}") from exc
        width, height = image.size
        if width <= 0 or height <= 0 or width * height > int(self.config.max_image_pixels):
            raise AircraftDetectorError("Detector input dimensions exceed the configured limit.")

        window = max(64, min(int(self.config.window_size_px), self._input_width, self._input_height))
        overlap = max(0.0, min(0.75, float(self.config.window_overlap)))
        x_starts = _tile_starts(width, window, overlap)
        y_starts = _tile_starts(height, window, overlap)
        rows: list[dict[str, Any]] = []
        for y0 in y_starts:
            for x0 in x_starts:
                crop = image.crop((x0, y0, min(width, x0 + window), min(height, y0 + window)))
                for row in self._infer_window(crop, session, np, confidence=float(self.config.confidence)):
                    row["bbox_px"] = [
                        float(row["bbox_px"][0]) + x0,
                        float(row["bbox_px"][1]) + y0,
                        float(row["bbox_px"][2]) + x0,
                        float(row["bbox_px"][3]) + y0,
                    ]
                    row["obb_px"] = [[float(point[0]) + x0, float(point[1]) + y0] for point in row["obb_px"]]
                    rows.append(row)
        rows = _class_aware_nms(rows, float(self.config.iou))
        rows = sorted(rows, key=lambda row: float(row.get("confidence", 0.0)), reverse=True)[: int(self.config.max_detections)]
        bounds = None
        warnings: list[str] = []
        geo = provenance if isinstance(provenance, dict) else {}
        if geo.get("z") is not None and geo.get("x") is not None and geo.get("y") is not None:
            try:
                bounds = webmercator_tile_bounds(int(geo["z"]), int(geo["x"]), int(geo["y"]))
                geo_crs = "EPSG:4326"
            except (TypeError, ValueError, AircraftDetectorError) as exc:
                warnings.append(f"invalid_tile_coordinates: {exc}")
                geo_crs = "EPSG:4326"
        elif geo.get("bounds") is not None:
            try:
                geo_crs = str(geo.get("crs") or "EPSG:4326")
                bounds = _bounds_to_wgs84([float(value) for value in geo["bounds"]], geo_crs)
                geo_crs = "EPSG:4326"
            except (TypeError, ValueError, AircraftDetectorError) as exc:
                warnings.append(f"invalid_georeferencing: {exc}")
                bounds = None
                geo_crs = str(geo.get("crs") or "")
        else:
            geo_crs = ""
            warnings.append("missing_georeferencing")

        normalized: list[dict[str, Any]] = []
        features: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            detection = {
                "detection_id": f"aircraft_{index:03d}",
                "class_id": int(row.get("class_id", -1)),
                "class_name": str(row.get("class_name") or "aircraft"),
                "confidence": round(float(row.get("confidence", 0.0)), 6),
                "bbox_px": [round(float(value), 3) for value in row.get("bbox_px", [])[:4]],
                "obb_px": [[round(float(point[0]), 3), round(float(point[1]), 3)] for point in row.get("obb_px", [])[:4]],
                "source_width_px": width,
                "source_height_px": height,
            }
            normalized.append(detection)
            feature: dict[str, Any] = {
                "type": "Feature",
                "id": detection["detection_id"],
                "properties": {
                    "detection_id": detection["detection_id"],
                    "class_id": detection["class_id"],
                    "class_name": detection["class_name"],
                    "confidence": detection["confidence"],
                    "bbox_px": detection["bbox_px"],
                    "obb_px": detection["obb_px"],
                    "source_width_px": width,
                    "source_height_px": height,
                },
                "geometry": None,
            }
            if bounds is not None:
                feature["geometry"] = {
                    "type": "Polygon",
                    "coordinates": [_project_detection_geometry(row, width, height, bounds)],
                }
            features.append(feature)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        model_path = self.config.model_path.expanduser()
        return {
            "detector": "aircraft",
            "model": {
                "name": _safe_model_name(model_path),
                "task": self._metadata.get("task"),
                "classes": self._metadata.get("names", {}),
                "selected_classes": list(self.config.aircraft_classes),
                "license": self._metadata.get("license"),
                "provider_mode": self.config.provider_mode,
                "providers": list(self._providers),
            },
            "input": {
                "width_px": width,
                "height_px": height,
                "window_size_px": window,
                "window_overlap": overlap,
                "window_count": len(x_starts) * len(y_starts),
                "collection_id": geo.get("collection_id"),
                "item_id": geo.get("item_id"),
                "asset_key": geo.get("asset_key"),
                "z": geo.get("z"),
                "x": geo.get("x"),
                "y": geo.get("y"),
                "scale": geo.get("scale"),
                "crs": geo_crs or None,
                "bounds_wgs84": bounds,
            },
            "thresholds": {
                "confidence": float(self.config.confidence),
                "iou": float(self.config.iou),
                "max_detections": int(self.config.max_detections),
            },
            "detections": normalized,
            "geojson": {"type": "FeatureCollection", "features": features},
            "warnings": warnings,
            "inference_ms": elapsed_ms,
        }


def detector_capability(config: AircraftDetectorConfig) -> dict[str, Any]:
    """Return safe capability metadata without loading or printing credentials."""
    detector = AircraftDetector(config)
    return detector.capability()
