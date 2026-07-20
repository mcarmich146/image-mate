#!/usr/bin/env python3
"""Create a dated QGIS plugin design/implementation plan document."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "change"


def title_from_slug(slug: str) -> str:
    return " ".join(token.capitalize() for token in slug.split("-"))


def build_template(topic_slug: str, day: str) -> str:
    title = title_from_slug(topic_slug)
    return f"""# {title} Design and Implementation Plan

- Date: {day}
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

## Existing Reusable Components

## Proposed Backend Changes

## UI Wiring Changes (Minimal)

## Implementation Steps

## Terminal-Only Test Plan

## Risks and Rollback
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a design/implementation plan under qgis_plugin/docs/<YYYY-MM-DD>/."
    )
    parser.add_argument(
        "--topic",
        required=True,
        help="Plan topic title or slug (for example: simulation-cache-hardening).",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root path (defaults to current directory).",
    )
    parser.add_argument(
        "--date",
        dest="day",
        default=None,
        help="Date folder in YYYY-MM-DD (defaults to local today).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing file if it already exists.",
    )
    args = parser.parse_args()

    topic_slug = slugify(args.topic)
    day = args.day or date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        print("[ERROR] --date must be YYYY-MM-DD", file=sys.stderr)
        return 2

    root = Path(args.root).resolve()
    docs_dir = root / "qgis_plugin" / "docs" / day
    docs_dir.mkdir(parents=True, exist_ok=True)

    output = docs_dir / f"{topic_slug}-plan.md"
    if output.exists() and not args.force:
        print(f"[ERROR] File already exists: {output}", file=sys.stderr)
        print("Use --force to overwrite.", file=sys.stderr)
        return 1

    output.write_text(build_template(topic_slug, day), encoding="utf-8")
    print(f"[OK] Wrote: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
