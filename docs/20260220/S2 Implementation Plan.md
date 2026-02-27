# Sentinel-2 Full-Stack Stabilization Plan (QGIS Plugin + Backend)

## Summary
Stabilize Sentinel-2 (`merlin-s2`) end-to-end so the workflow is reliable in this order:
1. Search returns correct Sentinel-2 results.
2. Selecting a result always loads usable imagery in QGIS.
3. WMTS streaming works predictably (or falls back cleanly).
4. Monitoring and workflow paths use Sentinel-2-safe defaults.

Primary success criteria:
1. Sentinel-2 searches from the plugin are correct and non-empty for valid AOI/date ranges.
2. Selecting a Sentinel-2 result loads a visible geospatial layer without manual recovery.
3. WMTS failures degrade to explicit fallback instead of silent failure.
4. Monitoring/workflow arrival logic no longer assumes Satellogic defaults for Sentinel-2 schedules.

## Scope (Locked)
1. Include full Sentinel-2 stack: Search + Load + WMTS + Monitoring + Workflows.
2. Prioritize fixing “result selection fails” first.
3. Keep `satellogic` behavior unchanged.
4. No Sentinel-1 changes in this batch.

## Implementation Workstreams

### 1. Search and Collection Correctness
Files:
- `qgis_plugin/image_mate_qgis_plugin/services/source_service.py`
- `qgis_plugin/image_mate_qgis_plugin/clients/source_manager.py`
- `qgis_plugin/image_mate_qgis_plugin/clients/merlin_sentinel2_client.py`
- `backend/app/main.py`
- `backend/app/source_manager.py`

Plan:
1. Ensure plugin source list and collection list always expose `merlin-s2` consistently when enabled.
2. Remove/limit broad exception swallowing in Sentinel-2 collection/search paths so actionable errors surface to logs/UI.
3. Normalize empty collection handling to Sentinel-2 default collection only for `merlin-s2`, never cross-source fallback.
4. Keep ID canonicalization unchanged (`merlin-s2:<native-id>`), and verify collection IDs are preserved through search -> cache -> item resolution.
5. Add explicit logging tags for source + collection + count in both plugin and backend search paths.

### 2. Result Selection and Raster Load Reliability (Top Priority)
Files:
- `qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py`
- `qgis_plugin/image_mate_qgis_plugin/clients/merlin_sentinel2_client.py`
- `qgis_plugin/image_mate_qgis_plugin/services/source_service.py`

Plan:
1. Change Sentinel-2 asset candidate priority for selection load to geospatial-first:
- `visual_fullres`
- `visual`
- `analytic`
- `preview`
- `thumbnail`
2. Add source-specific selection branch so only Sentinel-2 gets this priority change, preserving other sources.
3. If download/load of all raster assets fails, auto-attempt Sentinel-2 WMTS layer for that item day before hard failure.
4. Improve failure message to include attempted asset keys and first error cause.
5. Keep cache reuse behavior intact, but log whether loaded from cache vs downloaded.

### 3. WMTS Stream Stabilization
Files:
- `qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py`
- `qgis_plugin/image_mate_qgis_plugin/services/settings_service.py`
- `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
- `backend/app/main.py`
- `backend/tests/test_archive_search.py`

Plan:
1. Switch plugin Sentinel-2 streaming to prefer backend WMTS config endpoint contract:
- fetch `/api/layers/sentinel/wmts`
- use returned `template_url` when `available=true`
- keep existing direct WMTS construction as secondary fallback
2. Add explicit unavailable reasons to stream status (missing instance/layer/capabilities/tile probe fail).
3. Keep per-item day time pinning behavior, but enforce consistent `TIME` propagation for stream layer URLs.
4. Add optional plugin setting `cdse_wmts_use_backend_proxy` default `true`.
5. If WMTS unavailable, continue with direct asset fallback path without stopping user flow.

### 4. Monitoring and Workflow Sentinel-2 Defaults
Files:
- `backend/app/workbench.py`
- `backend/app/main.py`
- `backend/app/models.py`
- `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
- `qgis_plugin/image_mate_qgis_plugin/plugin.py`

