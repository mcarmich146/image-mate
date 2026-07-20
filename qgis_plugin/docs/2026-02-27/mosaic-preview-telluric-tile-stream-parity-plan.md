# Mosaic Preview Telluric Tile Stream Parity Design and Implementation Plan

- Date: 2026-02-27
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- Mosaic preview still showed partial imagery because preview flow did not follow Aleph browser behavior.
- HAR analysis showed browser preview uses Telluric map tiles:
  - `/telluric/scenes/{scene_id}/rasters/{raster}.tif/get_tile?x={x}&y={y}&z={z}`
- Current plugin path used downloaded preview/thumbnail assets and COG proxy tiles, which can diverge from browser rendering.

## Existing Reusable Components
- Local authenticated tile proxy in `services/local_tile_proxy.py`.
- Satellogic auth/contract handling in `services/source_service.py`.
- XYZ layer builder and preview render path in `mixins/search_streaming.py` and `plugin.py`.

## Proposed Backend Changes
- Add Telluric tile fetch method in source service:
  - `fetch_satellogic_telluric_tile(...)` with retries, contract fallback, and PNG media return.
- Add local proxy Telluric route:
  - `/satellogic/telluric/tiles/{z}/{x}/{y}?scene_id=...&raster_name=...&contract_id=...`
  - Reuse cache/coalescing/stats and safe empty-tile behavior on failures.
- Add dynamic scene/raster resolution from item metadata:
  - Scene id from item id/scene fields.
  - Raster `.tif` from asset href or embedded `s3://` source query parameter.
- Update stream builder:
  - `search_streaming._build_stream_layer_for_item(..., prefer_telluric=False)`
  - Telluric stream attempted first when explicitly requested.
- Update Mosaic preview renderer:
  - Prefer Telluric stream for browser parity, then asset download fallback, then generic stream fallback.

## UI Wiring Changes (Minimal)
- No UI widget changes.
- Preview checkbox/list behavior unchanged; only backend layer source selection changed.

## Implementation Steps
- Implement Telluric upstream fetch in `source_service`.
- Implement Telluric local-proxy route and handler in `local_tile_proxy`.
- Implement scene/raster extraction + Telluric XYZ URL builder in `search_streaming`.
- Switch Mosaic preview render order to Telluric-first.
- Add/adjust static smoke tests for wiring.

## Terminal-Only Test Plan
- `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/source_service.py`
- `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/local_tile_proxy.py`
- `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py`
- `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/plugin.py`
- `py -3 qgis_plugin/test/mosaic_tracking_preview_telluric_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_preview_multi_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_preview_all_candidates_smoke.py`

## Risks and Rollback
- Risk: some items may not provide parseable Telluric scene/raster identifiers; fallback path remains in place.
- Risk: Telluric tile availability/permissions can differ by contract; empty-tile handling prevents hard failures.
- Rollback: revert Telluric route/fetch/helper additions and restore previous preview source order.

## 2026-02-28 Log Triage Update (Thai_CaaS)
- Campaign: `Thai_CaaS`
- Project: `vancouver_mosaic`
- Latest log inspected: `C:\Users\jo.man_satellogic\ImageMateCampaigns\campaigns\thai_caas\logs\image_mate_qgis_20260228T061505Z.log`

### Observed Failure Signature
- Telluric preview loaded, but all requested tiles were empty.
- Repeated proxy warnings:
  - `served empty telluric tile ... status=404 ... detail={"message":"No item found with id <scene_id>"}`
- Scene id sent upstream included trailing tile suffixes (example: `..._2_0_1`), which Telluric rejects.

### Fix Applied
- Normalized scene id extraction for L1D ids by stripping trailing tile suffix pattern `_<int>_<int>_<int>`.
- Added raster-driven scene-id derivation fallback from `.tif` names (e.g. `..._visual.tif` -> canonical scene id).
- Corrected L1D fallback raster name generation to use canonical scene id directly (`{scene_id}_visual.tif`).

### Terminal Verification
- `py -3 -m compileall qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py qgis_plugin/image_mate_qgis_plugin/services/local_tile_proxy.py qgis_plugin/image_mate_qgis_plugin/services/source_service.py qgis_plugin/image_mate_qgis_plugin/plugin.py`
- `py -3 qgis_plugin/test/mosaic_tracking_preview_telluric_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_preview_multi_smoke.py`

### Pending Runtime Verification
- Launch plugin, preview `Thai_CaaS -> vancouver_mosaic`, then confirm newest campaign log no longer contains:
  - `No item found with id ..._2_0_1`
  - `served empty telluric tile ... status=404`

## 2026-02-28 Iteration: End-to-End Replay and Resolution
### Problem Confirmation from Latest Log
- Log used: `C:\Users\jo.man_satellogic\ImageMateCampaigns\campaigns\thai_caas\logs\image_mate_qgis_20260228T071521Z.log`
- Representative failure from log:
  - `scene_id=20260227_193958_340_SN50_L1D_SR_MS_10N_486_5450`
  - `raster=20260227_193958_340_SN50_L1D_SR_MS_10N_486_5450_visual.tif`
  - `z/x/y=14/2586/5612`
  - Upstream result: `404 {"message":"No item found with id ..."}`

### Root Cause (Post-Normalization)
- Even with suffix-normalized item ids, preview still resolved Telluric keys from tasking detail item-id candidates.
- For tasking mosaics, valid Telluric scene/raster keys come from order deliverables (assets), not from those guessed STAC item ids.

### Fix Applied
- Added deliverables-first preview resolution:
  - Fetch order deliverables for `latest_collection_id`.
  - Build preview items from deliverable assets.
  - Use deliverable-derived scene/raster for Telluric stream.
- Added scene-id extraction from deliverable asset hrefs in streaming helper logic.
- Kept previous item-id/search fallback paths when deliverables are unavailable.

### New Debug Tool
- Added CLI replay tool:
  - `qgis_plugin/test/mosaic_tracking_telluric_replay_debug.py`
- Behavior:
  - Parses latest campaign log Telluric-empty cases.
  - Replays exact failing `scene/raster/zxy`.
  - Fetches order deliverables and replays corrected deliverable scene/raster with the same `zxy`.
  - Optionally writes returned PNG tiles for visual verification.

### Replay Evidence (Thai_CaaS / vancouver_mosaic)
- Command:
  - `py -3 qgis_plugin/test/mosaic_tracking_telluric_replay_debug.py --campaign thai_caas --project vancouver_mosaic --max-cases 3 --save-dir qgis_plugin/test/_artifacts/telluric_replay`
- Results:
  - Log replay (exact parameters): `404` for all sampled cases.
  - Deliverable replay (same zxy): `200 image/png` for all sampled cases.
  - Saved PNG evidence under:
    - `qgis_plugin/test/_artifacts/telluric_replay/`
