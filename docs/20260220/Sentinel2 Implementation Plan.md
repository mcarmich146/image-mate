# Phase 1 Implementation Plan: Sentinel-1 GRD Search + Select (QGIS Plugin)

## Summary
This phase adds Sentinel-1 support as a new plugin source (`merlin-s1`) for Collection Search and result selection/loading, while leaving existing Sentinel-2 (`merlin-s2`) and Satellogic behavior intact.

This plan is scoped to your selected decisions:
- Phase scope: `Search + Select` only.
- Collection scope: Sentinel-1 defaults to `sentinel-1-grd` (keep Sentinel-2 optical behavior unchanged).
- Visualization path: `Direct asset fallback` (no Sentinel-1 WMTS/streaming branch in phase 1).

## Scope
In scope:
- New source registration for Sentinel-1 in plugin service layer.
- Sentinel-1 collection discovery/search/item normalization.
- Result selection loads Sentinel-1 assets via existing fallback download path.
- Automated tests for routing/normalization/search behavior.

Out of scope:
- Monitoring/cues updates for `merlin-s1`.
- Backend API parity for Sentinel-1.
- Sentinel-1 WMTS/stream proxy endpoint.
- SAR analytics workflows.

## Public Interfaces and Type Changes
1. New source ID exposed by plugin source APIs:
- `source_id`: `merlin-s1`
- `title`: `Merlin (Sentinel-1A)`
- aliases: `sentinel-1`, `s1`, `s1a`, `merlin-s1`

2. New environment/config fields in plugin client settings:
- `MERLIN_S1_ENABLED` (bool)
- `CDSE_SENTINEL1_COLLECTIONS` (CSV, default `sentinel-1-grd`)

3. Normalized item contract remains unchanged structurally, with Sentinel-1 semantics:
- `id`: prefixed as `merlin-s1:<native-id>`
- `cloud_cover`: usually `null`
- `assets`: mapped to best available image-like endpoints

## Implementation Steps (Ordered, Decision-Complete)
1. Add Sentinel-1 configuration support in `qgis_plugin/image_mate_qgis_plugin/clients/config.py`.
- Add `merlin_s1_enabled` with default `false`.
- Add `cdse_sentinel1_collections` CSV parsing with default `sentinel-1-grd`.
- Do not add QGIS settings UI fields in this phase; env-driven only.

2. Add new Sentinel-1 client module `qgis_plugin/image_mate_qgis_plugin/clients/merlin_sentinel1_client.py`.
- Reuse Merlin Sentinel-2 auth/token strategy (CDSE OAuth client credentials).
- Implement `list_collections`, `search`, `item_by_id`, `download_bytes`.
- Implement `normalize_merlin_s1_item(feature, source_id="merlin-s1")`.
- Filtering rules:
  - Apply `satellite_name`, `min_gsd`, `max_gsd`.
  - Ignore cloud filtering when cloud metadata is absent.
- Collection candidate behavior:
  - Explicit `collection_id` if provided and non-empty.
  - Otherwise first from `cdse_sentinel1_collections`.

3. Export new client in `qgis_plugin/image_mate_qgis_plugin/clients/__init__.py`.
- Export `MerlinSentinel1Client` and `normalize_merlin_s1_item`.

4. Update source routing in `qgis_plugin/image_mate_qgis_plugin/clients/source_manager.py`.
- Add `SOURCE_MERLIN_S1 = "merlin-s1"`.
- Accept `merlin_s1_client` in constructor.
- Register source metadata row for `merlin-s1`.
- Route `list_collections`, `search`, `item_by_id`, `download_bytes`, and `auth_headers_for_url` for `merlin-s1`.
- Keep URL inference backward-compatible:
  - If `source_hint` is valid/enabled, honor it.
  - Otherwise preserve existing CDSE default inference behavior.

5. Update service composition in `qgis_plugin/image_mate_qgis_plugin/services/source_service.py`.
- Instantiate `MerlinSentinel1Client`.
- Pass it into `SourceManager`.
- Extend module reload list with `image_mate_qgis_plugin.clients.merlin_sentinel1_client`.
- Extend env override wiring to set `merlin_s1_client.enabled` based on `MERLIN_S1_ENABLED`.
- Extend `list_sources()` fallback row set to include `merlin-s1`.
- Extend `list_collections()` fallback handling for `merlin-s1` to return at least `sentinel-1-grd`.

