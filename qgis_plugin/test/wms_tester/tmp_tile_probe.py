import math
import requests
from urllib.parse import urlparse, parse_qs
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.satellogic_client import SatellogicClient


def latlon_to_tile(lon, lat, zoom):
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n)
    return x, y


def main():
    client = SatellogicClient()
    contracts = client.list_contracts()
    contract_id = contracts[0].get("contract_id") if contracts else None

    geom = {"type": "Point", "coordinates": [111.5621096, 16.46092468]}
    item = client.search(
        geometry=geom,
        start_date="2025-12-19T00:00:00Z",
        end_date="2026-02-17T23:59:59Z",
        collection_id="l1d-sr",
        contract_id=contract_id,
        limit=1,
        max_cloud_cover=None,
        satellite_name=None,
        min_gsd=None,
        max_gsd=None,
    )[0]

    coords = item["geometry"]["coordinates"][0]
    lons = [pt[0] for pt in coords]
    lats = [pt[1] for pt in coords]
    minx, miny, maxx, maxy = min(lons), min(lats), max(lons), max(lats)
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0

    zoom = 16
    x, y = latlon_to_tile(cx, cy, zoom)

    asset_href = item["assets"]["visual"]["href"]
    parsed = urlparse(asset_href)
    asset = parse_qs(parsed.query or "").get("s", [asset_href])[0]
    base = "https://api.satellogic.com"
    params = (
        "tileMatrixSetId=WebMercatorQuad&format=png&scale=2&buffer=1&"
        "render_layer=raw&bidx=1&bidx=2&bidx=3&url="
        + requests.utils.quote(asset, safe=":/?&=,=")
    )
    url = f"{base}/raster/cog/tiles/{zoom}/{x}/{y}?{params}"

    print("id", item.get("id"))
    print("tile", zoom, x, y)
    resp = requests.get(url, headers=client.auth_headers(contract_id=contract_id), timeout=20)
    print("status", resp.status_code)


if __name__ == "__main__":
    main()
