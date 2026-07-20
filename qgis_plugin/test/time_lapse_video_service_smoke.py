#!/usr/bin/env python3
"""Smoke checks for time-lapse frame/fps normalization helpers."""

from __future__ import annotations

from pathlib import Path
import sys


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected={expected!r} actual={actual!r}")


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.time_lapse_video_service import (  # noqa: PLC0415
        TimeLapseVideoService,
        TimeLapseFrameSpec,
        normalize_time_lapse_fps,
        normalize_time_lapse_frames,
    )

    frames = normalize_time_lapse_frames(
        [
            {
                "frame_name": "Frame A",
                "layer_ids": ["layer_1", "layer_2", "layer_1"],
                "hold_frames": "3",
                "overlay_text": "",
            },
            {
                "layer_ids": ["layer_3"],
                "hold_frames": 0,
                "overlay_text": "Custom",
            },
        ]
    )
    _assert_equal(len(frames), 2, "frame_count")
    _assert_equal(
        frames[0],
        TimeLapseFrameSpec(
            layer_ids=("layer_1", "layer_2"),
            hold_frames=3,
            overlay_text="Frame A",
            label="Frame A",
        ),
        "first_frame",
    )
    _assert_equal(frames[1].layer_ids, ("layer_3",), "second_frame_layer_ids")
    _assert_equal(frames[1].hold_frames, 1, "second_frame_hold_floor")
    _assert_equal(frames[1].overlay_text, "Custom", "second_frame_overlay")
    _assert_equal(frames[1].label, "Frame 2", "second_frame_default_label")

    fps_ok = normalize_time_lapse_fps("5", default=2)
    _assert_equal(fps_ok, 5, "fps_parse")
    fps_default = normalize_time_lapse_fps("0", default=2)
    _assert_equal(fps_default, 2, "fps_default_low")
    fps_clamped = normalize_time_lapse_fps(200, default=2, max_value=60)
    _assert_equal(fps_clamped, 2, "fps_default_high")

    try:
        normalize_time_lapse_frames([{"frame_name": "Invalid"}])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError when no valid layer_ids are provided")

    probe = TimeLapseVideoService._parse_video_probe_payload(
        {
            "streams": [
                {
                    "duration": "12.500000",
                    "nb_frames": "25",
                    "nb_read_frames": "25",
                    "avg_frame_rate": "2/1",
                    "r_frame_rate": "2/1",
                }
            ],
            "format": {"duration": "12.500000"},
        }
    )
    if not isinstance(probe, dict):
        raise AssertionError("expected parsed probe payload to be a dict")
    _assert_equal(probe.get("duration_s"), 12.5, "probe_duration")
    _assert_equal(probe.get("frame_count"), 25, "probe_frame_count")
    _assert_equal(probe.get("avg_frame_rate"), "2/1", "probe_avg_frame_rate")
    _assert_equal(probe.get("r_frame_rate"), "2/1", "probe_r_frame_rate")

    probe_fallback = TimeLapseVideoService._parse_video_probe_payload(
        {
            "streams": [{"duration": "", "nb_frames": "", "nb_read_frames": ""}],
            "format": {"duration": "9.75"},
        }
    )
    if not isinstance(probe_fallback, dict):
        raise AssertionError("expected parsed fallback probe payload to be a dict")
    _assert_equal(probe_fallback.get("duration_s"), 9.75, "probe_duration_fallback")
    _assert_equal(probe_fallback.get("frame_count"), 0, "probe_frame_count_fallback")

    _assert_equal(TimeLapseVideoService._parse_video_probe_payload({}), None, "probe_invalid_payload")

    print("time_lapse_video_service_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
