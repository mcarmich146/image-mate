#!/usr/bin/env python3
"""Static contract check that opening/binding the dock cannot trigger APIs."""

from __future__ import annotations

import ast
from pathlib import Path


def _method(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing method: {name}")


def _calls(method: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(method):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
    return names


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[1]
    package_root = plugin_root / "image_mate_qgis_plugin"
    mixin_path = package_root / "mixins" / "search_streaming.py"
    source_path = package_root / "services" / "source_service.py"

    mixin_tree = ast.parse(mixin_path.read_text(encoding="utf-8"), filename=str(mixin_path))
    source_tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    bind_calls = _calls(_method(mixin_tree, "_bind_dock_data"))
    if "_on_source_changed" not in bind_calls:
        raise AssertionError("dock binding no longer initializes local source state")

    source_change_calls = _calls(_method(mixin_tree, "_on_source_changed"))
    forbidden = {
        "list_collections",
        "handle_tasking_refresh_request",
        "handle_mosaic_refresh_projects_request",
        "handle_monitoring_refresh_request",
        "_backend_streaming_available",
        "_backend_json_request",
    }
    leaked = sorted(source_change_calls & forbidden)
    if leaked:
        raise AssertionError(f"source binding can still trigger API work: {leaked}")
    if "default_collections" not in source_change_calls:
        raise AssertionError("source binding must use local collection defaults")

    default_calls = _calls(_method(source_tree, "default_collections"))
    network_primitives = {"get", "post", "request", "urlopen", "auth_headers"}
    leaked = sorted(default_calls & network_primitives)
    if leaked:
        raise AssertionError(f"local collection defaults contain network primitives: {leaked}")

    print("startup_no_api_calls_smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
