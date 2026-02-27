#!/usr/bin/env python3
"""Generate terminal-first low-bandwidth test checklist from changed files."""

from __future__ import annotations

import argparse
import sys
from pathlib import PurePosixPath


CATEGORY_RULES = [
    ("services", "qgis_plugin/image_mate_qgis_plugin/services/"),
    ("simulation", "qgis_plugin/image_mate_qgis_plugin/simulation/"),
    ("workflow", "qgis_plugin/image_mate_qgis_plugin/workflow_execution/"),
    ("workflow", "qgis_plugin/image_mate_qgis_plugin/workflow_plugins/"),
    ("clients", "qgis_plugin/image_mate_qgis_plugin/clients/"),
    ("controllers", "qgis_plugin/image_mate_qgis_plugin/controllers/"),
    ("ui", "qgis_plugin/image_mate_qgis_plugin/ui/"),
    ("tests", "qgis_plugin/test/"),
    ("docs", "qgis_plugin/docs/"),
]


CATEGORY_CHECKS = {
    "services": [
        "Assert input validation and explicit failure messages with non-zero exit.",
        "Assert deterministic output schema and stable ordering for sample payloads.",
        "Assert side effects (cache/db/file writes) through CLI-readable artifacts.",
    ],
    "simulation": [
        "Run a short smoke scenario with tiny AOI/time window and assert completion state.",
        "Assert progress and summary fields from CLI output or persisted report file.",
        "Assert deterministic results when re-running same fixture.",
    ],
    "workflow": [
        "Run workflow path in headless mode and assert task ordering/status transitions.",
        "Assert plugin execution contracts (required params, output fields, error path).",
        "Assert idempotent behavior for repeated runs where applicable.",
    ],
    "clients": [
        "Stub remote calls and assert request payload/headers without large downloads.",
        "Assert retry/backoff and error mapping through logs or structured output.",
        "Assert timeout handling and no unbounded blocking path.",
    ],
    "controllers": [
        "Assert controller-to-service delegation and argument normalization.",
        "Assert invalid input handling and clear, parseable error result.",
        "Assert no dependency on GUI state for core logic.",
    ],
    "ui": [
        "Assert UI handlers delegate logic to backend services/workers.",
        "Add backend tests for moved/extracted logic rather than visual UI checks.",
        "Assert CLI probes still cover changed behavior without opening QGIS GUI.",
    ],
    "tests": [
        "Run existing smoke runners and ensure fast pass/fail signals.",
        "Keep fixtures small and avoid large imagery unless explicitly required.",
        "Emit machine-readable summaries (JSON/text) for CI and terminal use.",
    ],
    "docs": [
        "Confirm design/implementation plan exists under qgis_plugin/docs/<YYYY-MM-DD>/.",
        "Link each changed behavior to at least one terminal-verifiable check.",
    ],
    "other": [
        "Derive at least one CLI contract test for each changed module.",
        "Confirm low-bandwidth assumptions (small fixtures, minimal network).",
    ],
}


def normalize(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return str(PurePosixPath(normalized))


def read_paths(cli_paths: list[str]) -> list[str]:
    if cli_paths:
        return [normalize(path) for path in cli_paths if path.strip()]
    return [normalize(line) for line in sys.stdin.read().splitlines() if line.strip()]


def classify(path: str) -> str:
    for category, prefix in CATEGORY_RULES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return category
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate terminal-only low-bandwidth test checklist from changed files."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Changed paths. If omitted, read newline-delimited paths from stdin.",
    )
    args = parser.parse_args()

    paths = read_paths(args.paths)
    if not paths:
        print("# Terminal Test Checklist")
        print("")
        print("No changed files provided.")
        return 0

    categories: list[str] = []
    seen: set[str] = set()
    for path in paths:
        category = classify(path)
        if category not in seen:
            categories.append(category)
            seen.add(category)

    print("# Terminal Test Checklist")
    print("")
    print(f"Generated from {len(paths)} changed path(s).")
    print("")
    print("## Global Checks")
    print("- Keep all checks terminal-executable with clear non-zero exit on failure.")
    print("- Use low-bandwidth fixtures and avoid GUI/image inspection as primary assertion.")
    print("- Prefer deterministic outputs (JSON/text/log fields) over visual comparisons.")

    for category in categories:
        checks = CATEGORY_CHECKS.get(category, CATEGORY_CHECKS["other"])
        print("")
        print(f"## {category.capitalize()} Checks")
        for check in checks:
            print(f"- [ ] {check}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
