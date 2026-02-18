# -*- coding: utf-8 -*-
"""Shared helpers for building streaming tile URLs."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import parse_qs, urlencode, urlparse


def extract_cog_source_url(raw_url: str) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return ""
    if value.startswith("s3://"):
        return value
    try:
        parsed = urlparse(value)
        source = str((parse_qs(parsed.query or "").get("s") or [""])[0]).strip()
        if source.startswith("s3://"):
            return source
        return value
    except Exception:
        return value


def satellogic_item_cog_source_url(item: dict) -> str:
    assets = item.get("assets") or {}
    for key in ("visual_fullres", "visual", "analytic"):
        asset = assets.get(key)
        if isinstance(asset, dict):
            href = str(asset.get("href") or "").strip()
        else:
            href = str(asset or "").strip()
        if not href:
            continue
        source = extract_cog_source_url(href)
        if source:
            return source
    return ""


def build_satellogic_tile_query(
    *,
    sources: Iterable[str],
    scale: int,
    contract_id: str | None,
    tile_matrix_set_id: str = "WebMercatorQuad",
    image_format: str = "png",
    buffer_size: int = 1,
    render_layer: str | None = "raw",
    bands: Iterable[int] = (1, 2, 3),
) -> str:
    params: list[tuple[str, str]] = [
        ("tileMatrixSetId", str(tile_matrix_set_id or "WebMercatorQuad")),
        ("format", str(image_format or "png")),
        ("scale", str(max(1, int(scale or 1)))),
        ("buffer", str(max(0, int(buffer_size or 0)))),
    ]
    if render_layer:
        params.append(("render_layer", str(render_layer)))
    for band in bands or []:
        params.append(("bidx", str(int(band))))
    for source in sources:
        source_value = str(source or "").strip()
        if source_value:
            params.append(("url", source_value))
    if contract_id:
        params.append(("contract_id", str(contract_id).strip()))

    query = urlencode(params, doseq=True, safe=":/")
    # QGIS datasource URI parsing splits on '&' at the provider URI level.
    # Escape nested query separators so they remain inside the XYZ URL value.
    return query.replace("&", "%26")


def build_satellogic_xyz_url(
    *,
    stream_base: str,
    sources: Iterable[str],
    scale: int,
    contract_id: str | None,
    is_local_proxy: bool,
    tile_matrix_set_id: str = "WebMercatorQuad",
    image_format: str = "png",
    buffer_size: int = 1,
    render_layer: str | None = "raw",
    bands: Iterable[int] = (1, 2, 3),
) -> str:
    query = build_satellogic_tile_query(
        sources=sources,
        scale=scale,
        contract_id=contract_id,
        tile_matrix_set_id=tile_matrix_set_id,
        image_format=image_format,
        buffer_size=buffer_size,
        render_layer=render_layer,
        bands=bands,
    )
    base = str(stream_base or "").strip().rstrip("/")
    if not base:
        return ""
    if is_local_proxy:
        return f"{base}/satellogic/cog/tiles/{{z}}/{{x}}/{{y}}?{query}"
    if base.endswith("/api"):
        return f"{base}/raster/cog/tiles/{{z}}/{{x}}/{{y}}?{query}"
    return f"{base}/api/raster/cog/tiles/{{z}}/{{x}}/{{y}}?{query}"
