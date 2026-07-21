#!/usr/bin/env python3
"""Reject developer-specific usernames in QGIS plugin text artifacts."""

from __future__ import annotations

from pathlib import Path


TEXT_SUFFIXES = {
    ".bat",
    ".csv",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".txt",
    ".yaml",
    ".yml",
}


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    violations = []
    for path in plugin_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if ("jo" + ".man") in text.casefold():
            violations.append(str(path.relative_to(plugin_root)))
    if violations:
        raise AssertionError(f"developer-specific username remains in: {violations}")
    print("user_path_portability_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
