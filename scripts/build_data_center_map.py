"""Read-only archive browse-map export; never creates orders or taskings.

Fetch with Image Mate's Python environment, then render with leafmap installed:
  .venv/bin/python scripts/build_data_center_map.py --fetch
  python scripts/build_data_center_map.py --render

The primary export is ``datacentres-index.html``; ``index.html`` remains a
small compatibility redirect for existing bookmarks.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from html import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RESEARCH = ROOT / "docs/research"
OUT = RESEARCH / "data-center-map"
MAP_PATH = OUT / "datacentres-index.html"
COLLECTION = "quickview-visual-thumb"
LEAFLET_JS_URL = "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js"
LEAFLET_CSS_URL = "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css"

LABELS = {
    "Anthropic-Amazon New Carlisle": ("New Carlisle · AWS / Anthropic", "Anthropic", "Campus map reference; not a surveyed parcel."),
    "OpenAI Stargate Abilene": ("Abilene · Stargate", "OpenAI", "Campus map reference; distinguish flagship and expansion buildings."),
    "Colossus 1": ("Colossus 1 · Memphis", "SpaceX / xAI", "Former Electrolux plant. Conversion and expansion, not a new original building."),
    "OpenAI Stargate Shackelford": ("Frontier · Shackelford County", "OpenAI", "Campus map reference, near Abilene."),
    "OpenAI Stargate Lordstown": ("Lordstown · Stargate", "OpenAI", "Verify compute halls versus server manufacturing / assembly."),
    "OpenAI Stargate New Mexico": ("Jupiter · Santa Teresa", "OpenAI", "Broad project search rectangle; imagery may cover only part of the development."),
    "OpenAI Stargate Wisconsin": ("Lighthouse · Port Washington", "OpenAI", "Campus map reference, not Mount Pleasant."),
    "OpenAI Stargate Michigan": ("The Barn · Saline Township", "OpenAI", "Campus map reference, not the town center."),
    "OpenAI Stargate Milam": ("Freebird · Milam County", "OpenAI", "Campus reference; expanded search rectangle used for discovery."),
    "Anthropic Lake Mariner": ("Lake Mariner · candidate", "Anthropic", "Physical campus identified; Anthropic building / tenant attribution is provisional."),
    "Colossus 2 facility search": ("Colossus 2 · Memphis", "SpaceX / xAI", "5420 Tulane Road street-address reference; not a surveyed building centroid."),
    "Colossus 3 Southaven": ("Colossus 3 · Southaven", "SpaceX / xAI", "2400 Stateline Road W street-address reference; not the separate power plant."),
    "River Bend provisional neighborhood": ("River Bend · provisional location", "Anthropic", "PROVISIONAL: pin is a neighboring commercial property, NOT a verified campus center."),
}


def prepare_sites(research, geojson):
    sites = []
    revised = {s["name"]: s for s in research["revised_sites"]}
    result_sets = sum((research.get(k, []) for k in (
        "initial_collection_results", "additional_collection_results", "revised_collection_results",
    )), [])
    for i, f in enumerate(geojson["features"]):
        p = f["properties"]
        name = p["site"]
        aliases = {name, name + " expanded search"}
        if name in ("Colossus 2 facility search", "Colossus 3 Southaven"):
            aliases.add("Colossus 2")
        expected = set()
        for result in result_sets:
            if result.get("site") in aliases:
                expected.update(c["outcome_id"] for c in result.get("captures", []) if c.get("outcome_id"))
        geometry = f["geometry"]
        if name + " expanded search" in revised:
            w, s, e, n = revised[name + " expanded search"]["bounds"]
            geometry = {"type": "Polygon", "coordinates": [[[w,s],[e,s],[e,n],[w,n],[w,s]]]}
        center = [p["search_center_longitude"], p["search_center_latitude"]]
        if name == "Colossus 2 facility search":
            center = [-90.042977, 34.999489]  # Address reference in the handoff, not AOI centroid.
        label, group, note = LABELS[name]
        sites.append(dict(id=f"site-{i+1}", name=name, label=label, group=group, note=note,
                          center=center, geometry=geometry, reference=p["coordinate_reference"],
                          source=p.get("source"), expected_outcomes=sorted(expected),
                          tasking_location_verified=name != "River Bend provisional neighborhood"))
    return sites


def _mercator_y(latitude: float) -> float:
    import math
    latitude = max(-85.05, min(85.05, latitude))
    radians = math.radians(latitude)
    return (1 - math.asinh(math.tan(radians)) / math.pi) / 2


def fallback_overview(data: dict) -> str:
    """A no-JavaScript overview for mobile file previewers.

    It is deliberately a sourced-coordinate plot with graticule, rather than a
    hand-drawn country outline. The interactive Leaflet map remains the normal
    view; this keeps the locations visible when an iOS file preview blocks JS.
    """
    width, height = 1000, 620
    west, east, south, north = -135.0, -45.0, 20.0, 66.0
    y_south, y_north = _mercator_y(south), _mercator_y(north)

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = (lon - west) / (east - west) * width
        y = (_mercator_y(lat) - y_north) / (y_south - y_north) * height
        return x, y

    colors = {"OpenAI": "#087e8b", "Anthropic": "#845cb3", "SpaceX / xAI": "#cf644d"}
    parts = [
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">',
        '<rect width="1000" height="620" fill="#e8f0f2"/>',
        '<g stroke="#bfd0d5" stroke-width="1" opacity=".65">',
    ]
    for lon in range(-130, -44, 10):
        x, _ = project(lon, 20)
        parts.append(f'<path d="M{x:.1f} 0V620"/>')
    for lat in range(20, 67, 5):
        _, y = project(-135, lat)
        parts.append(f'<path d="M0 {y:.1f}H1000"/>')
    parts.append('</g><g fill="#718891" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="12">')
    for lon in range(-130, -44, 10):
        x, _ = project(lon, 20)
        parts.append(f'<text x="{x + 3:.1f}" y="18">{lon}°</text>')
    for lat in range(25, 67, 5):
        _, y = project(-135, lat)
        parts.append(f'<text x="6" y="{y - 4:.1f}">{lat}°N</text>')
    parts.append('</g><text x="24" y="56" fill="#526a75" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="18" font-weight="600">North America · research site overview</text>')
    parts.append('<g stroke="#fff" stroke-width="2" opacity=".9" fill="none">')
    for site in data["sites"]:
        (x1, y1), (x2, y2) = project(site["center"][0], site["center"][1]), project(site["center"][0], site["center"][1])
        parts.append(f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="14" stroke-dasharray="3 3"/>')
    parts.append('</g>')
    for index, site in enumerate(data["sites"], 1):
        x, y = project(site["center"][0], site["center"][1])
        color = colors.get(site["group"], "#087e8b")
        label_x = x + (18 if x < 790 else -18)
        anchor = "start" if x < 790 else "end"
        provisional = "PROVISIONAL · " if "provisional" in site["note"].lower() else ""
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="10" fill="{color}" stroke="#fff" stroke-width="2"/><text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" fill="#fff" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="10" font-weight="700">{index}</text>')
        parts.append(f'<text x="{label_x:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}" fill="#294650" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="12">{index} · {escape(site["label"])}{escape(" · " + provisional) if provisional else ""}</text>')
    parts.append('</svg>')
    return "".join(parts)


def inline_leaflet_assets(html: str) -> str:
    """Make the export work from iOS Files / file:// when CDN script loading is blocked."""
    import requests

    try:
        js = requests.get(LEAFLET_JS_URL, timeout=30)
        js.raise_for_status()
        css = requests.get(LEAFLET_CSS_URL, timeout=30)
        css.raise_for_status()
    except requests.RequestException as exc:
        print(f"Warning: could not inline Leaflet assets ({type(exc).__name__}); keeping CDN fallback", file=sys.stderr)
        return html

    html = html.replace(f'<script src="{LEAFLET_JS_URL}"></script>', f'<script>{js.text}</script>')
    html = html.replace(f'<link rel="stylesheet" href="{LEAFLET_CSS_URL}"/>', f'<style>{css.text}</style>')
    unused = [
        r'<script src="https://code\.jquery\.com/jquery-3\.7\.1\.min\.js"></script>',
        r'<script src="https://cdn\.jsdelivr\.net/npm/bootstrap@5\.2\.2/dist/js/bootstrap\.bundle\.min\.js"></script>',
        r'<script src="https://cdnjs\.cloudflare\.com/ajax/libs/Leaflet\.awesome-markers/2\.0\.2/leaflet\.awesome-markers\.js"></script>',
        r'<link rel="stylesheet" href="https://cdn\.jsdelivr\.net/npm/bootstrap@5\.2\.2/dist/css/bootstrap\.min\.css"/>',
        r'<link rel="stylesheet" href="https://netdna\.bootstrapcdn\.com/bootstrap/3\.0\.0/css/bootstrap-glyphicons\.css"/>',
        r'<link rel="stylesheet" href="https://cdn\.jsdelivr\.net/npm/@fortawesome/fontawesome-free@6\.2\.0/css/all\.min\.css"/>',
        r'<link rel="stylesheet" href="https://cdnjs\.cloudflare\.com/ajax/libs/Leaflet\.awesome-markers/2\.0\.2/leaflet\.awesome-markers\.css"/>',
        r'<link rel="stylesheet" href="https://cdn\.jsdelivr\.net/gh/python-visualization/folium/folium/templates/leaflet\.awesome\.rotate\.min\.css"/>',
    ]
    for pattern in unused:
        html = re.sub(pattern, "", html)
    return html


