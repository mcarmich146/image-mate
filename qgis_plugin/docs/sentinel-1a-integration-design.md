# Sentinel-1A Hookup Design for QGIS Plugin

## Document Control
- Status: Draft v0.1
- Date: 2026-02-20
- Scope: Add Sentinel-1A support to the QGIS plugin as a first-class source, with safe rollout and minimal regressions.

## 1. Problem
Sentinel-1A is not currently usable in the QGIS plugin flow because the source stack is hard-wired to two source IDs:
- `satellogic`
- `merlin-s2` (Sentinel-2 only)

Current wiring confirms this in:
- `qgis_plugin/image_mate_qgis_plugin/clients/source_manager.py`
- `qgis_plugin/image_mate_qgis_plugin/services/source_service.py`
- `qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py`
- `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
- `backend/app/source_manager.py`
- `backend/app/main.py`

## 2. Current Blocking Points
1. No Sentinel-1 source identity.
- Source registry only defines `satellogic` and `merlin-s2`.

2. Sentinel collection logic is Sentinel-2-specific.
- Defaults and filters assume `sentinel-2-*`.

3. Streaming path is source-branch specific.
- `merlin-s2` path uses CDSE WMTS settings.
- No Sentinel-1 branch exists.

4. Monitoring/cue defaults are hardcoded to `merlin-s2`.
- Plugin payload fallbacks and backend model defaults assume `merlin-s2`.

5. URL-source inference maps CDSE URLs to `merlin-s2`.
- This mislabels source family if Sentinel-1 is added without expanding routing.

## 3. Design Goals
1. Add Sentinel-1A without breaking existing `satellogic` and `merlin-s2` behavior.
2. Keep source abstraction unchanged from caller perspective (`list_sources`, `list_collections`, `search`, `item_by_id`, `download_bytes`).
3. Support current plugin UX (Collection Search, map footprints, result selection, monitoring source selection).
4. Preserve prefix-safe IDs for caching and item lookup.
5. Roll out incrementally: search first, visualization hardening second.

## 4. Non-Goals (Phase 1)
1. Full SAR analytics (coherence, interferometry, flood change models).
2. New tasking support (tasking remains Satellogic-only).
3. Full backend workflow redesign.

## 5. Proposed Integration Model

### 5.1 Source Identity
Introduce a new source:
- `source_id`: `merlin-s1`
- `title`: `Merlin (Sentinel-1A)`
- `aliases`: `["sentinel-1", "s1", "s1a", "merlin-s1"]`
- `supports_contracts`: `False`
- `default_collection_id`: first configured Sentinel-1 collection (recommended `sentinel-1-grd`)

Rationale:
- Keeps Sentinel-1 behavior isolated from Sentinel-2.
- Avoids overloading `merlin-s2` with modality-specific logic.

### 5.2 Client/Adapter Strategy
Add `MerlinSentinel1Client` in plugin and backend clients.

Implementation options:
1. Fast path (recommended for phase 1):
- Duplicate `MerlinSentinel2Client` skeleton and specialize filtering + normalization for Sentinel-1.

2. Longer-term cleanup:
- Extract shared CDSE auth/STAC transport into a common base client used by `MerlinSentinel2Client` and `MerlinSentinel1Client`.

### 5.3 Normalized Item Contract
Keep existing item schema so no UI contract changes are needed:

```json
{
  "id": "merlin-s1:<native-id>",
  "source_id": "merlin-s1",
  "collection": "sentinel-1-grd",
  "datetime": "...",
  "outcome_id": "<native-id>",
  "satellite_name": "Sentinel-1A",
  "gsd": 10.0,
  "cloud_cover": null,
  "geometry": {},
  "assets": {
    "visual": "...",
    "analytic": "...",
    "preview": "...",
    "thumbnail": "...",
    "cloud_mask": ""
  },
  "raw": {}
}
```

Notes:
- `cloud_cover` is expected to be `null` for SAR.
- `satellite_name` comes from `platform`/`constellation` fields when available.
- Asset preference should prioritize image-like quicklook/preview and valid raster download targets.

### 5.4 Streaming and Imagery Loading
Phase 1 behavior:
1. Search + footprint overlay works for `merlin-s1`.
2. Item selection first attempts streaming branch:
- Add `merlin-s1` branch in `_build_stream_layer_for_item`.
- If Sentinel-1 WMTS config is available, build XYZ layer from configured instance/layer.
3. If no stream config is available, fallback to `_load_item_imagery_layer` download logic.

Phase 2 behavior:
- Optional dedicated backend endpoint for Sentinel-1 WMTS template/proxy (parallel to existing Sentinel endpoint) to improve operational reliability.

## 6. File-by-File Change Design

### 6.1 QGIS Plugin
1. `qgis_plugin/image_mate_qgis_plugin/clients/config.py`
- Add:
  - `merlin_s1_enabled`
  - `cdse_sentinel1_collections`
  - optional Sentinel-1 WMTS layer config fields.

2. `qgis_plugin/image_mate_qgis_plugin/clients/merlin_sentinel1_client.py` (new)
- CDSE auth + STAC search.
- Sentinel-1-specific collection defaults.
- `normalize_merlin_s1_item(...)`.

3. `qgis_plugin/image_mate_qgis_plugin/clients/source_manager.py`
- Register `SOURCE_MERLIN_S1`.
- Route list/search/item/download for `merlin-s1`.
- Expand alias map + URL inference fallback behavior.

4. `qgis_plugin/image_mate_qgis_plugin/services/source_service.py`
- Instantiate `MerlinSentinel1Client`.
- Include source and collection fallbacks for `merlin-s1`.
- Keep runtime summary explicit for S1/S2 enable flags.

5. `qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py`
- Add `merlin-s1` handling in `_build_stream_layer_for_item`.
- Keep fallback path unchanged when no stream layer can be built.

6. `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
- Remove hardcoded monitoring fallback `"merlin-s2"`; use currently selected source or first enabled non-tasking source.
- Keep source/collection controls generic.

