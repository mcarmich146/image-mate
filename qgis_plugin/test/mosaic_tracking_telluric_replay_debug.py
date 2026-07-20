#!/usr/bin/env python3
"""Replay Telluric preview parameters from mosaic tracking logs for debugging."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from qgis_plugin.image_mate_qgis_plugin.clients.satellogic_client import SatellogicClient


_PREVIEW_LOADED_RX = re.compile(
    r"preview_loaded project=(?P<project>[^\s]+)\s+tile=(?P<tile>[^\s]+)\s+collection_id=(?P<collection>[^\s]+)"
)
_EMPTY_TILE_RX = re.compile(
    r"served empty telluric tile zxy=(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)\s+status=(?P<status>\d+)\s+"
    r"scene=(?P<scene>[^\s]+)\s+raster=(?P<raster>[^\s]+)"
)


@dataclass
class LogCase:
    collection_id: str
    z: int
    x: int
    y: int
    scene_id: str
    raster_name: str


def _campaign_logs(campaign_root: Path) -> list[Path]:
    log_dir = campaign_root / "logs"
    logs = sorted(log_dir.glob("image_mate_qgis_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        raise RuntimeError(f"No campaign logs found under: {log_dir}")
    return logs


def _parse_log_cases(log_path: Path, project_id: str, max_cases: int) -> list[LogCase]:
    cases: list[LogCase] = []
    seen: set[tuple[str, int, int, int, str, str]] = set()
    active_collection = ""
    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            loaded = _PREVIEW_LOADED_RX.search(line)
            if loaded:
                if str(loaded.group("project") or "").strip() == project_id:
                    active_collection = str(loaded.group("collection") or "").strip()
                continue
            empty = _EMPTY_TILE_RX.search(line)
            if not empty or not active_collection:
                continue
            case = LogCase(
                collection_id=active_collection,
                z=int(empty.group("z")),
                x=int(empty.group("x")),
                y=int(empty.group("y")),
                scene_id=str(empty.group("scene") or "").strip(),
                raster_name=str(empty.group("raster") or "").strip(),
            )
            dedupe = (
                case.collection_id,
                case.z,
                case.x,
                case.y,
                case.scene_id,
                case.raster_name,
            )
            if dedupe in seen:
                continue
            seen.add(dedupe)
            cases.append(case)
            if len(cases) >= max_cases:
                break
    return cases


def _resolve_contract_id(db_path: Path, collection_id: str) -> str:
    if not db_path.exists():
        return ""
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT request_payload_json FROM mosaic_attempt WHERE collection_id=? ORDER BY id DESC LIMIT 1",
            (collection_id,),
        ).fetchone()
    except Exception:
        return ""
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not row or not row[0]:
        return ""
    try:
        payload = json.loads(str(row[0]))
    except Exception:
        return ""
    return str(payload.get("contract_id") or "").strip()


def _parse_scene_raster_from_visual_href(href: str) -> tuple[str, str]:
    raw = str(href or "").strip()
    if not raw:
        return "", ""
    parsed = urlparse(raw)
    parts = [part for part in str(parsed.path or "").split("/") if part]
    scene_id = ""
    if "deliverables" in parts:
        idx = parts.index("deliverables")
        if idx + 1 < len(parts):
            scene_id = str(parts[idx + 1] or "").strip()

    raster_name = ""
    params = parse_qs(parsed.query or "", keep_blank_values=False)
    for key in ("s", "url", "href"):
        for value in params.get(key) or []:
            nested = str(value or "").strip()
            if not nested:
                continue
            nested_name = Path(urlparse(nested).path).name
            if nested_name.lower().endswith((".tif", ".tiff")):
                raster_name = nested_name
                break
        if raster_name:
            break
    return scene_id, raster_name


def _telluric_get(
    *,
    headers: dict[str, str],
    scene_id: str,
    raster_name: str,
    z: int,
    x: int,
    y: int,
) -> requests.Response:
    url = f"https://api.satellogic.com/telluric/scenes/{scene_id}/rasters/{raster_name}/get_tile/"
    return requests.get(url, headers=headers, params={"z": z, "x": x, "y": y}, timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default="thai_caas", help="Campaign uid (default: thai_caas)")
    parser.add_argument("--project", default="vancouver_mosaic", help="Mosaic project id (default: vancouver_mosaic)")
    parser.add_argument("--base-dir", default=str(Path.home() / "ImageMateCampaigns" / "campaigns"))
    parser.add_argument("--log-path", default="", help="Explicit log path; defaults to latest campaign log")
    parser.add_argument("--max-cases", type=int, default=6)
    parser.add_argument("--save-dir", default="", help="Optional directory to store successful replay PNGs")
    args = parser.parse_args()

    campaign_root = Path(args.base_dir).expanduser().resolve() / str(args.campaign).strip().lower()
    if not campaign_root.exists():
        raise RuntimeError(f"Campaign root not found: {campaign_root}")
    project_root = campaign_root / "collections" / "mosaic" / str(args.project).strip()
    if not project_root.exists():
        raise RuntimeError(f"Mosaic project root not found: {project_root}")

    project_key = str(args.project).strip()
    if args.log_path:
        log_candidates = [Path(args.log_path).expanduser().resolve()]
    else:
        log_candidates = [path for path in _campaign_logs(campaign_root) if path.stat().st_size > 0]
    if not log_candidates:
        raise RuntimeError("No non-empty campaign logs found.")

    log_path = None
    cases: list[LogCase] = []
    for candidate in log_candidates:
        parsed = _parse_log_cases(log_path=candidate, project_id=project_key, max_cases=max(1, int(args.max_cases)))
        if parsed:
            log_path = candidate
            cases = parsed
            break
    if not cases or log_path is None:
        raise RuntimeError("No Telluric empty-tile cases found in available logs for requested project.")

    print(f"log: {log_path}")
    print(f"cases: {len(cases)}")

    save_dir = Path(args.save_dir).expanduser().resolve() if args.save_dir else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)

    client = SatellogicClient()
    ok_count = 0
    fail_count = 0

    for idx, case in enumerate(cases, start=1):
        db_path = project_root / "mosaic_tracking.sqlite3"
        contract_id = _resolve_contract_id(db_path, case.collection_id)
        if not contract_id:
            print(f"\n[{idx}] collection={case.collection_id} missing contract_id; skipping")
            fail_count += 1
            continue

        headers = client.auth_headers(contract_id=contract_id, prefer_oauth=True, ignore_static_bearer=True)
        print(
            f"\n[{idx}] collection={case.collection_id} zxy={case.z}/{case.x}/{case.y} "
            f"log_scene={case.scene_id} log_raster={case.raster_name}"
        )

        log_response = _telluric_get(
            headers=headers,
            scene_id=case.scene_id,
            raster_name=case.raster_name,
            z=case.z,
            x=case.x,
            y=case.y,
        )
        log_ctype = str(log_response.headers.get("Content-Type") or "").split(";")[0].strip()
        log_body = (log_response.text or "")[:180].replace("\n", " ")
        print(
            "  log_replay:"
            f" status={log_response.status_code} ctype={log_ctype or '--'} body={log_body}"
        )

        deliverables_payload = client.list_order_deliverables(case.collection_id, contract_id=contract_id)
        deliverables = deliverables_payload.get("results") if isinstance(deliverables_payload, dict) else []
        deliverables = [row for row in (deliverables or []) if isinstance(row, dict)]
        delivered_rows = [row for row in deliverables if str(row.get("status") or "").strip().upper() == "DELIVERED"]
        candidate_rows = delivered_rows or deliverables
        if not candidate_rows:
            print("  deliverables: none")
            fail_count += 1
            continue

        first = candidate_rows[0]
        visual_href = str(((first.get("assets") or {}).get("visual") or {}).get("href") or "").strip()
        fixed_scene, fixed_raster = _parse_scene_raster_from_visual_href(visual_href)
        if not fixed_scene or not fixed_raster:
            print("  deliverables: could not parse scene/raster from visual href")
            fail_count += 1
            continue
        fixed_response = _telluric_get(
            headers=headers,
            scene_id=fixed_scene,
            raster_name=fixed_raster,
            z=case.z,
            x=case.x,
            y=case.y,
        )
        fixed_ctype = str(fixed_response.headers.get("Content-Type") or "").split(";")[0].strip()
        print(
            "  deliverable_replay:"
            f" scene={fixed_scene} raster={fixed_raster} "
            f"status={fixed_response.status_code} ctype={fixed_ctype or '--'} bytes={len(fixed_response.content or b'')}"
        )
        if fixed_response.status_code == 200 and fixed_ctype == "image/png" and fixed_response.content:
            ok_count += 1
            if save_dir:
                out_path = save_dir / (
                    f"collection_{case.collection_id}_z{case.z}_x{case.x}_y{case.y}.png"
                )
                out_path.write_bytes(fixed_response.content)
                print(f"  saved_png: {out_path}")
        else:
            fail_count += 1

    print(f"\nsummary: ok={ok_count} fail={fail_count}")
    if ok_count == 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
