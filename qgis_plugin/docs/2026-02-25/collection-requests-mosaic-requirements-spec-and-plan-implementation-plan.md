# Collection Requests Mosaic v1 Implementation Plan

## Summary
Implement Mosaic as a new workflow under Collection Requests while preserving existing Ad-hocs behavior, using backend-first services for tiling, persistence, and tasking orchestration. Deliver in vertical slices with requirement traceability to `REQ-*`, deterministic pricing from clipped AOI area, and terminal-first smoke coverage.

## Important API/Interface Changes
| Component | Change |
| --- | --- |
| `ImageMateMainDock` | Add Collection Requests sub-tabs: `Ad-hocs` and `Mosaic`; inside `Mosaic` add `Create` and `Tracking`. |
| `ImageMateMainDock` signals | Add: `mosaic_breakdown_requested(dict)`, `mosaic_accept_requested(dict)`, `mosaic_tracking_project_changed(str)`, `mosaic_refresh_status_requested(dict)`, `mosaic_mark_accepted_requested(dict)`, `mosaic_retask_requested(dict)`, `mosaic_refresh_projects_requested()`. |
| `ImageMateMainDock` setters | Add: `set_mosaic_create_status(str)`, `set_mosaic_breakdown_rows(list[dict])`, `set_mosaic_estimated_price(float)`, `set_mosaic_projects(list[str])`, `set_mosaic_tracking_rows(list[dict])`, `set_mosaic_tracking_status(str)`. |
| Plugin handlers | Add corresponding `handle_mosaic_*` handlers and connect them in `show_dock()`. |
| Campaign storage interface | Add campaign-scoped mosaic path helpers (`collections/mosaic/<project_id>`). |
| New backend services | Add Mosaic services for planning, storage, and orchestration (details below). |

## Architecture and File-Level Plan
| File | Change |
| --- | --- |
| [main_dock.py](C:/Users/jo.man_satellogic/Documents/Personal/dev/image-mate/qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py) | Refactor `_build_tasking_tab()` to host `Ad-hocs` + `Mosaic` tabs; keep existing Ad-hocs controls/behavior unchanged; add Mosaic Create/Tracking UI and thin signal emitters only. |
| [plugin.py](C:/Users/jo.man_satellogic/Documents/Personal/dev/image-mate/qgis_plugin/image_mate_qgis_plugin/plugin.py) | Connect new Mosaic signals; add `handle_mosaic_*` orchestration; keep UI logic minimal; use services for validation, tiling, persistence, submission, refresh, retask, acceptance. |
| [campaign_storage_service.py](C:/Users/jo.man_satellogic/Documents/Personal/dev/image-mate/qgis_plugin/image_mate_qgis_plugin/services/campaign_storage_service.py) | Add deterministic Mosaic directory helpers under campaign root. |
| `services/mosaic_grid_service.py` | New: AOI -> 10km world-grid clipped tiles, deterministic `tile_id`, clipped area km2, pricing helper. |
| `services/mosaic_tracking_store.py` | New: SQLite schema, transactional CRUD for project/tile/attempt/status_history. |
| `services/mosaic_tasking_service.py` | New: tasking payload builder, per-tile submit, status refresh, retask, manual acceptance transitions. |
| `services/mosaic_contracts.py` | New: constants and typed keys for statuses, table names, defaults, field names. |
| [source_service.py](C:/Users/jo.man_satellogic/Documents/Personal/dev/image-mate/qgis_plugin/image_mate_qgis_plugin/services/source_service.py) | No breaking changes; reuse existing `create_tasking_order`/`get_tasking_order`/`default_contract_id` seams. |

## Data Contracts and Persistence (Decision Complete)
### Project folder layout
1. `<campaign_root>/collections/mosaic/<project_id>/tiles.shp` (+ sidecar files)
2. `<campaign_root>/collections/mosaic/<project_id>/mosaic_tracking.sqlite3`
3. `<campaign_root>/collections/mosaic/<project_id>/project_meta.json`

### SQLite schema
1. `mosaic_project(project_id PK, campaign_uid, created_at, updated_at, aoi_source, aoi_geojson, estimated_price_usd, tile_count, shapefile_path, schema_version)`
2. `mosaic_tile(project_id, tile_id, geometry_wkt, clipped_area_km2, qa_status, api_status, latest_collection_id, attempt_count, last_sync_at, accepted_at, accepted_by, created_at, updated_at, mutation_source, PRIMARY KEY(project_id,tile_id))`
3. `mosaic_attempt(id PK, project_id, tile_id, attempt_no, collection_id, attempt_status, api_status, request_payload_json, response_payload_json, error_text, requested_at, updated_at, UNIQUE(project_id,tile_id,attempt_no))`
4. `mosaic_status_history(id PK, project_id, tile_id, from_qa_status, to_qa_status, from_api_status, to_api_status, mutation_source, note, created_at)`

### Status model
1. `qa_status`: `NotAccepted` or `Accepted` only.
2. `api_status`: raw API status string, plus local sentinel values (`not_submitted`, `submission_failed`) where needed.
3. `Accepted` is terminal for `Refresh Status` and `Re-task`.

## Workflow Implementation Details
### A. Mosaic Create -> Breakdown AOI
1. Resolve AOI from `map_extent` or `polygon_layer` using existing geometry conversion helpers.
2. Transform AOI to equal-area metric CRS (`EPSG:6933`), generate world-aligned 10,000m cells, intersect, discard empties.
3. Compute `tile_id` deterministically from grid indices; compute `clipped_area_km2` from clipped geometry.
4. Compute `estimated_price_usd = sum(clipped_area_km2) * 8.0`.
5. Render clipped tiles on map as memory layer and populate preview table.

