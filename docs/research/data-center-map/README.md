# Data centre archive atlas

Open `datacentres-index.html` in Safari or Chrome. It is a standalone Leafmap/Folium HTML export with embedded Leaflet, imagery and a no-JavaScript static overview; no Image Mate server, API key, or expiring asset URL is required. `index.html` is retained as a compatibility redirect. Internet access is needed only for the optional reference basemap tiles. If iOS Files shows the static overview, use Share → Open in Safari or Chrome for the interactive controls and imagery overlays. A localhost preview may also be served with `python -m http.server 8025 --bind 127.0.0.1 --directory docs/research/data-center-map` from the repository root.

## Contents and use

- All 13 sites from the September 9 research shortlist are pinned.
- 87 distinct images / capture outcomes from `quickview-visual-thumb` are embedded, with actual image footprint polygons. Shared images are downloaded once and associated with every intersecting site search area.
- Click a pin or select a site. The default is its latest capture with scene cloud metadata at most 20%, if one exists; this does not certify cloud-free pixels at the construction site. Use Previous / Next or choose a date; All dates stacks the site's captures chronologically. Fit site and Fit image provide different spatial scales.
- Image opacity, footprints, research search rectangles, and reference basemaps are independently controllable. Clicking a footprint shows timestamp, cloud metadata, item ID and outcome ID.
- Where the L1D-SR site-local quality gate found at least two usable capture dates, the footprint and site popups include an **Animate this** button that opens a fixed-extent, north-up time-series player. Each animation is exactly 2.0 km × 2.0 km, centered on the site pin and rendered at the source-oriented 0.5 m output grid. Class-2 haze is allowed over that focus square; class-3 cloud rejects a frame. Cloud elsewhere in the source image does not reject it.
- The current pre-rendered L1D-SR sequence is Abilene (4 frames, including two haze-qualified dates). Colossus 2 has one qualifying date, while Colossus 1, Colossus 3 Southaven and the other sites do not have a usable multi-date sequence inside the 2 km pin-centered focus; their manifests explain the exclusion reason.
- New Carlisle, Lordstown, Port Washington, Saline and Lake Mariner have no matching products in this thumbnail collection. This is not evidence of an empty provider archive or a reason to submit tasking automatically.
- River Bend is explicitly a provisional neighboring-property pin, not a verified campus. Lake Mariner's Anthropic attribution remains provisional. All search rectangles are research AOIs, not property boundaries.

| Site | Matching thumbnail products |
| --- | ---: |
| Abilene | 16 |
| Colossus 1 | 53 |
| Frontier / Shackelford | 1 |
| Jupiter | 1 |
| Freebird / Milam | 2 |
| Colossus 2 | 9 |
| Colossus 3 | 10 |
| River Bend provisional neighborhood | 4 |
| Other five sites | 0 |

Site counts overlap: the sum is not the number of unique images. This is a fixed browse snapshot, not a live archive monitor.

## Provenance and placement

Search window: September 9, 2024 through September 10, 2026 UTC. Searches were performed September 10 using Image Mate's `SatellogicClient` and its Sales – Showcase default contract. Candidate outcomes were matched to the prior research inventory; no other acquisitions were added. Expanded research AOIs were used where previously established. The exact queries, item/outcome IDs, footprints, site memberships, unmatched outcomes and download status are in `inventory.json`. Research location sources and caveats remain in the adjacent construction handoff document.

## L1D-SR animation and tasking review

`animations/index.json` is the refreshed L1D-SR archive assessment. It groups products by outcome, downloads the provider `visual` and `cloud` GeoTIFFs, composes same-outcome tiles onto a fixed 2.0 km × 2.0 km north-up grid centered on each site pin, and creates one MP4 plus a player page for each site with at least two usable dates. The live collection did not publish a cloud-mask legend; the documented operational rule is class 1 = clear, class 2 = haze allowed for this exploratory sequence, class 3 = cloud rejection, and class 0/nodata ignored outside the valid mask. This rule is empirical and is recorded with the manifests.

The active-collection test is independent of animation quality: a site is active when the archive has any L1D-SR capture from August 27 through September 10, 2026 UTC. Abilene is the only active site in the refreshed search. `data-center-tasking-previews-2026-09-10.geojson` contains 12 local weekly-tasking proposals for inactive sites (11 requiring geometry/commercial confirmation and the provisional River Bend location blocked). No tasking or processing order was submitted by this workflow.

The source is the low-resolution RGB GeoTIFF (`analytic` asset) of the **visual-thumbnail collection**, not the full-resolution analytical imagery collection and not L1D-SR. Although catalog asset metadata advertises four bands, the downloaded files contain provider-rendered 8-bit RGB. All 87 downloaded rasters were successfully checked against their STAC footprints.

All 87 catalog `proj:epsg` values disagreed with the embedded GeoTIFF CRS. The exporter uses the GeoTIFF CRS, reprojects to Web Mercator, and alpha-clips to the actual footprint. It does not stretch an unreferenced image into an arbitrary bounding box. Original cloud cover is retained; images are not cloud-screened out. Derived PNGs are limited to 1024 pixels on their longest side; the HTML embeds WebP versions at quality 88 for a compact ~4.3 MB deliverable. The displayed previews may therefore be coarser than the native 20 m product. Black/nodata padding outside the footprint is transparent.

Imagery © Satellogic. Internal research use: check applicable publication rights before sharing or using in a public blog. Street basemap © OpenStreetMap contributors. Optional reference satellite tiles © Esri and its credited providers; these tiles are not capture-dated construction evidence.

## Rebuild and checks

The read-only exporters are `scripts/build_data_center_map.py` and `scripts/build_data_center_animations.py`; map controls and layout are in `scripts/data_center_map_ui.html`.

```sh
.venv/bin/python scripts/build_data_center_map.py --fetch
# In a separate environment with leafmap, folium and Pillow installed:
python scripts/build_data_center_map.py --render
.venv/bin/python scripts/build_data_center_animations.py
.venv/bin/python -m unittest discover -s test -p 'test_data_center_map.py' -v
```

Fetching and animation generation use authenticated GET/search/download calls only. No processing orders, opportunities, taskings, changes to active jobs, or public uploads are performed. Rendering is offline apart from library import initialization; browsing the final map loads third-party libraries and reference tiles. The isolated render environment used for this export has leafmap 0.63.1 and folium 0.20.0; Image Mate's application dependencies were not changed.
