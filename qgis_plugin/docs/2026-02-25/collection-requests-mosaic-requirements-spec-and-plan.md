# Collection Requests Mosaic Requirements Specification And Implementation Plan

- Revision: `v2`
- Date: `2026-02-25`
- Scope: `qgis_plugin/**`
- Source: stakeholder workflow and clarifications from this thread
- Related artifact: `qgis_plugin/docs/2026-02-25/collection-requests-mosaic-rtm.csv`

## 1. Objective Summary

### Objectives

- `OBJ-001`: Enable operators to convert an AOI into priced mosaic tiles ready for tasking.
- `OBJ-002`: Ensure every tile submission attempt is persisted and traceable.
- `OBJ-003`: Support tile-level tracking with manual QA acceptance and controlled re-tasking.
- `OBJ-004`: Add Mosaic workflow without regressing existing `Ad-hocs` behavior.

### Scope Boundary

- In scope:
  - `Collection Requests` tab split into `Ad-hocs` and `Mosaic`.
  - `Mosaic` flow for AOI tiling, pricing, acceptance, submission, and tracking.
  - Per-project shapefile and SQLite persistence under campaign storage.
  - Tile-level status refresh and manual acceptance lifecycle.
- Out of scope:
  - Automatic QA acceptance from API status.
  - External financial settlement/invoice integration.
  - Cross-campaign project ID uniqueness.

### Constraints

- Pricing uses AOI-intersection area at `8 USD/km2`.
- Tile geometries written to shapefile are clipped to AOI.
- `Accepted` is manual-only and terminal from QA standpoint.
- A non-accepted tile can be re-tasked repeatedly until accepted.
- `Project ID` must be globally unique within a campaign.

### Success Metrics

- `100%` of created tiles have a durable `tile_id` and attempt history.
- Pricing is reproducible from stored tile areas.
- Operators can resume tracking from local SQLite after restart without data loss.

## 2. Domain Definitions And State Model

### Definitions

- `Tile`: AOI-intersection polygon produced from a 10 km x 10 km world grid cell.
- `Attempt`: One tasking submission for one tile, with one returned `collection_id` or failure.
- `api_status`: Status returned by tasking API for an attempt.
- `qa_status`: Local operator decision state for a tile, values: `NotAccepted`, `Accepted`.

### Tile Lifecycle Rules

1. Initial tile state is `qa_status=NotAccepted`.
2. `Refresh Status` may update `api_status` for non-accepted tiles only.
3. `Mark Accepted` changes `qa_status` to `Accepted` and records audit fields.
4. `Re-task` is allowed only when `qa_status != Accepted` and creates a new attempt row.
5. API `Completed` never implies local `Accepted`.

## 3. Assumptions And Open Questions

### Assumptions

| ID | Assumption | Impact | Owner |
| --- | --- | --- | --- |
| ASM-001 | Existing tasking integration supports polygon area-collect and returns stable identifiers per request. | High | Tasking Integration |
| ASM-002 | Campaign root path resolution is already available to plugin services. | High | QGIS Plugin Team |
| ASM-003 | Runtime has write access for shapefile and SQLite under campaign folders. | High | Deployment/Ops |
| ASM-004 | AOI and grid processing can run in a metric CRS suitable for 10,000m cells and area calculation. | High | Geospatial Engineering |

### Open Questions

| ID | Question | Blocking? | Owner |
| --- | --- | --- | --- |
| Q-001 | Which API status values should be shown as-is vs normalized labels in UI? | No | Product + Integration |
| Q-002 | Should tracking support bulk `Mark Accepted` in v1? | No | Product Owner |

## 4. Requirements

