#!/usr/bin/env python3
"""Validate that changed files stay within qgis_plugin/."""

from __future__ import annotations

import argparse
import sys
from pathlib import PurePosixPath


def normalize_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def allowed_path(path: str, allowed_prefixes: list[str]) -> bool:
    pure = str(PurePosixPath(path))
    return any(pure == prefix or pure.startswith(prefix + "/") for prefix in allowed_prefixes)


def read_files(args: list[str]) -> list[str]:
    if args:
        return [line for line in args if line.strip()]
    return [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail if any changed path falls outside allowed prefixes."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Changed file paths. If omitted, read newline-delimited paths from stdin.",
    )
    parser.add_argument(
        "--allow",
        action="append",
        default=["qgis_plugin"],
        help="Allowed top-level prefix. Repeat to allow multiple prefixes.",
    )
    args = parser.parse_args()

    allowed = [normalize_path(prefix).rstrip("/") for prefix in args.allow if prefix.strip()]
    files = [normalize_path(path) for path in read_files(args.files)]

    if not files:
        print("[OK] No files provided.")
        return 0

    blocked = [path for path in files if not allowed_path(path, allowed)]
    if blocked:
        print("[ERROR] Out-of-scope file changes detected:")
        for path in blocked:
            print(f" - {path}")
        print(f"[HINT] Allowed prefixes: {', '.join(allowed)}")
        return 1

    print(f"[OK] All {len(files)} path(s) are within allowed scope: {', '.join(allowed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