7. `qgis_plugin/image_mate_qgis_plugin/services/settings_service.py`
- Persist Sentinel-1 enable + collection + WMTS settings.

### 6.2 Backend (for monitoring/cues compatibility and API parity)
1. `backend/app/config.py`
- Add Sentinel-1 enable/collections config.

2. `backend/app/merlin_sentinel1_client.py` (new)
- Mirror plugin client behavior for API endpoints.

3. `backend/app/source_manager.py`
- Register and route `merlin-s1`.

4. `backend/app/main.py`
- Ensure `/api/sources`, `/api/collections`, `/api/archive/search`, and monitoring/cue validation accept `merlin-s1`.
- Replace Sentinel-2-only fallback assumptions with source-specific defaults.

5. `backend/app/models.py`
- Update monitoring defaults from fixed `merlin-s2` to a neutral default (or keep explicit but UI-selected override required).

## 7. Config Additions

### Plugin/Backend env
- `MERLIN_S1_ENABLED=true|false`
- `CDSE_SENTINEL1_COLLECTIONS=sentinel-1-grd,sentinel-1-slc`
- Optional:
  - `CDSE_S1_WMTS_LAYER_ID=<layer>`
  - `CDSE_S1_WMTS_INSTANCE_ID=<instance>`

### QGIS settings keys
- `cdse/s1_enabled`
- `cdse/s1_collections`
- optional WMTS keys for S1 visualization.

## 8. Rollout Plan
1. Phase 1: Search and selection MVP
- Add `merlin-s1` source registration.
- Add Sentinel-1 client + normalization.
- Search results appear in Collection Search; item selection loads fallback imagery where available.

2. Phase 2: Stream visualization hardening
- Add Sentinel-1 stream branch and optional WMTS settings.
- Improve source-specific error messages when only archive assets are available.

3. Phase 3: Monitoring parity
- Enable monitoring subscriptions/events/cues for `merlin-s1` in backend validation and defaults.

## 9. Testing Plan

### Unit tests
1. Source manager routing:
- `merlin-s1` listed, normalized, and routed correctly.

2. Sentinel-1 normalization:
- Prefix-safe IDs (`merlin-s1:<native>`), asset selection, null cloud handling.

3. Search filters:
- Satellite/platform filtering and GSD handling.
- Cloud filter ignored for Sentinel-1.

### API tests
1. `/api/sources` includes `merlin-s1` when enabled.
2. `/api/collections?source_id=merlin-s1` returns Sentinel-1 collections.
3. `/api/archive/search` works with `source_id=merlin-s1`.
4. Monitoring endpoints accept `source_id=merlin-s1`.

### Plugin smoke tests
1. Source switch to `Merlin (Sentinel-1A)` updates collection list.
2. Search returns footprints and list rows.
3. Selecting a result loads a layer (stream or fallback).
4. Monitoring create/refresh with `merlin-s1` no longer fails source validation.

## 10. Acceptance Criteria
1. Sentinel-1A appears as selectable source in QGIS plugin.
2. Sentinel-1 collections are selectable and searchable.
3. Returned items keep canonical schema and render in existing result UI.
4. Result selection loads imagery through stream branch when configured, otherwise fallback download path.
5. No regressions in `satellogic` and `merlin-s2` search/stream behavior.

## 11. Open Decisions
1. Naming:
- Keep label as `Merlin (Sentinel-1A)` vs `Merlin (Sentinel-1 SAR)` for future Sentinel-1B compatibility.

2. Visualization policy:
- WMTS-first vs Process API-first for Sentinel-1 intensity rendering.

3. Collection defaults:
- Restrict to `sentinel-1-grd` in phase 1, or expose both `grd` and `slc` immediately.

