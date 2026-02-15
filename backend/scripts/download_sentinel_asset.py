#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
from urllib.parse import urlparse

import requests


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "asset"


def _pick_http_url(row: dict) -> str:
    candidates: list[str] = []
    href = str(row.get("href") or "").strip()
    if href:
        candidates.append(href)
    alternates = row.get("alternates")
    if isinstance(alternates, dict):
        for key in ("https", "s3", "odata", "download"):
            value = str(alternates.get(key) or "").strip()
            if value:
                candidates.append(value)
        for value in alternates.values():
            value_s = str(value or "").strip()
            if value_s:
                candidates.append(value_s)

    for value in candidates:
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
    return ""


def _extension_from_url_or_type(url: str, mime_type: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jp2", ".tif", ".tiff", ".png", ".jpg", ".jpeg"):
        if path.endswith(ext):
            return ext
    mt = (mime_type or "").lower()
    if "jpeg2000" in mt or "jp2" in mt:
        return ".jp2"
    if "tiff" in mt:
        return ".tif"
    if "png" in mt:
        return ".png"
    if "jpeg" in mt:
        return ".jpg"
    return ".bin"


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a Sentinel asset (e.g. TCI_10m) through the image-mate API proxy.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000", help="Backend API base URL")
    parser.add_argument("--item-id", required=True, help="STAC item id (can include merlin-s2: prefix)")
    parser.add_argument("--asset-key", default="TCI_10m", help="Asset key to fetch (default: TCI_10m)")
    parser.add_argument("--source-id", default="merlin-s2", help="Source id (default: merlin-s2)")
    parser.add_argument("--collection-id", default="sentinel-2-l2a", help="Collection id")
    parser.add_argument("--contract-id", default="", help="Optional contract id to pass to proxy")
    args = parser.parse_args()

    api_base = args.api_base.rstrip("/")
    repo_root = Path(__file__).resolve().parents[2]
    output_dir = repo_root / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    inspect_url = f"{api_base}/api/archive/item-assets"
    inspect_params = {
        "item_id": args.item_id,
        "source_id": args.source_id,
        "collection_id": args.collection_id,
    }
    if args.contract_id:
        inspect_params["contract_id"] = args.contract_id

    inspect_resp = requests.get(inspect_url, params=inspect_params, timeout=120)
    if inspect_resp.status_code >= 400:
        print(f"Failed to inspect item assets: {inspect_resp.status_code} {inspect_resp.text}")
        return 1

    payload = inspect_resp.json()
    raw_assets = payload.get("raw_assets") or []
    if not isinstance(raw_assets, list) or not raw_assets:
        print("No raw assets returned for this item.")
        return 1

    key_exact = str(args.asset_key or "").strip()
    target = next((row for row in raw_assets if str(row.get("key") or "") == key_exact), None)
    if target is None:
        key_lower = key_exact.lower()
        target = next((row for row in raw_assets if str(row.get("key") or "").lower().startswith(key_lower)), None)
    if target is None:
        keys = ", ".join(str(row.get("key") or "") for row in raw_assets)
        print(f"Asset key '{args.asset_key}' not found. Available keys: {keys}")
        return 1

    raw_url = _pick_http_url(target)
    if not raw_url:
        print(f"Asset key '{args.asset_key}' has no http/https URL in href/alternates.")
        return 1

    proxy_url = f"{api_base}/api/assets/proxy"
    proxy_params = {
        "url": raw_url,
        "source_hint": args.source_id,
    }
    if args.contract_id:
        proxy_params["contract_id"] = args.contract_id
    proxy_resp = requests.get(proxy_url, params=proxy_params, timeout=300)
    if proxy_resp.status_code >= 400:
        print(f"Asset proxy failed: {proxy_resp.status_code} {proxy_resp.text}")
        return 1

    source_item = str(payload.get("id") or args.item_id)
    source_item_safe = _safe_name(source_item.replace(":", "_"))
    asset_key_safe = _safe_name(str(target.get("key") or args.asset_key))
    ext = _extension_from_url_or_type(raw_url, str(target.get("type") or ""))
    out_path = output_dir / f"{source_item_safe}__{asset_key_safe}{ext}"
    out_path.write_bytes(proxy_resp.content)

    print(f"Downloaded: {out_path}")
    print(f"Bytes: {len(proxy_resp.content)}")
    print(f"Asset key: {target.get('key')}")
    print(f"Asset url: {raw_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
