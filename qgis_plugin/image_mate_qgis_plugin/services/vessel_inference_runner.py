# -*- coding: utf-8 -*-
"""Run vessel ONNX inference in an isolated Python process."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any


def _resolve_input_shape(shape: list[Any] | tuple[Any, ...]) -> tuple[int, int]:
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
    return width, height


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


def _read_raster_rgb_uint8(raster_path: str):
    try:
        import numpy as np
    except Exception as exc:
        raise RuntimeError(f"NumPy is required for vessel detection: {exc}") from exc
    try:
        return _read_raster_rgb_uint8_gdal(raster_path, np)
    except Exception as gdal_exc:
        try:
            return _read_raster_rgb_uint8_rasterio(raster_path, np)
        except Exception as rasterio_exc:
            raise RuntimeError(
                "Could not read raster for detection. "
                f"GDAL path failed: {gdal_exc}; rasterio fallback failed: {rasterio_exc}"
            ) from rasterio_exc


def _read_raster_rgb_uint8_gdal(raster_path: str, np):
    from osgeo import gdal

    ds = gdal.Open(str(raster_path), gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Could not open raster for detection: {raster_path}")
    try:
        width = int(ds.RasterXSize or 0)
        height = int(ds.RasterYSize or 0)
        bands = int(ds.RasterCount or 0)
        if width <= 0 or height <= 0 or bands <= 0:
            raise RuntimeError("Input raster has invalid size or no bands.")

        pick_count = 3 if bands >= 3 else 1
        band_arrays = []
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
        rgb = np.stack(
            [_normalize_band_uint8(arr, np) for arr in band_arrays[:3]],
            axis=-1,
        )
        return rgb.astype(np.uint8, copy=False)
    finally:
        ds = None


def _read_raster_rgb_uint8_rasterio(raster_path: str, np):
    import rasterio

    with rasterio.open(str(raster_path)) as ds:
        width = int(ds.width or 0)
        height = int(ds.height or 0)
        band_count = int(ds.count or 0)
        if width <= 0 or height <= 0 or band_count <= 0:
            raise RuntimeError("Input raster has invalid dimensions or no bands.")
        pick_count = 3 if band_count >= 3 else 1
        indexes = list(range(1, pick_count + 1))
        data = ds.read(indexes=indexes)
        nodata_values = list(ds.nodatavals or [])
        norm_bands = []
        for idx in range(pick_count):
            nodata = nodata_values[idx] if idx < len(nodata_values) else None
            arr = data[idx]
            values = arr.astype(np.float32, copy=False)
            finite = np.isfinite(values)
            if nodata is not None and math.isfinite(float(nodata)):
                finite = finite & (values != float(nodata))
            if not np.any(finite):
                norm_bands.append(np.zeros(values.shape, dtype=np.uint8))
                continue
            valid = values[finite]
            low = float(np.percentile(valid, 2.0))
            high = float(np.percentile(valid, 98.0))
            if not math.isfinite(low) or not math.isfinite(high) or high <= low:
                low = float(np.min(valid))
                high = float(np.max(valid))
            if not math.isfinite(low) or not math.isfinite(high) or high <= low:
                out = np.zeros(values.shape, dtype=np.uint8)
                out[finite] = 127
                norm_bands.append(out)
                continue
            scaled = (values - low) / max(1e-6, high - low)
            scaled = np.clip(scaled, 0.0, 1.0)
            norm_bands.append(np.rint(scaled * 255.0).astype(np.uint8))
        if len(norm_bands) == 1:
            norm_bands = [norm_bands[0], norm_bands[0], norm_bands[0]]
        rgb = np.stack(norm_bands[:3], axis=-1)
        return rgb.astype(np.uint8, copy=False)


def _parse_xywh_classprob_candidates(*, arr, input_width: int, input_height: int, conf: float):
    out = []
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
        score = float(class_scores[class_id])
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


def _parse_xywhr_classprob_candidates(
    *,
    arr,
    input_width: int,
    input_height: int,
    conf: float,
    angle_layout: str,
):
    out = []
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
            class_scores = row[4:-1]
        else:
            try:
                angle = float(row[4])
            except Exception:
                continue
            class_scores = row[5:]
        if class_scores.size <= 0:
            continue
        class_id = int(class_scores.argmax())
        score = float(class_scores[class_id])
        if not math.isfinite(score):
            continue
        if score < 0.0 or score > 1.0:
            # Some exports expose logits; map them to [0, 1].
            score = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, score))))
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
                "obb_px": _xywhr_to_obb(cx, cy, w, h, angle),
            }
        )
    return out


def _sample_out_of_unit_ratio(col, np) -> float:
    if col.size > 2048:
        step = max(1, int(col.size // 2048))
        col = col[::step]
    finite = col[np.isfinite(col)]
    if finite.size <= 0:
        return 0.0
    return float(np.mean((finite < -0.05) | (finite > 1.05)))


def _select_obb_layout(arr, np) -> str | None:
    if arr.shape[1] < 7 or arr.shape[1] > 50:
        return None
    col4_ratio = _sample_out_of_unit_ratio(arr[:, 4], np)
    col_last_ratio = _sample_out_of_unit_ratio(arr[:, -1], np)
    best = max(col4_ratio, col_last_ratio)
    if best < 0.02:
        return None
    if col_last_ratio >= col4_ratio + 0.01:
        return "last"
    if col4_ratio >= col_last_ratio + 0.01:
        return "fifth"
    # Prefer Ultralytics OBB export layout when both columns look similar.
    return "last"


def _parse_xyxy_score_class_candidates(*, arr, input_width: int, input_height: int, conf: float):
    out = []
    for row in arr:
        if len(row) < 6:
            continue
        try:
            x1, y1, x2, y2 = (float(row[0]), float(row[1]), float(row[2]), float(row[3]))
            score = float(row[4])
            class_id = int(round(float(row[5])))
        except Exception:
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


def _parse_onnx_outputs(*, outputs: list[Any], input_width: int, input_height: int, conf: float):
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
    if arr.shape[0] <= 128 and arr.shape[1] > arr.shape[0]:
        arr = arr.T
    if arr.shape[1] < 6 and arr.shape[0] >= 6:
        arr = arr.T
    if arr.shape[1] < 6:
        return []

    obb_layout = _select_obb_layout(arr, np)
    if obb_layout is not None:
        parsed_obb = _parse_xywhr_classprob_candidates(
            arr=arr,
            input_width=input_width,
            input_height=input_height,
            conf=conf,
            angle_layout=obb_layout,
        )
        if parsed_obb:
            return parsed_obb
        parsed_obb_alt = _parse_xywhr_classprob_candidates(
            arr=arr,
            input_width=input_width,
            input_height=input_height,
            conf=conf,
            angle_layout=("fifth" if obb_layout == "last" else "last"),
        )
        if parsed_obb_alt:
            return parsed_obb_alt

    parsed_xywh = _parse_xywh_classprob_candidates(
        arr=arr,
        input_width=input_width,
        input_height=input_height,
        conf=conf,
    )
    if parsed_xywh:
        return parsed_xywh
    return _parse_xyxy_score_class_candidates(
        arr=arr,
        input_width=input_width,
        input_height=input_height,
        conf=conf,
    )


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
    if union <= 0.0:
        return 0.0
    return inter / union


def _nms(rows: list[dict[str, Any]], *, iou_threshold: float) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda r: float(r.get("confidence", 0.0)), reverse=True)
    kept = []
    for row in ordered:
        bbox = row.get("bbox_px")
        if not isinstance(bbox, list) or len(bbox) < 4:
            continue
        keep = True
        for selected in kept:
            selected_bbox = selected.get("bbox_px")
            if not isinstance(selected_bbox, list) or len(selected_bbox) < 4:
                continue
            if _bbox_iou(bbox[:4], selected_bbox[:4]) > iou_threshold:
                keep = False
                break
        if keep:
            kept.append(row)
    return kept


def _bbox_to_obb(bbox: list[float]) -> list[list[float]]:
    if not isinstance(bbox, list) or len(bbox) < 4:
        return [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    x1, y1, x2, y2 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _infer(*, layer_path: str, model_path: str, conf: float, iou: float, max_det: int):
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

    image_rgb = _read_raster_rgb_uint8(layer_path)

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

    target_w, target_h = _resolve_input_shape(input_tensor.shape)
    image = Image.fromarray(image_rgb, mode="RGB").resize((target_w, target_h))
    arr = np.asarray(image).astype(np.float32) / 255.0
    # Some Windows/OSGeo onnxruntime builds crash on non-contiguous tensors.
    arr = np.ascontiguousarray(np.transpose(arr, (2, 0, 1))[None, :, :, :], dtype=np.float32)
    outputs = session.run(None, {input_name: arr})
    candidates = _parse_onnx_outputs(
        outputs=outputs,
        input_width=target_w,
        input_height=target_h,
        conf=conf,
    )
    if not candidates:
        return []

    orig_h, orig_w = int(image_rgb.shape[0]), int(image_rgb.shape[1])
    sx = float(orig_w) / float(target_w)
    sy = float(orig_h) / float(target_h)
    for row in candidates:
        x1, y1, x2, y2 = row["bbox_px"]
        row["bbox_px"] = [
            max(0.0, min(float(orig_w), float(x1) * sx)),
            max(0.0, min(float(orig_h), float(y1) * sy)),
            max(0.0, min(float(orig_w), float(x2) * sx)),
            max(0.0, min(float(orig_h), float(y2) * sy)),
        ]
        obb = row.get("obb_px")
        if isinstance(obb, list) and len(obb) >= 4:
            scaled = []
            for pair in obb[:4]:
                if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                    continue
                try:
                    ox = max(0.0, min(float(orig_w), float(pair[0]) * sx))
                    oy = max(0.0, min(float(orig_h), float(pair[1]) * sy))
                    scaled.append([ox, oy])
                except Exception:
                    continue
            row["obb_px"] = scaled if len(scaled) == 4 else _bbox_to_obb(row["bbox_px"])
        else:
            row["obb_px"] = _bbox_to_obb(row["bbox_px"])

    pre_nms_limit = max(400, min(4000, int(max_det) * 200))
    if len(candidates) > pre_nms_limit:
        candidates.sort(key=lambda r: float(r.get("confidence", 0.0)), reverse=True)
        candidates = candidates[:pre_nms_limit]

    filtered = _nms(candidates, iou_threshold=iou)
    filtered.sort(key=lambda r: float(r.get("confidence", 0.0)), reverse=True)
    filtered = filtered[:max_det]

    rows = []
    for idx, row in enumerate(filtered, start=1):
        class_id = int(row.get("class_id", 0))
        class_name = "vessel" if class_id == 0 else f"class_{class_id}"
        rows.append(
            {
                "detection_id": f"det_{idx:03d}",
                "class_id": class_id,
                "class_name": class_name,
                "confidence": round(float(row.get("confidence", 0.0)), 6),
                "bbox_px": [float(v) for v in row.get("bbox_px", [0.0, 0.0, 0.0, 0.0])[:4]],
                "obb_px": [[float(p[0]), float(p[1])] for p in row.get("obb_px", [])[:4]],
                "source_width_px": orig_w,
                "source_height_px": orig_h,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated ONNX vessel inference.")
    parser.add_argument("--layer-path", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--max-det", type=int, default=20)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args()

    layer_path = Path(str(args.layer_path)).expanduser()
    model_path = Path(str(args.model_path)).expanduser()
    if not layer_path.exists():
        raise RuntimeError(f"Input raster not found: {layer_path}")
    if not model_path.exists():
        raise RuntimeError(f"ONNX model not found: {model_path}")

    detections = _infer(
        layer_path=str(layer_path),
        model_path=str(model_path),
        conf=max(0.01, min(1.0, float(args.conf))),
        iou=max(0.01, min(1.0, float(args.iou))),
        max_det=max(1, min(500, int(args.max_det))),
    )
    output_path = Path(str(args.output_json)).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(detections, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
