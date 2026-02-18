#!/usr/bin/env python3
"""Deterministic gap/seam checker for a specific L1D SR outcome on a canvas tile window."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import math
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import requests

try:
    from PIL import Image
    import numpy as np
except Exception as exc:
    raise SystemExit(f"Pillow/numpy are required for gap checks: {exc}") from exc


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
QGIS_PLUGIN_ROOT = WORKSPACE_ROOT / "qgis_plugin"
if str(QGIS_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(QGIS_PLUGIN_ROOT))

from image_mate_qgis_plugin.clients.satellogic_client import SatellogicClient
from image_mate_qgis_plugin.services.local_tile_proxy import LocalTileProxy
from image_mate_qgis_plugin.services.source_service import SourceService


def _create_square_aoi(center_lat: float, center_lon: float, size_km: float) -> dict:
    lat_offset = (size_km / 2.0) / 111.0
    lon_offset = (size_km / 2.0) / (111.0 * max(0.01, math.cos(math.radians(center_lat))))
    return {
        "type": "Polygon",
        "coordinates": [[
            [center_lon - lon_offset, center_lat - lat_offset],
            [center_lon + lon_offset, center_lat - lat_offset],
            [center_lon + lon_offset, center_lat + lat_offset],
            [center_lon - lon_offset, center_lat + lat_offset],
            [center_lon - lon_offset, center_lat - lat_offset],
        ]],
    }


def _lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2 ** int(zoom)
    x = int((lon + 180.0) / 360.0 * n)
    clamped_lat = max(min(lat, 85.05112878), -85.05112878)
    lat_rad = math.radians(clamped_lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return x, y


def _extract_source_url(item: dict) -> str:
    assets = item.get("assets") or {}
    href = ""
    for key in ("visual_fullres", "visual", "analytic"):
        asset = assets.get(key)
        if isinstance(asset, dict) and asset.get("href"):
            href = str(asset.get("href") or "").strip()
            break
    if not href:
        return ""
    parsed = urlparse(href)
    source = str((parse_qs(parsed.query or {}).get("s") or [""])[0]).strip()
    if source.startswith("s3://"):
        return source
    return href


def _build_source_service(contract_id: str | None) -> SourceService:
    cfg = SimpleNamespace(
        satellogic_contract_id=str(contract_id or "").strip(),
        cdse_wmts_base_url="",
        cdse_wmts_instance_id="",
        cdse_wmts_layer_id="",
        cdse_enabled=False,
        satellogic_auth_mode="oauth_client_credentials",
        satellogic_authcfg_id="",
        cdse_authcfg_id="",
    )
    return SourceService(cfg)


def _fetch_outcome_sources(
    *,
    client: SatellogicClient,
    outcome_id: str,
    center_lat: float,
    center_lon: float,
    source_aoi_size_km: float,
    start_date: str,
    end_date: str,
    contract_id: str | None,
) -> list[str]:
    geom = _create_square_aoi(center_lat=center_lat, center_lon=center_lon, size_km=source_aoi_size_km)
    rows = client.search(
        geometry=geom,
        start_date=start_date,
        end_date=end_date,
        collection_id="l1d-sr",
        contract_id=contract_id,
        limit=500,
        max_cloud_cover=40,
    )
    sources: list[str] = []
    seen: set[str] = set()
    for row in rows or []:
        props = row.get("properties") or {}
        if str(props.get("satl:outcome_id") or "").strip() != outcome_id:
            continue
        source = _extract_source_url(row)
        if source and source not in seen:
            seen.add(source)
            sources.append(source)
    return sources


def _analyze_png(payload: bytes) -> tuple[float, int, int]:
    img = Image.open(io.BytesIO(payload)).convert("RGBA")
    alpha = np.array(img)[:, :, 3]
    transparent = alpha == 0
    transparent_ratio = float(transparent.sum()) / float(alpha.size)
    full_rows = int(transparent.all(axis=1).sum())
    full_cols = int(transparent.all(axis=0).sum())
    return transparent_ratio, full_rows, full_cols


def run_gap_check(args: argparse.Namespace) -> int:
    client = SatellogicClient()
    contract_id = str(args.contract_id or "").strip() or None
    sources = _fetch_outcome_sources(
        client=client,
        outcome_id=args.outcome_id,
        center_lat=float(args.center_lat),
        center_lon=float(args.center_lon),
        source_aoi_size_km=float(args.source_aoi_size_km),
        start_date=str(args.start_date),
        end_date=str(args.end_date),
        contract_id=contract_id,
    )
    if not sources:
        print("ERROR: no sources found for outcome in source AOI.")
        return 2

    print(f"Outcome {args.outcome_id}: {len(sources)} source strip(s)")
    service = _build_source_service(contract_id=contract_id)
    proxy = LocalTileProxy(service, event_logger=lambda _m, _l="info": None)
    proxy.start()
    base_url = proxy.base_url
    print(f"Local proxy: {base_url}")

    center_x, center_y = _lonlat_to_tile(float(args.center_lon), float(args.center_lat), int(args.zoom))
    radius = max(0, int(args.radius))
    coords = [
        (x, y)
        for x in range(center_x - radius, center_x + radius + 1)
        for y in range(center_y - radius, center_y + radius + 1)
    ]
    print(
        f"Checking {len(coords)} tile(s) around z/x/y={args.zoom}/{center_x}/{center_y} "
        f"(radius={radius}, scale={args.scale}, buffer={args.buffer})"
    )

    params: list[tuple[str, str]] = [
        ("tileMatrixSetId", "WebMercatorQuad"),
        ("format", "png"),
        ("scale", str(int(args.scale))),
        ("buffer", str(int(args.buffer))),
        ("render_layer", "raw"),
        ("bidx", "1"),
        ("bidx", "2"),
        ("bidx", "3"),
    ]
    if contract_id:
        params.append(("contract_id", contract_id))
    for source in sources:
        params.append(("url", source))

    rows: list[dict] = []
    durations: list[float] = []
    max_workers = max(1, int(args.max_workers))

    def fetch_tile(x: int, y: int) -> tuple[dict, float]:
        url = (
            f"{base_url}/satellogic/cog/tiles/{int(args.zoom)}/{x}/{y}?"
            f"{urlencode(params, doseq=True, safe=':/')}"
        )
        started = time.perf_counter()
        response = requests.get(url, timeout=max(20, int(args.timeout_seconds)))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if response.status_code != 200:
            return (
                {
                    "x": x,
                    "y": y,
                    "status": response.status_code,
                    "transparent_ratio": 0.0,
                    "full_rows": 0,
                    "full_cols": 0,
                },
                elapsed_ms,
            )
        transparent_ratio, full_rows, full_cols = _analyze_png(response.content)
        return (
            {
                "x": x,
                "y": y,
                "status": 200,
                "transparent_ratio": transparent_ratio,
                "full_rows": full_rows,
                "full_cols": full_cols,
            },
            elapsed_ms,
        )

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(fetch_tile, x, y) for x, y in coords]
            for future in as_completed(futures):
                row, elapsed_ms = future.result()
                rows.append(row)
                durations.append(elapsed_ms)
    finally:
        proxy.stop()

    seam_issues = [
        row
        for row in rows
        if row["status"] != 200
        or (
            0.0 < float(row["transparent_ratio"]) < 0.99
            and (int(row["full_rows"]) > 0 or int(row["full_cols"]) > 0)
        )
    ]
    nonzero_alpha_tiles = [row for row in rows if float(row["transparent_ratio"]) > 0.0]

    print(
        f"Done: {len(rows)} tile(s), seam_issues={len(seam_issues)}, "
        f"tiles_with_any_transparency={len(nonzero_alpha_tiles)}"
    )
    if durations:
        print(
            "Timing ms: "
            f"min={min(durations):.1f} median={statistics.median(durations):.1f} max={max(durations):.1f}"
        )

    if seam_issues:
        print("Seam issue sample:")
        for row in seam_issues[:15]:
            print(
                f"  zxy={args.zoom}/{row['x']}/{row['y']} status={row['status']} "
                f"alpha0_ratio={row['transparent_ratio']:.6f} rows={row['full_rows']} cols={row['full_cols']}"
            )
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gap/seam checker for an L1D SR outcome on local proxy tiles.")
    parser.add_argument("--outcome-id", default="435f51fd-8684-414c-be5f-b46d5a7f172d")
    parser.add_argument("--contract-id", default="cont.eac744cc-2afe-4012-9621-35623feeb7a7")
    parser.add_argument("--center-lat", type=float, default=16.460779)
    parser.add_argument("--center-lon", type=float, default=111.599384)
    parser.add_argument("--zoom", type=int, default=19)
    parser.add_argument("--radius", type=int, default=3, help="Tile radius from center (3 => 7x7 window)")
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--buffer", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--source-aoi-size-km", type=float, default=40.0)
    parser.add_argument("--start-date", default="2026-01-18T00:00:00Z")
    parser.add_argument("--end-date", default="2026-02-17T23:59:59Z")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_gap_check(parse_args()))
