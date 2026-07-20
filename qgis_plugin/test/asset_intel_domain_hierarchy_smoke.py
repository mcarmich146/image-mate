#!/usr/bin/env python3
"""Smoke checks for Asset Intel domain hierarchy normalization."""

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

    from image_mate_qgis_plugin.services.asset_intel_service import (  # noqa: PLC0415
        normalize_domain_hierarchy,
        split_domain_tokens,
    )

    _assert_equal(
        split_domain_tokens("Naval, Surface Combatant, Destroyer"),
        ["Naval", "Surface Combatant", "Destroyer"],
        "split_three_tokens",
    )
    _assert_equal(
        split_domain_tokens("Naval, naval,  Surface Combatant ,"),
        ["Naval", "Surface Combatant"],
        "split_dedup_and_trim",
    )

    normalized_explicit = normalize_domain_hierarchy("Naval", "Surface Combatant", "Destroyer")
    _assert_equal(
        normalized_explicit["domain"],
        "Naval, Surface Combatant, Destroyer",
        "explicit_domain_string",
    )
    _assert_equal(normalized_explicit["main_domain"], "Naval", "explicit_main")
    _assert_equal(normalized_explicit["sub_domain_1"], "Surface Combatant", "explicit_sub1")
    _assert_equal(normalized_explicit["sub_domain_2"], "Destroyer", "explicit_sub2")

    normalized_main_only = normalize_domain_hierarchy("Naval, Submarine")
    _assert_equal(
        normalized_main_only["tokens"],
        ["Naval", "Submarine"],
        "main_only_split_path",
    )

    normalized_fallback = normalize_domain_hierarchy(
        None,
        None,
        None,
        fallback_domain="Land, Armored, MBT",
    )
    _assert_equal(
        normalized_fallback["tokens"],
        ["Land", "Armored", "MBT"],
        "fallback_tokens",
    )

    normalized_clear = normalize_domain_hierarchy("", "", "")
    _assert_equal(normalized_clear["domain"], "", "explicit_clear_domain")
    _assert_equal(normalized_clear["tokens"], [], "explicit_clear_tokens")

    print("asset_intel_domain_hierarchy_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