def export_raster(client, item):
    """Use embedded GeoTIFF CRS, never blindly trust the STAC proj:epsg value."""
    import numpy as np
    from PIL import Image
    from rasterio.io import MemoryFile
    from rasterio.enums import Resampling
    from rasterio.features import geometry_mask
    from rasterio.transform import array_bounds
    from rasterio.warp import calculate_default_transform, reproject, transform_bounds, transform_geom
    from affine import Affine

    asset = item.get("assets", {}).get("analytic", {})
    if "tiff" not in asset.get("type", "") or not asset.get("href"):
        raise ValueError("No georeferenced low-resolution thumbnail raster")
    content = client.download_bytes(asset["href"])
    with MemoryFile(content) as mem, mem.open() as src:
        if not src.crs or src.count < 3 or src.width * src.height > 25_000_000:
            raise ValueError("Unsupported thumbnail raster")
        if any(t != "uint8" for t in src.dtypes[:3]):
            raise ValueError("Expected provider-rendered 8-bit RGB thumbnail")
        native_bounds = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        from shapely.geometry import box, shape
        footprint = shape(item["geometry"])
        extent = box(*native_bounds)
        if not footprint.is_valid or footprint.area <= 0 or footprint.area > 4:
            raise ValueError("Implausible footprint")
        if extent.intersection(footprint).area / footprint.area < 0.95:
            raise ValueError("Raster georeferencing does not match footprint")
        dst_transform, width, height = calculate_default_transform(
            src.crs, "EPSG:3857", src.width, src.height, *src.bounds)
        scale = max(width, height) / 1024
        if scale > 1:
            new_w, new_h = max(1, round(width / scale)), max(1, round(height / scale))
            dst_transform *= Affine.scale(width / new_w, height / new_h)
            width, height = new_w, new_h
        rgba = np.zeros((4, height, width), dtype=np.uint8)
        for band in range(3):
            reproject(src.read(band + 1), rgba[band], src_transform=src.transform, src_crs=src.crs,
                      dst_transform=dst_transform, dst_crs="EPSG:3857", resampling=Resampling.bilinear)
        reproject(src.dataset_mask(), rgba[3], src_transform=src.transform, src_crs=src.crs,
                  dst_transform=dst_transform, dst_crs="EPSG:3857", resampling=Resampling.nearest)
        inside = geometry_mask([transform_geom("EPSG:4326", "EPSG:3857", item["geometry"])],
                               out_shape=(height, width), transform=dst_transform, invert=True)
        rgba[3, ~inside] = 0
        if not np.any(rgba[3]):
            raise ValueError("Empty clipped image")
        filename = hashlib.sha256(item["id"].encode()).hexdigest()[:20] + ".png"
        Image.fromarray(np.moveaxis(rgba, 0, -1)).save(OUT / "images" / filename)
        west, south, east, north = transform_bounds(
            "EPSG:3857", "EPSG:4326", *array_bounds(height, width, dst_transform))
        return dict(image="images/" + filename, bounds=[[south, west], [north, east]],
                    raster_crs=str(src.crs), stac_crs=item["properties"].get("proj:epsg"),
                    width=width, height=height, downloaded_bytes=len(content))


