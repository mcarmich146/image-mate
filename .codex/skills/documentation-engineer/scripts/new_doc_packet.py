#!/usr/bin/env python3
"""
Scaffold a dated engineering note under docs/YYYYMMDD/.

Example:
    py -3 .codex/skills/documentation-engineer/scripts/new_doc_packet.py --topic "tile streaming fix"
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path


DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "templates"
    / "engineering_note_template.md"
)


def parse_date(raw: str | None) -> dt.date:
    if not raw:
        return dt.date.today()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {raw}")


def slugify(topic: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", topic.strip().lower())
    normalized = normalized.strip("_")
    return normalized or "untitled"


def render_template(template: str, topic: str, slug: str, date_value: dt.date) -> str:
    replacements = {
        "{{TOPIC_TITLE}}": topic.strip(),
        "{{TOPIC_SLUG}}": slug,
        "{{DATE_ISO}}": date_value.isoformat(),
        "{{DATE_COMPACT}}": date_value.strftime("%Y%m%d"),
        "{{OWNER}}": os.environ.get("USERNAME", "owner"),
    }
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    return rendered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create docs/YYYYMMDD/<topic>_engineering_note.md from template.",
    )
    parser.add_argument("--topic", required=True, help="Work item topic for title/file slug.")
    parser.add_argument(
        "--date",
        help="Date override in YYYYMMDD or YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--docs-root",
        default="docs",
        help="Base docs directory where dated folder is created. Default: docs",
    )
    parser.add_argument(
        "--template",
        help="Template file path. Default is assets/templates/engineering_note_template.md",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite output file if it already exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        date_value = parse_date(args.date)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    topic = args.topic.strip()
    if not topic:
        print("[ERROR] --topic cannot be blank.", file=sys.stderr)
        return 1

    slug = slugify(topic)
    docs_root = Path(args.docs_root)
    day_dir = docs_root / date_value.strftime("%Y%m%d")
    output_path = day_dir / f"{slug}_engineering_note.md"

    template_path = Path(args.template) if args.template else DEFAULT_TEMPLATE_PATH
    if not template_path.exists():
        print(f"[ERROR] Template not found: {template_path}", file=sys.stderr)
        return 1

    if output_path.exists() and not args.overwrite:
        print(
            f"[ERROR] Output exists: {output_path}. Use --overwrite to replace it.",
            file=sys.stderr,
        )
        return 1

    template_content = template_path.read_text(encoding="utf-8")
    rendered = render_template(template_content, topic, slug, date_value)

    day_dir.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    print(f"[OK] Created: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
