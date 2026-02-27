#!/usr/bin/env python3
"""Smoke checks for shared resample workflow presets."""

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

    from image_mate_qgis_plugin.services.resample_workflows import (  # noqa: PLC0415
        RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M,
        RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M,
        RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M,
        resolution_hint_token,
    )

    _assert_equal(
        RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M.action_label,
        "Resample to 10.8->3m (PlanetScope)",
        "planetscope_label",
    )
    _assert_equal(
        RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M.stage_resolutions_m,
        (10.8, 3.0),
        "planetscope_steps",
    )
    _assert_equal(
        RESAMPLE_WORKFLOW_PLANETSCOPE_10P8_TO_3M.resolution_chain_label(),
        "10.8 m -> 3 m",
        "planetscope_chain_label",
    )
    _assert_equal(
        RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M.action_label,
        "Resample to 2m->1m (Merlin)",
        "merlin_label",
    )
    _assert_equal(
        RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M.stage_resolutions_m,
        (2.0, 1.0),
        "merlin_steps",
    )
    _assert_equal(
        RESAMPLE_WORKFLOW_MERLIN_2M_TO_1M.resolution_chain_label(),
        "2 m -> 1 m",
        "merlin_chain_label",
    )
    _assert_equal(
        RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M.action_label,
        "Resample to 3.76m->1m (Merlin)",
        "merlin_3p76_label",
    )
    _assert_equal(
        RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M.stage_resolutions_m,
        (3.76, 1.0),
        "merlin_3p76_steps",
    )
    _assert_equal(
        RESAMPLE_WORKFLOW_MERLIN_3P76M_TO_1M.resolution_chain_label(),
        "3.76 m -> 1 m",
        "merlin_3p76_chain_label",
    )
    _assert_equal(resolution_hint_token(10.8), "10p8m", "hint_token_decimal")
    _assert_equal(resolution_hint_token(3.76), "3p76m", "hint_token_decimal_merlin")
    _assert_equal(resolution_hint_token(3), "3m", "hint_token_integer")

    print("resample_workflows_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