def fetch_inventory():
    from backend.app.satellogic_client import SatellogicClient
    from shapely.geometry import shape

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "images").mkdir(exist_ok=True)
    research = json.loads((RESEARCH / "data-center-imagery-2026-09-09.json").read_text())
    sites = prepare_sites(research, json.loads((RESEARCH / "data-center-search-aois-2026-09-09.geojson").read_text()))
    client = SatellogicClient()
    client.auth_headers()  # Resolve auth once before parallel read-only requests.
    items = {}

    def query(site):
        rows = client.search(site["geometry"], "2024-09-09", "2026-09-09", COLLECTION, None, 1000, None)
        if len(rows) >= 1000:
            raise ValueError("Search hit limit; do not report complete results")
        known = set(site["expected_outcomes"])
        matches = [r for r in rows if r["properties"].get("satl:outcome_id") in known
                   and shape(r["geometry"]).intersects(shape(site["geometry"]))]
        return rows, matches

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(query, s): s for s in sites}
        for future in as_completed(futures):
            site = futures[future]
            try:
                rows, matches = future.result()
                site.update(search_status="ok", thumbnail_items_found=len(rows), matched_items=len(matches))
                for row in matches:
                    record = items.setdefault(row["id"], {"raw": row, "sites": []})
                    record["sites"].append(site["id"])
                print(f"{site['label']}: {len(matches)} matched / {len(rows)} thumbnail items", flush=True)
            except Exception as exc:
                site.update(search_status="error", error_type=type(exc).__name__)
                print(f"{site['label']}: search failed ({type(exc).__name__})", flush=True)

    records = []
    def download(entry):
        row = entry["raw"]
        p = row["properties"]
        record = dict(id=row["id"], outcome_id=p.get("satl:outcome_id"), datetime=p.get("datetime"),
                      collection=COLLECTION, geometry=row["geometry"], sites=entry["sites"],
                      cloud=p.get("eo:cloud_cover"), gsd=p.get("gsd"), platform=p.get("platform"))
        try:
            record.update(export_raster(client, row), status="ready")
        except Exception as exc:
            record.update(status="unavailable", error_type=type(exc).__name__)
        return record

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(download, e) for e in items.values()]
        for i, future in enumerate(as_completed(futures), 1):
            record = future.result()
            records.append(record)
            if i % 10 == 0 or record["status"] != "ready" or i == len(futures):
                print(f"Downloaded {i}/{len(futures)}; last status={record['status']}", flush=True)
    records.sort(key=lambda r: (r["datetime"], r["id"]))
    for site in sites:
        matched = {r["outcome_id"] for r in records if site["id"] in r["sites"]}
        site["identified_outcomes_without_thumbnail"] = sorted(set(site["expected_outcomes"]) - matched)
    result = dict(collection=COLLECTION, generated_at=datetime.now(timezone.utc).isoformat(),
                  interval=research["search_interval_utc"], sites=sites, images=records,
                  method="Thumbnail-collection RGB GeoTIFFs, reprojected using embedded CRS to EPSG:3857; alpha-clipped to STAC footprint. No L1D-SR substitution. Outcome-matched to saved research; no orders or taskings.")
    (OUT / "inventory.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"sites": len(sites), "unique_images": len(records),
                      "ready": sum(r["status"] == "ready" for r in records)}), flush=True)