| Requirement ID | Type | Statement | Source Objective | Rationale | Priority | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-F-001 | Functional | The system shall render `Collection Requests` with sibling tabs `Ad-hocs` and `Mosaic`. | OBJ-004 | Preserve existing workflow while adding Mosaic. | Must | QGIS Plugin Team |
| REQ-F-002 | Functional | The system shall render nested tabs `Create` and `Tracking` inside `Mosaic`. | OBJ-001 | Separate creation flow from operations flow. | Must | QGIS Plugin Team |
| REQ-F-003 | Functional | The system shall accept a valid AOI polygon input in `Mosaic/Create` using existing plugin AOI selection mechanisms. | OBJ-001 | Enable operator-defined area planning. | Must | QGIS Plugin Team |
| REQ-F-004 | Functional | The system shall generate a 10,000m x 10,000m world grid and clip it to AOI when `Breakdown AOI` is executed. | OBJ-001 | Standardized tiling geometry. | Must | Geospatial Engineering |
| REQ-F-005 | Functional | The system shall discard empty intersections and assign a unique `tile_id` to each resulting clipped tile within a project. | OBJ-001 | Ensure valid, addressable tile set. | Must | Geospatial Engineering |
| REQ-F-006 | Functional | The system shall display clipped tiles on the map and in a table with columns `tile_id` and `clipped_area_km2`. | OBJ-001 | Pre-submit inspection and operator confidence. | Must | QGIS Plugin Team |
| REQ-F-007 | Functional | The system shall compute and display `estimated_price_usd = sum(clipped_area_km2) * 8.0` after AOI breakdown. | OBJ-001 | Pricing transparency before submission. | Must | QGIS Plugin Team |
| REQ-F-008 | Functional | The system shall require `Project ID` entry before enabling `Accept` in `Mosaic/Create`. | OBJ-002 | Prevent untracked submissions. | Must | QGIS Plugin Team |
| REQ-F-009 | Functional | The system shall reject `Project ID` values that are empty, contain filesystem-unsafe characters, or exceed 64 characters. | OBJ-002 | Prevent invalid storage paths. | Must | QGIS Plugin Team |
| REQ-F-010 | Functional | The system shall reject `Accept` when `Project ID` already exists in the active campaign mosaic namespace. | OBJ-002 | Enforce campaign-level uniqueness. | Must | QGIS Plugin Team |
| REQ-F-011 | Functional | The system shall create project folder `<campaign>/collections/mosaic/<project_id>/` when `Accept` succeeds. | OBJ-002 | Deterministic project storage location. | Must | QGIS Plugin Team |
| REQ-F-012 | Functional | The system shall write a shapefile of clipped tile geometries to the project folder with fields `tile_id` and `clipped_area_km2`. | OBJ-001 | Durable geospatial artifact for audit/reuse. | Must | Geospatial Engineering |
| REQ-F-013 | Functional | The system shall create a SQLite database in the project folder with tables for project, tile, attempt, and tile status history. | OBJ-002 | Persistent local system-of-record. | Must | QGIS Plugin Team |
| REQ-F-014 | Functional | The system shall submit one area-collect request per tile after project acceptance. | OBJ-002 | Execute requested collections tile-by-tile. | Must | Tasking Integration |
| REQ-F-015 | Functional | The system shall persist one attempt record per submission with `tile_id`, `collection_id` when available, request timestamp, and error details when failed. | OBJ-002 | Full attempt traceability and diagnostics. | Must | QGIS Plugin Team |
| REQ-F-016 | Functional | The system shall continue processing remaining tiles when one tile submission fails. | OBJ-002 | Avoid all-or-nothing failure behavior. | Must | Tasking Integration |
| REQ-F-017 | Functional | The system shall let users select a mosaic project in `Tracking` and list tiles with `tile_id`, `clipped_area_km2`, `api_status`, `qa_status`, `latest_collection_id`, `attempt_count`, and `last_sync_at`. | OBJ-003 | Provide operational tile visibility. | Must | QGIS Plugin Team |
| REQ-F-018 | Functional | The system shall refresh API status only for tiles where `qa_status != Accepted` when `Refresh Status` is clicked. | OBJ-003 | Focus polling on unresolved work. | Must | Tasking Integration |
| REQ-F-019 | Functional | The system shall allow users to set `qa_status=Accepted` per tile and persist `accepted_at` and `accepted_by`. | OBJ-003 | Manual QA closeout and accountability. | Must | QGIS Plugin Team |
| REQ-F-020 | Functional | The system shall allow `Re-task` only for tiles where `qa_status != Accepted`, creating a new attempt and updating `latest_collection_id` on success. | OBJ-003 | Support repeated tasking until QA closure. | Must | QGIS Plugin Team |
| REQ-F-021 | Functional | The system shall load project, tile, and attempt state from SQLite when the plugin restarts and a project is reopened. | OBJ-002 | Session continuity and recoverability. | Should | QGIS Plugin Team |
| REQ-BR-001 | Business Rule | The system shall compute price from AOI-intersection area, not full 100 km2 tile area. | OBJ-001 | Pricing decision from stakeholder. | Must | Product Owner |
| REQ-BR-002 | Business Rule | The system shall not auto-set `qa_status=Accepted` when API reports `Completed`. | OBJ-003 | QA acceptance remains manual. | Must | Product Owner |
| REQ-BR-003 | Business Rule | The system shall exclude `qa_status=Accepted` tiles from both `Refresh Status` and `Re-task` actions. | OBJ-003 | Accepted is terminal for operations. | Must | Product Owner |
| REQ-BR-004 | Business Rule | The system shall enforce `Project ID` uniqueness per campaign and allow the same ID in different campaigns. | OBJ-002 | Campaign-local namespace governance. | Must | Product Owner |
| REQ-NF-001 | Non-Functional | The system shall produce deterministic tile sets and pricing such that repeated breakdowns of identical AOI/settings vary by no more than `0.01 km2` total area. | OBJ-001 | Reproducible planning outputs. | Should | Geospatial Engineering |
| REQ-NF-002 | Non-Functional | The system shall wrap project creation and persistence writes in transactions so failures do not leave orphan tile-attempt links. | OBJ-002 | Data integrity under partial failure. | Must | QGIS Plugin Team |
| REQ-NF-003 | Non-Functional | The system shall complete AOI breakdown plus price computation in `<= 20 s` for inputs producing up to `2,000` clipped tiles on reference operator hardware. | OBJ-001 | Usable latency target. | Should | Geospatial Engineering |
| REQ-NF-004 | Non-Functional | The system shall record audit fields `created_at`, `updated_at`, and mutation source for tile status transitions and re-task actions. | OBJ-002 | Auditability and post-incident analysis. | Must | QGIS Plugin Team |

