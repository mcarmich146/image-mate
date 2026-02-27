#!/usr/bin/env python3
"""
Infer documentation updates from changed file paths.

Example:
    git diff --name-only | py -3 .codex/skills/documentation-engineer/scripts/derive_doc_updates.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Dict, List


def normalize_path(raw: str) -> str:
    path = raw.strip().replace("\\", "/")
    while "//" in path:
        path = path.replace("//", "/")
    return path.strip("/")


def is_doc_path(path: str) -> bool:
    lower = path.lower()
    return (
        lower.startswith("docs/")
        or lower.endswith(".md")
        or lower.endswith(".mdx")
        or lower.endswith(".rst")
        or lower.endswith(".adoc")
    )


def unique_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    unique_values = []
    for value in values:
        if value not in seen:
            unique_values.append(value)
            seen.add(value)
    return unique_values


def bucket_paths(paths: List[str]) -> Dict[str, List[str]]:
    buckets = defaultdict(list)
    for path in paths:
        lower = path.lower()
        if is_doc_path(path):
            buckets["docs"].append(path)
        if lower.startswith("backend/"):
            buckets["backend"].append(path)
        if lower.startswith("frontend/"):
            buckets["frontend"].append(path)
        if lower.startswith("ml/"):
            buckets["ml"].append(path)
        if lower.startswith("qgis_plugin/"):
            buckets["qgis_plugin"].append(path)
        if lower.startswith(".codex/skills/"):
            buckets["skills"].append(path)
        if (
            lower.startswith("test/")
            or "/test/" in lower
            or lower.endswith("_test.py")
            or lower.endswith(".spec.ts")
            or lower.endswith(".spec.tsx")
        ):
            buckets["tests"].append(path)
        if any(token in lower for token in ("migration", "alembic", "schema", "model", "seed", "dataset")):
            buckets["data"].append(path)
        if any(
            token in lower
            for token in ("/api/", "openapi", "swagger", "/routes/", "/controller", "endpoint")
        ):
            buckets["api"].append(path)
        if (
            lower.startswith(".github/workflows/")
            or lower.endswith("dockerfile")
            or lower in ("docker-compose.yml", "docker-compose.yaml")
            or lower.endswith("requirements.txt")
            or lower.endswith("pyproject.toml")
            or lower.endswith("package.json")
            or lower.endswith("package-lock.json")
            or lower.endswith("pnpm-lock.yaml")
            or lower.endswith(".env-template")
        ):
            buckets["ops"].append(path)
    return buckets


def trim_examples(paths: List[str], max_examples: int) -> List[str]:
    examples = unique_preserve_order(paths)
    if len(examples) <= max_examples:
        return examples
    return examples[:max_examples]


def recommendation(
    title: str,
    target: str,
    reason: str,
    triggered_by: List[str],
    required: bool,
    max_examples: int,
) -> Dict[str, object]:
    return {
        "title": title,
        "target": target,
        "reason": reason,
        "triggered_by": trim_examples(triggered_by, max_examples),
        "required": required,
    }


def infer_recommendations(paths: List[str], max_examples: int) -> Dict[str, object]:
    buckets = bucket_paths(paths)
    doc_paths = unique_preserve_order(buckets.get("docs", []))
    non_doc_paths = [path for path in paths if not is_doc_path(path)]

    recommendations = []
    warnings = []

    if non_doc_paths:
        recommendations.append(
            recommendation(
                title="Create or update a dated engineering note",
                target="docs/YYYYMMDD/<topic>_engineering_note.md",
                reason="Every non-trivial code or config change should leave a durable dated record.",
                triggered_by=non_doc_paths,
                required=True,
                max_examples=max_examples,
            )
        )

    if buckets.get("backend") or buckets.get("frontend") or buckets.get("ml"):
        component_triggers = []
        component_triggers.extend(buckets.get("backend", []))
        component_triggers.extend(buckets.get("frontend", []))
        component_triggers.extend(buckets.get("ml", []))
        recommendations.append(
            recommendation(
                title="Update component and architecture docs",
                target="README.md and docs/* architecture/module notes",
                reason="Behavior and design changes must be reflected in canonical component documentation.",
                triggered_by=component_triggers,
                required=True,
                max_examples=max_examples,
            )
        )

    if buckets.get("qgis_plugin"):
        recommendations.append(
            recommendation(
                title="Update QGIS plugin dated docs",
                target="qgis_plugin/docs/YYYY-MM-DD/<topic>.md",
                reason="Plugin workflows use dated docs to track design and implementation decisions.",
                triggered_by=buckets["qgis_plugin"],
                required=True,
                max_examples=max_examples,
            )
        )

    if buckets.get("api"):
        recommendations.append(
            recommendation(
                title="Update API contract documentation",
                target="API spec docs, endpoint behavior notes, and request/response examples",
                reason="API shape changes require explicit contract updates for consumers.",
                triggered_by=buckets["api"],
                required=True,
                max_examples=max_examples,
            )
        )

    if buckets.get("data"):
        recommendations.append(
            recommendation(
                title="Update schema and data model docs",
                target="Schema references, migration notes, and data assumptions",
                reason="Data structure changes can break downstream logic unless documented clearly.",
                triggered_by=buckets["data"],
                required=True,
                max_examples=max_examples,
            )
        )

    if buckets.get("ops"):
        recommendations.append(
            recommendation(
                title="Update setup and operations documentation",
                target="Runbooks, deployment notes, and environment setup docs",
                reason="Operational and dependency changes need reproducible setup and rollback guidance.",
                triggered_by=buckets["ops"],
                required=True,
                max_examples=max_examples,
            )
        )

    if buckets.get("skills"):
        recommendations.append(
            recommendation(
                title="Update skill references and examples",
                target=".codex/skills/<skill>/SKILL.md and related resources",
                reason="Skill behavior changes require synchronized procedural guidance and templates.",
                triggered_by=buckets["skills"],
                required=True,
                max_examples=max_examples,
            )
        )

    if non_doc_paths and not doc_paths:
        warnings.append(
            "Non-documentation files changed but no documentation files changed."
        )

    payload = {
        "counts": {
            "changed_files": len(paths),
            "doc_files": len(doc_paths),
            "non_doc_files": len(non_doc_paths),
        },
        "recommendations": recommendations,
        "warnings": warnings,
    }
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Infer likely documentation updates from changed file paths.",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Changed file path. Repeat for multiple files. If omitted, read stdin lines.",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=5,
        help="Max trigger examples shown per recommendation. Default: 5",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    return parser.parse_args()


def read_input_paths(explicit_paths: List[str]) -> List[str]:
    raw_paths = list(explicit_paths)
    if not raw_paths:
        raw_paths.extend(sys.stdin.read().splitlines())
    normalized = [normalize_path(item) for item in raw_paths if normalize_path(item)]
    return unique_preserve_order(normalized)


def print_text_report(payload: Dict[str, object]) -> None:
    counts = payload["counts"]
    recommendations = payload["recommendations"]
    warnings = payload["warnings"]

    print(f"Changed files: {counts['changed_files']}")
    print(f"Documentation files changed: {counts['doc_files']}")
    print(f"Non-documentation files changed: {counts['non_doc_files']}")

    if recommendations:
        print("\nRecommended documentation updates:")
        for idx, rec in enumerate(recommendations, start=1):
            label = "[Required]" if rec["required"] else "[Recommended]"
            examples = ", ".join(rec["triggered_by"]) if rec["triggered_by"] else "(none)"
            print(f"{idx}. {label} {rec['title']}")
            print(f"   Target: {rec['target']}")
            print(f"   Reason: {rec['reason']}")
            print(f"   Triggered by: {examples}")
    else:
        print("\nNo documentation updates inferred from the provided paths.")

    if warnings:
        print("\nCoverage warnings:")
        for warning in warnings:
            print(f"- {warning}")


def main() -> int:
    args = parse_args()
    paths = read_input_paths(args.path)

    if not paths:
        print("[ERROR] No file paths provided via --path or stdin.", file=sys.stderr)
        return 1
    if args.max_examples < 1:
        print("[ERROR] --max-examples must be at least 1.", file=sys.stderr)
        return 1

    payload = infer_recommendations(paths, max_examples=args.max_examples)

    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        print()
    else:
        print_text_report(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