def render():
    import folium
    import leafmap.foliumap as leafmap
    from branca.element import Element, MacroElement, Template
    from PIL import Image

    data = json.loads((OUT / "inventory.json").read_text())
    animation_index_path = OUT / "animations/index.json"
    if animation_index_path.exists():
        animation_index = json.loads(animation_index_path.read_text(encoding="utf-8"))
        data["animation_index"] = {
            key: value
            for key, value in animation_index.items()
            if key not in {"site_results"}
        }
        data["animations"] = animation_index.get("site_results", {})
        for site in data.get("sites", []):
            site["animation"] = data["animations"].get(site.get("id"))
    for item in data["images"]:
        if item.get("image"):
            buffer = io.BytesIO()
            with Image.open(OUT / item["image"]) as image:
                image.save(buffer, format="WEBP", quality=88, method=6)
            item["image_data"] = "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode()
    m = leafmap.Map(center=[37.5, -94], zoom=4, tiles=None, height=900,
                    fullscreen_control=False, draw_control=False, measure_control=False,
                    latlon_control=False, search_control=False, layer_control=False)
    folium.TileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", name="Street map",
                     attr='© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', max_zoom=19).add_to(m)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                     name="Reference satellite basemap (not capture-dated)", attr="Tiles © Esri — Esri, Maxar, Earthstar Geographics, and the GIS User Community",
                     max_zoom=19, show=False).add_to(m)
    template = (ROOT / "scripts/data_center_map_ui.html").read_text()
    style, rest = template.split("<!-- END STYLE -->")
    markup, js = rest.split("<!-- START SCRIPT -->")
    markup = markup.replace("__FALLBACK_MAP__", fallback_overview(data))
    m.get_root().header.add_child(Element(style.replace("__MAP_ID__", m.get_name())))
    m.get_root().html.add_child(Element(markup))
    script = MacroElement()
    script._template = Template("{% macro script(this, kwargs) %}\n" +
                                js.replace("__MAP_ID__", m.get_name()).replace("__MAP_DATA__", json.dumps(data).replace("</", "<\\/")) +
                                "\n{% endmacro %}")
    m.add_child(script)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)
    m.to_html(str(MAP_PATH))
    html = inline_leaflet_assets(MAP_PATH.read_text())
    MAP_PATH.write_text(html)
    # Keep an intentionally tiny compatibility landing page so an existing
    # bookmark to index.html cannot open a stale pre-animation export.
    legacy_path = OUT / "index.html"
    legacy_path.write_text(
        '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=datacentres-index.html">'
        '<title>Data centre archive atlas</title><p>Opening <a href="datacentres-index.html">datacentres-index.html</a>…</p>',
        encoding="utf-8",
    )
    print(f"Map: {MAP_PATH} ({MAP_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    if not (args.fetch or args.render):
        parser.error("Choose --fetch and/or --render")
    if args.fetch:
        fetch_inventory()
    if args.render:
        render()
