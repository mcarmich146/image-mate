#!/usr/bin/env python3
"""Smoke checks for OBB vessel parsing robustness."""

from __future__ import annotations

from pathlib import Path
import sys


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_true(condition: bool, label: str) -> None:
    if not bool(condition):
        raise AssertionError(label)


def _assert_close(actual: float, expected: float, label: str, tol: float = 1e-4) -> None:
    if abs(float(actual) - float(expected)) > float(tol):
        raise AssertionError(f"{label}: expected~={expected!r} actual={actual!r}")


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    import numpy as np  # noqa: PLC0415
    from PIL import Image as PILImage  # noqa: PLC0415

    from image_mate_qgis_plugin.services.vessel_detection_service import VesselDetectionService  # noqa: PLC0415

    svc = VesselDetectionService()

    # Case 1: OBB output with angle in [0, 1] should still parse as OBB, not as extra class column.
    arr_no_obj = np.zeros((1, 20, 1), dtype=np.float32)
    arr_no_obj[0, 0, 0] = 0.5
    arr_no_obj[0, 1, 0] = 0.5
    arr_no_obj[0, 2, 0] = 0.2
    arr_no_obj[0, 3, 0] = 0.1
    arr_no_obj[0, 4:19, 0] = 0.01
    arr_no_obj[0, 7, 0] = 0.62  # class_id=3 in OBB class block (index offset 4)
    arr_no_obj[0, 19, 0] = 0.99  # ambiguous angle value that used to look like class score
    parsed_no_obj = svc._parse_onnx_outputs(
        outputs=[arr_no_obj],
        input_width=1024,
        input_height=1024,
        conf=0.5,
        expected_class_count=15,
    )
    _assert_true(len(parsed_no_obj) == 1, "obb_no_objectness_count")
    _assert_true(int(parsed_no_obj[0].get("class_id", -1)) == 3, "obb_no_objectness_class")
    _assert_close(float(parsed_no_obj[0].get("confidence", 0.0)), 0.62, "obb_no_objectness_conf")

    # Case 2: OBB output with explicit objectness should use obj*class confidence and preserve class IDs.
    arr_with_obj = np.zeros((1, 21, 1), dtype=np.float32)
    arr_with_obj[0, 0, 0] = 0.5
    arr_with_obj[0, 1, 0] = 0.5
    arr_with_obj[0, 2, 0] = 0.2
    arr_with_obj[0, 3, 0] = 0.1
    arr_with_obj[0, 4, 0] = 0.8  # objectness
    arr_with_obj[0, 5:20, 0] = 0.01
    arr_with_obj[0, 8, 0] = 0.7  # class_id=3 in class block (index offset 5)
    arr_with_obj[0, 20, 0] = 0.4  # angle
    parsed_with_obj = svc._parse_onnx_outputs(
        outputs=[arr_with_obj],
        input_width=1024,
        input_height=1024,
        conf=0.5,
        expected_task="obb",
        expected_class_count=15,
    )
    _assert_true(len(parsed_with_obj) == 1, "obb_with_objectness_count")
    _assert_true(int(parsed_with_obj[0].get("class_id", -1)) == 3, "obb_with_objectness_class")
    _assert_close(float(parsed_with_obj[0].get("confidence", 0.0)), 0.56, "obb_with_objectness_conf")

    # Case 3: Letterbox preprocessing + unletterbox mapping should preserve coordinates.
    image = np.zeros((400, 800, 3), dtype=np.uint8)
    _, gain, pad_x, pad_y = svc._letterbox_image(
        image_rgb=image,
        target_w=640,
        target_h=640,
        np=np,
        Image=PILImage,
    )
    x1_net = (80.0 * gain) + pad_x
    y1_net = (40.0 * gain) + pad_y
    x2_net = (240.0 * gain) + pad_x
    y2_net = (120.0 * gain) + pad_y
    _assert_close(
        svc._unletterbox_coord(x1_net, pad=pad_x, gain=gain, max_value=800),
        80.0,
        "letterbox_x1",
    )
    _assert_close(
        svc._unletterbox_coord(y1_net, pad=pad_y, gain=gain, max_value=400),
        40.0,
        "letterbox_y1",
    )
    _assert_close(
        svc._unletterbox_coord(x2_net, pad=pad_x, gain=gain, max_value=800),
        240.0,
        "letterbox_x2",
    )
    _assert_close(
        svc._unletterbox_coord(y2_net, pad=pad_y, gain=gain, max_value=400),
        120.0,
        "letterbox_y2",
    )

    print("vessel_obb_parser_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
