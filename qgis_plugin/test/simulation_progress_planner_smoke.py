#!/usr/bin/env python3
"""Smoke checks for simulation progress planning helpers."""

from __future__ import annotations

from pathlib import Path
import sys


def _repo_plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _assert_true(condition: bool, label: str) -> None:
    if not bool(condition):
        raise AssertionError(label)


def _assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected={expected!r} actual={actual!r}")


def main() -> int:
    plugin_root = _repo_plugin_root()
    sys.path.insert(0, str(plugin_root))

    from image_mate_qgis_plugin.services.simulation_progress_planner import (  # noqa: PLC0415
        coverage_progress_plan,
        revisit_progress_plan,
    )

    coverage_short = coverage_progress_plan(total_satellites=1, total_days=10)
    _assert_equal(coverage_short["satellite_units"], 1000, "coverage_satellite_units")
    _assert_true(80 <= coverage_short["finalization_units"] <= 600, "coverage_short_final_bounds")
    _assert_equal(
        coverage_short["total_units"],
        coverage_short["satellite_units"] + coverage_short["finalization_units"],
        "coverage_short_total_units",
    )

    coverage_long = coverage_progress_plan(total_satellites=5, total_days=400)
    _assert_true(80 <= coverage_long["finalization_units"] <= 600, "coverage_long_final_bounds")
    _assert_equal(
        coverage_long["total_units"],
        5 * coverage_long["satellite_units"] + coverage_long["finalization_units"],
        "coverage_long_total_units",
    )
    _assert_true(
        coverage_long["finalization_units"] >= coverage_short["finalization_units"],
        "coverage_longer_days_more_or_equal_final_units",
    )

    revisit_short = revisit_progress_plan(total_satellites=2, total_days=15)
    _assert_equal(revisit_short["satellite_units"], 1000, "revisit_satellite_units")
    _assert_true(40 <= revisit_short["finalization_units"] <= 240, "revisit_short_final_bounds")
    _assert_equal(
        revisit_short["total_units"],
        2 * revisit_short["satellite_units"] + revisit_short["finalization_units"],
        "revisit_short_total_units",
    )

    revisit_long = revisit_progress_plan(total_satellites=2, total_days=1000)
    _assert_true(40 <= revisit_long["finalization_units"] <= 240, "revisit_long_final_bounds")
    _assert_true(
        revisit_long["finalization_units"] >= revisit_short["finalization_units"],
        "revisit_longer_days_more_or_equal_final_units",
    )

    print("simulation_progress_planner_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
