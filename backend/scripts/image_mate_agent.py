#!/usr/bin/env python3
"""Backend-independent Image-Mate project/site/context CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.agent_projects import AgentProjectService, load_json, load_sites  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.monitoring_store import MonitoringStore  # noqa: E402


def _service(args: argparse.Namespace) -> AgentProjectService:
    db_path = Path(args.db).expanduser().resolve() if args.db else settings.monitoring_db_path
    return AgentProjectService(MonitoringStore(db_path))


def _sources(path: str | None) -> list[dict]:
    if not path:
        return []
    payload = load_json(path)
    if not isinstance(payload, list):
        raise ValueError("Sources file must contain a JSON list")
    return payload


def _context(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).expanduser().resolve().read_text(encoding="utf-8")


def _create(args: argparse.Namespace) -> int:
    service = _service(args)
    sites = load_sites(args.sites_file)
    project: dict = {
        "project_id": args.project_id,
        "name": args.name,
        "status": args.status,
        "enabled": bool(args.enabled),
        "owner": args.owner,
        "sources": load_json(args.sources_config) if args.sources_config else [],
    }
    if args.geometry_file:
        geometry_payload = load_json(args.geometry_file)
        project["geometry"] = geometry_payload.get("geometry", geometry_payload) if isinstance(geometry_payload, dict) else geometry_payload
    result = service.create_project(
        project,
        sites,
        context_text=_context(args.context_file),
        context_sources=_sources(args.context_sources_file),
    )
    print(json.dumps({"created": True, "project": result}, indent=2, ensure_ascii=False))
    return 0


def _sync(args: argparse.Namespace) -> int:
    service = _service(args)
    result = service.sync_project(
        args.project_id,
        load_sites(args.sites_file),
        context_text=_context(args.context_file),
        context_sources=_sources(args.context_sources_file),
    )
    print(json.dumps({"synced": True, "project": result}, indent=2, ensure_ascii=False))
    return 0


def _list(args: argparse.Namespace) -> int:
    service = _service(args)
    rows = service.list_projects()
    print(json.dumps({"count": len(rows), "projects": rows}, indent=2, ensure_ascii=False))
    return 0


def _show(args: argparse.Namespace) -> int:
    result = _service(args).get_project(args.project_id, include_context=args.include_context)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _sites(args: argparse.Namespace) -> int:
    result = _service(args).list_sites(args.project_id)
    print(json.dumps({"count": len(result), "sites": result}, indent=2, ensure_ascii=False))
    return 0


def _context_command(args: argparse.Namespace) -> int:
    service = _service(args)
    if args.context_action == "show":
        result = service.get_context(args.project_id, history=args.history)
    else:
        result = service.import_context(args.project_id, _context(args.context_file) or "", _sources(args.context_sources_file))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", help="Monitoring SQLite path; defaults to Image-Mate settings")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="image-mate-agent")
    commands = parser.add_subparsers(dest="command", required=True)

    project = commands.add_parser("project")
    project_commands = project.add_subparsers(dest="project_action", required=True)

    create = project_commands.add_parser("create")
    _common(create)
    create.add_argument("--project-id")
    create.add_argument("--name", required=True)
    create.add_argument("--status", choices=["draft", "approved", "active", "paused", "archived"], default="draft")
    create.add_argument("--enabled", action="store_true")
    create.add_argument("--owner", default="local-operator")
    create.add_argument("--sites-file", required=True)
    create.add_argument("--geometry-file")
    create.add_argument("--context-file")
    create.add_argument("--context-sources-file")
    create.add_argument("--sources-config")
    create.set_defaults(func=_create)

    sync = project_commands.add_parser("sync")
    _common(sync)
    sync.add_argument("--project-id", required=True)
    sync.add_argument("--sites-file", required=True)
    sync.add_argument("--context-file")
    sync.add_argument("--context-sources-file")
    sync.set_defaults(func=_sync)

    listing = project_commands.add_parser("list")
    _common(listing)
    listing.set_defaults(func=_list)

    show = project_commands.add_parser("show")
    _common(show)
    show.add_argument("--project-id", required=True)
    show.add_argument("--include-context", action="store_true")
    show.set_defaults(func=_show)

    sites = project_commands.add_parser("sites")
    _common(sites)
    sites.add_argument("--project-id", required=True)
    sites.set_defaults(func=_sites)

    context = project_commands.add_parser("context")
    _common(context)
    context_commands = context.add_subparsers(dest="context_action", required=True)
    context_show = context_commands.add_parser("show")
    context_show.add_argument("--project-id", required=True)
    context_show.add_argument("--history", action="store_true")
    context_show.set_defaults(func=_context_command)
    context_import = context_commands.add_parser("import")
    context_import.add_argument("--project-id", required=True)
    context_import.add_argument("--context-file", required=True)
    context_import.add_argument("--context-sources-file")
    context_import.set_defaults(func=_context_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"image-mate-agent error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
