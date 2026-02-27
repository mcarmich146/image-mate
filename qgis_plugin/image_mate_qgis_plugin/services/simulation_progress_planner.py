# -*- coding: utf-8 -*-
"""Progress planning helpers for long-running simulation workers."""

from __future__ import annotations


def _to_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)


def _normalize_satellite_count(total_satellites):
    return max(1, _to_int(total_satellites, default=1))


def _normalize_days(total_days):
    return max(1, _to_int(total_days, default=1))


def coverage_progress_plan(*, total_satellites, total_days):
    satellites = _normalize_satellite_count(total_satellites)
    days = _normalize_days(total_days)

    satellite_units = 1000
    # Daily geometry unions/serializations can dominate tail latency on long runs.
    finalization_units = max(80, min(600, int(round(days * 0.8))))
    total_units = max(1, satellites * satellite_units + finalization_units)
    return {
        "satellite_units": satellite_units,
        "finalization_units": finalization_units,
        "total_units": total_units,
    }


def revisit_progress_plan(*, total_satellites, total_days):
    satellites = _normalize_satellite_count(total_satellites)
    days = _normalize_days(total_days)

    satellite_units = 1000
    finalization_units = max(40, min(240, days))
    total_units = max(1, satellites * satellite_units + finalization_units)
    return {
        "satellite_units": satellite_units,
        "finalization_units": finalization_units,
        "total_units": total_units,
    }