6. Keep map loading path fallback-first (no Sentinel-1 stream path changes).
- Do not add `merlin-s1` branch in `_build_stream_layer_for_item`.
- Rely on existing fallback `_load_item_imagery_layer` when stream layer is `None`.
- Add one diagnostic log line during fallback attempts for `merlin-s1` selection to simplify troubleshooting.

7. No phase-1 changes to monitoring defaults in `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py` or backend monitoring models.
- Monitoring remains `merlin-s2`-oriented in this phase by explicit scope decision.

## Runtime Data Flow After Change
1. User selects `Merlin (Sentinel-1A)` from `source_combo`.
2. `_on_source_changed` requests collections via `SourceService.list_collections("merlin-s1")`.
3. Search payload uses `source_id=merlin-s1` and selected `collection_id`.
4. `SourceService.search` routes to `SourceManager.search`.
5. `SourceManager.search` calls `MerlinSentinel1Client.search`.
6. Returned features are normalized as `merlin-s1:*`.
7. Result selection attempts stream layer first (expected `None` for `merlin-s1` in phase 1), then loads fallback asset layer via `_load_item_imagery_layer`.

## Failure Modes and Handling
1. Missing CDSE credentials.
- Return clear runtime error from Sentinel-1 client with same style as existing Merlin auth failures.

2. No image-like assets in item.
- Selection fails with explicit asset-resolution error message showing attempted asset keys.

3. Unknown/empty collection.
- Fallback to first configured Sentinel-1 collection (`sentinel-1-grd`).

4. ID collisions across sources.
- Prevented by canonical `merlin-s1:` prefixing.

## Test Plan
Automated tests to add:
1. `qgis_plugin` source manager routing test.
- `list_sources` includes `merlin-s1` when enabled.
- Alias normalization resolves `s1`, `sentinel-1`, `s1a` to `merlin-s1`.
- `search`/`item_by_id` route to Sentinel-1 client.

2. Sentinel-1 client normalization test.
- `id` is prefixed `merlin-s1:`.
- `source_id` is `merlin-s1`.
- `cloud_cover` remains `None` when absent.
- Asset selection picks image-like endpoint over metadata-only links.

3. Sentinel-1 search filter behavior test.
- `satellite_name` and GSD filters are honored.
- Cloud filter does not drop rows when cloud metadata is missing.

4. Source service integration test.
- `list_collections("merlin-s1")` returns Sentinel-1 rows.
- `search` with `source_id=merlin-s1` returns normalized items.

Manual smoke scenarios:
1. Enable `MERLIN_S1_ENABLED=true`, set CDSE credentials, restart plugin.
2. Verify source dropdown includes `Merlin (Sentinel-1A)`.
3. Run AOI search with `sentinel-1-grd`.
4. Verify footprints/results populate.
5. Select a result and confirm raster layer loads through fallback path.
6. Confirm `satellogic` and `merlin-s2` searches still behave unchanged.

## Rollout and Verification
1. Deliver as one focused PR for phase-1 plugin-only Sentinel-1 support.
2. Guard behavior with `MERLIN_S1_ENABLED` (default off) for controlled rollout.
3. Add brief operator notes to plugin docs for required env vars and known phase-1 limits.

## Acceptance Criteria
1. Sentinel-1 appears as an optional third source when enabled.
2. Sentinel-1 `sentinel-1-grd` searches return normalized results in existing UI.
3. Result selection loads imagery via fallback asset path.
4. No regressions in existing `satellogic` and `merlin-s2` search/selection flows.
5. New automated tests pass.

## Assumptions and Defaults Chosen
1. Canonical spec target for this implementation is the Sentinel-1 design in `qgis_plugin/docs/sentinel-1a-integration-design.md`.
2. Phase 1 remains plugin-only; backend Sentinel-1 API parity is deferred.
3. Sentinel-1 default collection is `sentinel-1-grd`.
4. Sentinel-2 behavior and defaults are unchanged in this phase.
5. Sentinel-1 visualization is fallback-only in phase 1 (no WMTS/stream requirement).