## 5. Acceptance Criteria

| AC ID | Requirement ID | Criterion |
| --- | --- | --- |
| AC-001 | REQ-F-001 | Given `Collection Requests` is opened, when tabs render, then `Ad-hocs` and `Mosaic` are visible in the same row. |
| AC-002 | REQ-F-002 | Given `Mosaic` is opened, when nested tabs render, then `Create` and `Tracking` are visible. |
| AC-003 | REQ-F-003 | Given a valid AOI polygon is provided through plugin AOI selection, when `Breakdown AOI` is clicked, then processing starts without AOI-validation errors. |
| AC-004 | REQ-F-004 | Given a valid AOI, when breakdown runs, then intermediate grid cell size is exactly 10,000m x 10,000m before clipping. |
| AC-005 | REQ-F-005 | Given breakdown output, when tiles are materialized, then all tiles have non-empty geometry and unique `tile_id` values. |
| AC-006 | REQ-F-006 | Given breakdown success, when UI updates, then map layer tile count equals table row count and all `tile_id` values match. |
| AC-007 | REQ-F-007 | Given clipped tiles exist, when price is displayed, then value equals `sum(clipped_area_km2) * 8.0` with configured rounding. |
| AC-008 | REQ-F-008 | Given no `Project ID`, when user attempts to accept, then `Accept` is disabled or blocked with validation feedback. |
| AC-009 | REQ-F-009 | Given invalid `Project ID` format, when `Accept` is clicked, then creation is blocked and reason is shown. |
| AC-010 | REQ-F-010 | Given a duplicate `Project ID` in campaign scope, when `Accept` is clicked, then request is rejected and no files are created. |
| AC-011 | REQ-F-011 | Given a valid new project, when accept succeeds, then folder exists at `<campaign>/collections/mosaic/<project_id>/`. |
| AC-012 | REQ-F-012 | Given project acceptance, when shapefile export completes, then all tile geometries are clipped-to-AOI and include required fields. |
| AC-013 | REQ-F-013 | Given project acceptance, when DB initialization completes, then required tables exist and project/tile rows are inserted. |
| AC-014 | REQ-F-014 | Given N tiles, when submission runs, then exactly N tile-level area-collect requests are attempted. |
| AC-015 | REQ-F-015 | Given submission results, when persistence completes, then each tile has a new attempt row with success or failure details. |
| AC-016 | REQ-F-016 | Given one tile submission fails, when batch processing continues, then other tiles are still attempted and failure is recorded for failed tile. |
| AC-017 | REQ-F-017 | Given a selected project in tracking, when list loads, then required columns are populated per tile. |
| AC-018 | REQ-F-018 | Given mixed tile states, when `Refresh Status` is clicked, then only `qa_status != Accepted` tiles trigger API status requests. |
| AC-019 | REQ-F-019 | Given a non-accepted tile, when user marks it accepted, then `qa_status=Accepted`, `accepted_at`, and `accepted_by` are persisted. |
| AC-020 | REQ-F-020 | Given a non-accepted tile with prior attempts, when `Re-task` succeeds, then attempt count increments and prior attempts remain unchanged. |
| AC-021 | REQ-F-021 | Given plugin restart, when project is reopened, then tiles, attempts, and latest statuses are restored from SQLite. |
| AC-022 | REQ-BR-001 | Given a partially covered tile, when price is computed, then only intersection area contributes to the price. |
| AC-023 | REQ-BR-002 | Given API status `Completed`, when status refresh runs, then tile is not auto-marked `Accepted`. |
| AC-024 | REQ-BR-003 | Given `qa_status=Accepted`, when user runs refresh or re-task actions, then that tile is excluded from both operations. |
| AC-025 | REQ-BR-004 | Given two campaigns, when same `Project ID` is used in each, then both are permitted; duplicate only fails within one campaign. |
| AC-026 | REQ-NF-001 | Given repeated runs with same AOI/settings, when comparing totals, then total area difference is <= `0.01 km2`. |
| AC-027 | REQ-NF-002 | Given injected write failure during persistence, when transaction rolls back, then no orphan links remain between tiles and attempts. |
| AC-028 | REQ-NF-003 | Given AOI producing <= `2,000` tiles, when breakdown+pricing executes on reference hardware, then runtime is <= `20 s`. |
| AC-029 | REQ-NF-004 | Given status mutation or re-task action, when persistence completes, then `created_at`/`updated_at` and mutation source are present. |

