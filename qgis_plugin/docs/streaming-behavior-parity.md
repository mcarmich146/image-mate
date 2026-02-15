# Image Mate Streaming Behavior Parity (Web App -> QGIS Plugin)

## What the old web app did

The web app had two rendering modes:

1. Overview mode (lower zoom):
- Rendered frame footprints + preview/thumbnail overlays.
- Did not fetch full-resolution COG tiles for every frame.

2. Detail mode (higher zoom):
- Automatically switched to streamed tile rendering.
- Satellogic: streamed XYZ tiles from `/api/raster/cog/tiles/{z}/{x}/{y}` (backend proxy -> Satellogic COG tile API).
- Sentinel: rendered WMTS tiles from `/api/layers/sentinel/wmts...`.
- Used viewport-driven refresh and prefetch (not click-to-download).

Key references:
- `frontend/app.js` (`detailTileTemplateUrl`, `refreshMapMode`, `drawResults`)
- `backend/app/main.py` (`/api/raster/cog/tiles/...`, `/api/layers/sentinel/wmts...`)

## Transferability to QGIS plugin

Fully transferable:
- Sentinel WMTS streaming via QGIS XYZ/WMTS tile layer.
- Satellogic COG tile streaming if a proxy endpoint is available.

Partially transferable:
- Automatic detail-mode orchestration (viewport-driven layer switching and item prioritization).
- Multi-overlay/prefetch behavior can be approximated in QGIS, but implementation differs from Leaflet.

Not 1:1 transferable:
- Browser-centric prefetch tuning and overlay stacking behavior will differ in QGIS rendering pipeline.

## Current plugin status

Implemented in plugin:
- Selection-driven streaming layer load for both providers.
- Embedded local Satellogic tile proxy inside plugin (no separate FastAPI process required).
- Local proxy resilience improvements: retry on transient upstream errors, tile cache, stale-tile fallback.
- Stream telemetry/progress in dock (`Stream status`) with tile counters (tiles, cache hits, errors, in-flight).
- Satellogic detail parity: if overview search collection is quickview, plugin also fetches `l1d-sr` and resolves selection/auto-stream to matching `l1d-sr` items for full-resolution tile streaming.
- Fallback to original download-based loading if streaming cannot be built.
- Basic auto-detail behavior: when panning/zooming with results loaded, plugin auto-streams the latest visible item (stream-only path).

Files:
- `qgis_plugin/image_mate_qgis_plugin/plugin.py`
- `qgis_plugin/image_mate_qgis_plugin/services/local_tile_proxy.py`
- `qgis_plugin/image_mate_qgis_plugin/services/source_service.py`

## Recommended next steps for closer parity

1. Add explicit "Overview/Detail" plugin toggle and zoom threshold setting in UI.
2. Add policy controls for auto-stream selection (latest visible, nearest to center, selected-only).
3. Add optional multi-item streamed stack (bounded count) for compare workflows.
4. Add tile-cache metrics/logging panel to monitor stream throughput and failures.
