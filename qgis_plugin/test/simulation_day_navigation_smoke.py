#!/usr/bin/env python3
"""Smoke checks for simulation day navigation helpers."""

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

    from image_mate_qgis_plugin.services.simulation_day_navigation import (  # noqa: PLC0415
        clamp_day_index,
        end_day_index,
        navigation_button_state,
        shift_day_index,
        start_day_index,
    )

    _assert_equal(clamp_day_index(-3, 10), 0, "clamp_negative")
    _assert_equal(clamp_day_index(4, 10), 4, "clamp_middle")
    _assert_equal(clamp_day_index(30, 10), 9, "clamp_overflow")
    _assert_equal(clamp_day_index(7, 0), 0, "clamp_empty")

    _assert_equal(shift_day_index(5, 10, -30), 0, "shift_back_30")
    _assert_equal(shift_day_index(5, 10, 30), 9, "shift_forward_30")
    _assert_equal(shift_day_index(5, 10, -1), 4, "shift_back_1")
    _assert_equal(shift_day_index(5, 10, 1), 6, "shift_forward_1")

    _assert_equal(start_day_index(10), 0, "start_idx")
    _assert_equal(end_day_index(10), 9, "end_idx")
    _assert_equal(end_day_index(0), 0, "end_idx_empty")

    state_first = navigation_button_state(0, 10)
    _assert_equal(state_first["can_first"], False, "first_can_first")
    _assert_equal(state_first["can_prev_30"], False, "first_can_prev_30")
    _assert_equal(state_first["can_prev_1"], False, "first_can_prev_1")
    _assert_equal(state_first["can_next_1"], True, "first_can_next_1")
    _assert_equal(state_first["can_next_30"], True, "first_can_next_30")
    _assert_equal(state_first["can_last"], True, "first_can_last")

    state_last = navigation_button_state(9, 10)
    _assert_equal(state_last["can_first"], True, "last_can_first")
    _assert_equal(state_last["can_prev_30"], True, "last_can_prev_30")
    _assert_equal(state_last["can_prev_1"], True, "last_can_prev_1")
    _assert_equal(state_last["can_next_1"], False, "last_can_next_1")
    _assert_equal(state_last["can_next_30"], False, "last_can_next_30")
    _assert_equal(state_last["can_last"], False, "last_can_last")

    state_mid = navigation_button_state(5, 10)
    _assert_equal(state_mid["can_first"], True, "mid_can_first")
    _assert_equal(state_mid["can_prev_30"], True, "mid_can_prev_30")
    _assert_equal(state_mid["can_prev_1"], True, "mid_can_prev_1")
    _assert_equal(state_mid["can_next_1"], True, "mid_can_next_1")
    _assert_equal(state_mid["can_next_30"], True, "mid_can_next_30")
    _assert_equal(state_mid["can_last"], True, "mid_can_last")

    print("simulation_day_navigation_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