### B. Mosaic Create -> Accept
1. Validate project id (`1..64`, `[A-Za-z0-9._-]`, filesystem safe) and uniqueness in current campaign.
2. Create project folder, SQLite DB, and shapefile with clipped geometries (`tile_id`, `clipped_area_km2` attributes).
3. Persist project and tiles in one transaction.
4. Submit one area tasking per tile; continue on failures; persist each attempt/result transactionally.
5. Populate Tracking view from DB immediately after acceptance.

### C. Mosaic Tracking
1. Project selection loads tiles with required columns: `tile_id`, `clipped_area_km2`, `api_status`, `qa_status`, `latest_collection_id`, `attempt_count`, `last_sync_at`.
2. `Refresh Status` fetches latest order state only for `qa_status != Accepted`.
3. `Mark Accepted` updates `qa_status`, audit fields, and status history.
4. `Re-task` allowed only for non-accepted tiles; appends new attempt and updates latest collection mapping.

## Required Defaults Chosen
1. Source restriction: tasking submission/refresh/retask require `source_id == satellogic`; otherwise show actionable warning and skip network actions.
2. Tasking package: fixed `sku = TSKARE-M` for Mosaic v1.
3. Tasking window: `start_date = now_utc`, `end_date = now_utc + 24h`.
4. Order naming: `mosaic-{project_id}-{tile_id}-a{attempt_no}` (sanitized).
5. `accepted_by`: OS username (`USERNAME`) fallback to `"operator"`.
6. Tracking actions are single-tile in v1 (no bulk accept/retask).
7. API status display is raw string in v1 (no label normalization layer).

## Delivery Slices and Traceability
| Slice | Scope | Primary REQ coverage |
| --- | --- | --- |
| S1 | Storage/path/contracts services + schema + validation | `REQ-F-009..013`, `REQ-BR-004`, `REQ-NF-002`, `REQ-NF-004` |
| S2 | UI tab refactor (`Ad-hocs` + `Mosaic`) and Mosaic Create wiring | `REQ-F-001..008`, `REQ-F-017` (table scaffolding), `REQ-BR-001` |
| S3 | AOI tiling, deterministic pricing, map/table preview | `REQ-F-004..007`, `REQ-F-012`, `REQ-NF-001`, `REQ-NF-003` |
| S4 | Accept flow + per-tile submission + attempt persistence | `REQ-F-014..016`, `REQ-F-020`, `REQ-BR-001` |
| S5 | Tracking project load, refresh statuses, mark accepted, retask | `REQ-F-018..021`, `REQ-BR-002`, `REQ-BR-003` |
| S6 | Hardening, regression checks, docs + traceability evidence | all remaining AC/TC closure |

## Test Cases and Scenarios (Terminal-First)
| Scenario | Requirement refs | Verification |
| --- | --- | --- |
| Project ID validation and uniqueness | `REQ-F-009`, `REQ-F-010`, `REQ-BR-004` | Pure-Python smoke with temp dirs and expected reject/accept paths. |
| SQLite transaction rollback integrity | `REQ-NF-002`, `AC-027` | Failure-injection smoke confirms no orphan tile-attempt links. |
| Status transitions (`Completed` != `Accepted`, accepted terminal) | `REQ-BR-002`, `REQ-BR-003` | Service-level smoke with mocked `source_service.get_tasking_order`. |
| Re-task appends immutable attempt history | `REQ-F-019`, `REQ-F-020` | Service-level smoke verifies attempt count increment and historical row preservation. |
| Pricing from clipped area only | `REQ-F-007`, `REQ-BR-001` | Grid service test fixture with partial tile intersections and deterministic totals. |
| Restart persistence recovery | `REQ-F-021` | Store reload smoke using persisted SQLite fixture. |
| Performance envelope | `REQ-NF-003` | Benchmark probe on synthetic AOI producing up to 2,000 clipped tiles. |

### Planned test scripts
1. `qgis_plugin/test/mosaic_project_validation_smoke.py`
2. `qgis_plugin/test/mosaic_tracking_store_smoke.py`
3. `qgis_plugin/test/mosaic_status_rules_smoke.py`
4. `qgis_plugin/test/mosaic_submission_payload_smoke.py`
5. `qgis_plugin/test/mosaic_grid_pricing_smoke.py` (runs when QGIS Python is available)

### Planned verification commands
1. `py -3 -m py_compile` on all changed Mosaic modules and touched UI/plugin files.
2. `py -3 qgis_plugin/test/mosaic_*_smoke.py`
3. `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
4. `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Rollout and Safety
1. Keep Ad-hocs code path intact and unchanged in behavior; Mosaic is additive.
2. Use structured logs prefixed with `[Mosaic]` for breakdown, accept, submit, refresh, retask, and acceptance actions.
3. Fail per-tile operations independently and continue processing remaining tiles.
4. No migration impact outside new project-local SQLite DBs.

## Explicit Assumptions
1. Existing tasking order endpoints (`create_order`, `get_order`) remain stable.
2. Campaign storage path is writable at runtime.
3. AOI geometry input can be represented as polygon/multipolygon in WGS84.
4. Mosaic v1 intentionally omits bulk acceptance and API-status label normalization.