## 6. Verification Plan

| Verification ID | Requirement ID | Method | Evidence | Test Owner |
| --- | --- | --- | --- | --- |
| TC-001 | REQ-F-001 | Inspection | UI tab rendering evidence | QA |
| TC-002 | REQ-F-002 | Inspection | Nested tab rendering evidence | QA |
| TC-003 | REQ-F-003 | Integration Test | AOI input acceptance tests | QA |
| TC-004 | REQ-F-004 | Analysis + Test | Grid dimension validation report | Geospatial QA |
| TC-005 | REQ-F-005 | Unit + Integration Test | Tile uniqueness/non-empty checks | QA |
| TC-006 | REQ-F-006 | Integration Test | Map-table consistency assertions | QA |
| TC-007 | REQ-F-007 | Unit Test | Pricing formula tests | QA |
| TC-008 | REQ-F-008 | UI/Integration Test | Missing project-id validation test | QA |
| TC-009 | REQ-F-009 | UI/Integration Test | Invalid project-id validation test | QA |
| TC-010 | REQ-F-010 | Integration Test | Duplicate project-id rejection test | QA |
| TC-011 | REQ-F-011 | Integration Test | Folder creation path check | QA |
| TC-012 | REQ-F-012 | Geospatial Test | Shapefile geometry+field inspection | Geospatial QA |
| TC-013 | REQ-F-013 | Integration Test | SQLite schema and seed-row assertions | QA |
| TC-014 | REQ-F-014 | Integration Test | One-attempt-per-tile submission test | Integration QA |
| TC-015 | REQ-F-015 | Integration Test | Attempt row persistence test | QA |
| TC-016 | REQ-F-016 | Resilience Test | Partial failure continuation scenario | Integration QA |
| TC-017 | REQ-F-017 | UI/Integration Test | Tracking table field coverage test | QA |
| TC-018 | REQ-F-018 | Integration Test | Accepted-tile refresh exclusion test | QA |
| TC-019 | REQ-F-019 | Integration Test | Manual acceptance persistence test | QA |
| TC-020 | REQ-F-020 | Integration Test | Re-task creates new attempt test | QA |
| TC-021 | REQ-F-021 | Integration Test | Restart reload from SQLite test | QA |
| TC-022 | REQ-BR-001 | Analysis + Unit Test | Intersection-area pricing assertion | QA |
| TC-023 | REQ-BR-002 | Integration Test | Completed-not-accepted behavior test | QA |
| TC-024 | REQ-BR-003 | Integration Test | Accepted terminal behavior test | QA |
| TC-025 | REQ-BR-004 | Integration Test | Campaign-local uniqueness test | QA |
| TC-026 | REQ-NF-001 | Determinism Test | Repeated-run area variance report | QA |
| TC-027 | REQ-NF-002 | Failure Injection Test | Transaction rollback integrity report | QA |
| TC-028 | REQ-NF-003 | Performance Test | Benchmark timing logs | Performance QA |
| TC-029 | REQ-NF-004 | Integration Test | Audit field persistence checks | QA |