Plan:
1. In workflow schedule arrival logic, replace hardcoded fallback `collection_id="l1d-sr"` with source-aware default:
- `merlin-s2` -> first `CDSE_SENTINEL2_COLLECTIONS` (default `sentinel-2-l2a`)
- `satellogic` -> `SATELLOGIC_COLLECTION_ID`
2. In monitoring create flows, preserve selected source and avoid implicit source rewrites.
3. Keep monitoring model defaults as `merlin-s2` for now, but ensure runtime payload source always wins.
4. Add trace logs for monitoring subscription source + collection filters and run trigger source.

### 5. Observability and Diagnostics
Files:
- `qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py`
- `qgis_plugin/image_mate_qgis_plugin/services/source_service.py`
- `backend/app/main.py`

Plan:
1. Add structured diagnostics for Sentinel-2 item load attempts:
- source, collection, item id
- asset key attempted
- auth route used
- success/failure
2. Add one-line runtime summary fields for Sentinel-2 WMTS readiness and credentials detected.
3. Ensure search/selection/stream failures are visible in both disk log and UI status line.

## Public API / Interface / Type Changes
1. Add plugin setting key:
- `image_mate/cdse/wmts_use_backend_proxy` (bool, default `true`)
2. No breaking API changes to existing backend endpoints.
3. Preserve existing endpoint contracts:
- `/api/archive/search`
- `/api/layers/sentinel/wmts`
- `/api/layers/sentinel/wmts/tiles/{z}/{x}/{y}`
- monitoring endpoints
4. No schema breaking changes to `SearchRequest` or `SearchResultItem`.
5. Internal behavior change in workbench schedule default collection selection (source-aware).

## Test Plan

### Backend tests
1. Search route:
- `source_id=merlin-s2` keeps Sentinel-2 collection defaults and returns typed items.
2. WMTS route:
- available/unavailable behavior and reason fields remain correct.
3. Monitoring/workbench:
- arrival schedule uses Sentinel-2 default collection when source is `merlin-s2`.
4. Regression:
- existing Satellogic search/tasking tests remain green.

### Plugin tests
1. Source/collection:
- `merlin-s2` source populates Sentinel-2 collections correctly.
2. Result selection:
- Sentinel-2 selection attempts geospatial-first asset order.
3. Fallback chain:
- stream unavailable -> asset load; asset load fail -> explicit actionable error.
4. WMTS integration:
- backend template path is used when configured.
5. Regression:
- Satellogic streaming path unchanged.

### Manual smoke scenarios
1. Sentinel-2 search in plugin with valid AOI/date.
2. Select top 3 results and confirm visible layer load each time.
3. Disable/break WMTS config and confirm fallback still loads imagery.
4. Create monitoring subscription with `merlin-s2`; verify refresh and run trigger metadata.

## Rollout Plan
1. Stage 1: Search + selection reliability changes behind normal config (no feature flag).
2. Stage 2: WMTS backend-proxy preference with default enabled.
3. Stage 3: Monitoring/workbench source-aware default collection.
4. Stage 4: Final cleanup pass and documentation update in `docs/20260220/merlin-sentinel2-integration-design.md`.

## Acceptance Criteria
1. Sentinel-2 selection in plugin does not fail for valid items due to preview-first ordering.
2. WMTS failures no longer block user from loading Sentinel-2 imagery.
3. Sentinel-2 monitoring/workbench schedule path does not silently use `l1d-sr`.
4. No regressions in Satellogic search, stream, and tasking.

## Assumptions and Defaults
1. Canonical design reference is `docs/20260220/merlin-sentinel2-integration-design.md`.
2. Sentinel-2 default collection is `sentinel-2-l2a` unless overridden by config.
3. Backend WMTS endpoint remains available for plugin integration.
4. Existing dirty workspace changes are unrelated and will not be modified during implementation.
