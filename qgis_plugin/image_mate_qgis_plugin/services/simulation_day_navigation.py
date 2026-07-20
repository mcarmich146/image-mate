# -*- coding: utf-8 -*-
"""Helpers for simulation day-index navigation."""

from __future__ import annotations


def _to_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)


def normalize_total_days(total_days):
    return max(0, _to_int(total_days, default=0))


def clamp_day_index(index, total_days):
    total = normalize_total_days(total_days)
    if total <= 0:
        return 0
    return max(0, min(_to_int(index, default=0), total - 1))


def shift_day_index(index, total_days, day_delta):
    base = clamp_day_index(index, total_days)
    return clamp_day_index(base + _to_int(day_delta, default=0), total_days)


def start_day_index(total_days):
    _ = normalize_total_days(total_days)
    return 0


def end_day_index(total_days):
    total = normalize_total_days(total_days)
    return max(0, total - 1)


def navigation_button_state(index, total_days):
    total = normalize_total_days(total_days)
    idx = clamp_day_index(index, total)
    can_prev = bool(total > 0 and idx > 0)
    can_next = bool(total > 0 and idx < (total - 1))
    return {
        "index": idx,
        "total_days": total,
        "can_first": can_prev,
        "can_prev_30": can_prev,
        "can_prev_1": can_prev,
        "can_next_1": can_next,
        "can_next_30": can_next,
        "can_last": can_next,
    }