## 7. Requirement Traceability Matrix

RTM CSV path:

- `qgis_plugin/docs/2026-02-25/collection-requests-mosaic-rtm.csv`

Coverage status at revision `v2`:

- Objective to requirement coverage: complete
- Requirement to acceptance criteria coverage: complete
- Requirement to verification coverage: complete
- Orphans: none

## 8. Implementation Plan

### Phase 1: Data And Domain Foundation

- Implement SQLite schema and repository methods for project, tile, attempt, status history.
- Implement project path resolver and project-id validation service.
- Exit criteria:
  - `REQ-F-009`, `REQ-F-010`, `REQ-F-011`, `REQ-F-013`, `REQ-NF-002`, `REQ-NF-004`

### Phase 2: Mosaic Create Workflow

- Build `Mosaic/Create` UI and connect to backend tiling/pricing service.
- Implement `Breakdown AOI`, map/table preview, and price display.
- Implement `Accept` flow with shapefile export and initial submission.
- Exit criteria:
  - `REQ-F-001` to `REQ-F-008`, `REQ-F-012`, `REQ-F-014` to `REQ-F-016`, `REQ-BR-001`, `REQ-NF-001`, `REQ-NF-003`

### Phase 3: Mosaic Tracking Workflow

- Build `Mosaic/Tracking` project selector and tile table view.
- Implement `Refresh Status`, `Mark Accepted`, and `Re-task`.
- Enforce accepted-terminal behavior in refresh and retask paths.
- Exit criteria:
  - `REQ-F-017` to `REQ-F-021`, `REQ-BR-002`, `REQ-BR-003`, `REQ-BR-004`

### Phase 4: Verification And Hardening

- Execute all `TC-*` items and close failures.
- Validate determinism/performance thresholds.
- Capture release notes with known limitations tied to `Q-*`.
- Exit criteria:
  - `AC-001` to `AC-029` all pass or formally waived.

## 9. Coverage Gaps And Risks

### Gaps

1. API status normalization map is not finalized (`Q-001`).
2. Bulk acceptance UX for tracking remains undecided (`Q-002`).

### Risks

1. Large AOIs may breach `REQ-NF-003` if geometry operations are not optimized.
2. Weak API error messaging may reduce operator ability to diagnose failed attempts.
3. Campaign folder permission issues can block persistence despite valid input.

### Recommended Next Actions

1. Approve this `v2` requirements baseline and RTM.
2. Resolve `Q-001` before implementation of status labels.
3. Resolve `Q-002` before UI freeze for tracking actions.
4. Start implementation in phase order and tag pull requests with impacted `REQ-*` IDs.
