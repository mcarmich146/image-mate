# QGIS Plugin Phase 0/1 Backlog

## 1. Scope

This backlog covers:
- **Phase 0**: foundation and architecture setup
- **Phase 1**: Explore MVP (AOI + search + result visualization + imagery load)

Out of scope for this backlog:
- Tasking execution UX
- Monitoring/cues UX
- Workflow/runs orchestration UX
- Animation/report generation UX


## 2. Execution Model

Recommended cadence:
- 2-week spike, single stream with daily integration.

Suggested priorities:
- `P0`: blocker, must be done first
- `P1`: required for MVP
- `P2`: valuable hardening, can follow MVP

Status values:
- `Todo`
- `In Progress`
- `Done`
- `Blocked`


## 3. Ticket Backlog

## Phase 0: Foundation

### QP-001 Plugin skeleton and packaging baseline
- Priority: `P0`
- Status: `Todo`
- Depends on: none
- Description:
  - Create base QGIS plugin structure and load/unload entrypoints.
  - Define package layout for `ui/`, `controllers/`, `services/`, `storage/`.
- Acceptance criteria:
  1. Plugin installs in QGIS dev profile.
  2. Plugin appears in menu/toolbar and can be enabled/disabled without errors.
  3. `qgis_plugin` module import has no side effects that require credentials/network.

### QP-002 Dependency strategy for backend code reuse
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-001`
- Description:
  - Decide and implement how plugin reuses backend modules from `backend/app/*`.
  - Remove hard dependency on FastAPI objects/routes.
- Acceptance criteria:
  1. Reuse path documented (import strategy and constraints).
  2. Provider logic (`source_manager` and clients) callable from plugin service layer.
  3. No plugin import-time dependency on starting backend server.

### QP-003 Configuration and settings service
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-001`
- Description:
  - Implement plugin settings abstraction over `QSettings`.
  - Define provider config fields and defaults.
- Acceptance criteria:
  1. Settings can be saved/reloaded across QGIS restarts.
  2. Distinguish required vs optional settings per provider.
  3. Invalid config states are surfaced in UI as actionable messages.

### QP-004 Auth service with QGIS Auth Manager
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-003`
- Description:
  - Add credentials flow using QGIS auth infrastructure.
  - Avoid storing plaintext long-lived tokens in plugin files.
- Acceptance criteria:
  1. Credentials are referenced via auth config IDs (or equivalent secure storage), not plain text files.
  2. Satellogic auth mode can be selected (OAuth/key-secret/bearer fallback).
  3. Token refresh path functions for OAuth-enabled providers.

### QP-005 Async task framework (`QgsTask`) and error surface
- Priority: `P1`
- Status: `Todo`
- Depends on: `QP-001`
- Description:
  - Standardize background execution for network/search calls.
  - Ensure cancellation and user feedback are consistent.
- Acceptance criteria:
  1. Long operations run outside UI thread.
  2. User sees progress and terminal state (success/failure/cancelled).
  3. Exceptions are logged and mapped to readable UI errors.

### QP-006 Observability and debug logging conventions
- Priority: `P2`
- Status: `Todo`
- Depends on: `QP-001`
- Description:
  - Define plugin logger channels and debug toggle.
  - Add request correlation ID per operation.
- Acceptance criteria:
  1. Logs include operation ID, provider, duration, status.
  2. Debug mode can be toggled without code changes.
  3. Failures include enough context for triage (no secret leakage).


## Phase 1: Explore MVP

### QP-101 Main dock widget and Explore tab shell
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-001`
- Description:
  - Create a dock widget with Explore tab controls:
    - source selector
    - date range
    - cloud/GSD/satellite filters
    - search action
- Acceptance criteria:
  1. Dock opens/closes reliably.
  2. Explore controls validate input before dispatch.
  3. Invalid inputs show inline messages.

### QP-102 AOI capture tool integration
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-101`
- Description:
  - Implement AOI acquisition from map:
    - draw rectangle/polygon
    - optionally use current extent
- Acceptance criteria:
  1. AOI geometry is captured as valid GeoJSON-like polygon.
  2. AOI can be replaced/reset.
  3. Search is blocked until AOI or “use extent” is available.

### QP-103 Source/collections/contracts bootstrap
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-002`, `QP-004`, `QP-101`
- Description:
  - Populate source list and source-specific collections/contracts.
- Acceptance criteria:
  1. Sources load from service layer.
  2. Collection dropdown updates when source changes.
  3. Contract selector is shown/enabled only when source supports contracts.

### QP-104 Archive search controller and service wiring
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-102`, `QP-103`, `QP-005`
- Description:
  - Execute archive search against selected source and filters.
  - Normalize results to canonical scene model.
- Acceptance criteria:
  1. Search returns items with expected fields (`id`, `datetime`, `geometry`, `assets`, etc.).
  2. Empty results are handled cleanly.
  3. Search failures show provider-specific error context.

### QP-105 Results layer rendering (vector footprints)
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-104`
- Description:
  - Render scene footprints as a QGIS vector layer.
  - Include useful attributes (source, datetime, cloud, gsd, item id).
- Acceptance criteria:
  1. Layer is created/refreshed per search.
  2. Feature count matches search result count.
  3. Layer styling distinguishes sources at minimum.

### QP-106 Result selection and detail panel
- Priority: `P1`
- Status: `Todo`
- Depends on: `QP-105`
- Description:
  - Add selectable results list/table.
  - Show selected scene metadata and available assets.
- Acceptance criteria:
  1. Selecting a row highlights matching feature on map.
  2. Metadata panel updates correctly.
  3. Missing asset URLs are handled without crashes.

### QP-107 Raster load for selected scene (preview/visual)
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-106`, `QP-004`
- Description:
  - Load selected scene asset into QGIS map as raster layer.
  - Prefer preview first, support full visual where feasible.
- Acceptance criteria:
  1. User can load at least one renderable asset from selected scene.
  2. Layer naming convention includes source + datetime + item id.
  3. Auth headers/tokens are correctly applied to protected URLs.

### QP-108 Sentinel WMTS layer integration
- Priority: `P1`
- Status: `Todo`
- Depends on: `QP-103`, `QP-004`
- Description:
  - Add Merlin Sentinel WMTS base layer using QGIS native WMTS provider.
  - Keep per-layer config options (instance/layer/time where applicable).
- Acceptance criteria:
  1. WMTS layer adds successfully when configured.
  2. Misconfiguration surfaces clear diagnostics.
  3. User can toggle WMTS visibility independently of search layers.

### QP-109 Search result export (GeoJSON/CSV metadata)
- Priority: `P2`
- Status: `Todo`
- Depends on: `QP-105`
- Description:
  - Export search result footprints and metadata.
- Acceptance criteria:
  1. GeoJSON export contains all rendered features.
  2. CSV export includes key scene fields.
  3. Export path and overwrite behavior are explicit.

### QP-110 Explore MVP integration test pass
- Priority: `P0`
- Status: `Todo`
- Depends on: `QP-101`..`QP-108`
- Description:
  - Run end-to-end smoke scenarios for both sources.
- Acceptance criteria:
  1. Scenario A (`satellogic`) completes AOI -> search -> select -> load asset.
  2. Scenario B (`merlin-s2`) completes AOI -> search -> select -> load WMTS or scene asset.
  3. No unhandled exceptions during normal operator flow.


## 4. Suggested Sprint Slice (2 Weeks)

Week 1 (must complete):
1. `QP-001`
2. `QP-002`
3. `QP-003`
4. `QP-004`
5. `QP-101`
6. `QP-102`
7. `QP-103`

Week 2 (must complete):
1. `QP-005`
2. `QP-104`
3. `QP-105`
4. `QP-106`
5. `QP-107`
6. `QP-110`

Stretch:
1. `QP-108`
2. `QP-006`
3. `QP-109`


## 5. Test Scenarios and Exit Criteria

## Mandatory test scenarios

### TS-01 Plugin lifecycle
1. Enable plugin.
2. Open dock.
3. Disable plugin.
Expected: no crashes, no residual map tools locked.

### TS-02 Satellogic search path
1. Configure auth and contract.
2. Draw AOI.
3. Run search with filters.
4. Select result and load preview/visual.
Expected: results rendered and selected asset visible on map.

### TS-03 Merlin search path
1. Configure CDSE credentials.
2. Draw AOI.
3. Search Sentinel collection.
4. Load selected asset or WMTS layer.
Expected: imagery appears; failures are actionable.

### TS-04 Failure handling
1. Break credentials.
2. Run search/load.
Expected: user gets clear error with provider context; plugin remains responsive.

## Phase 1 exit criteria
1. All `P0` Phase 0/1 tickets are `Done`.
2. TS-01 through TS-04 pass.
3. No permanent bearer token required in plugin files for normal operation.


## 6. Ownership Template

Use this template per ticket:
- Owner:
- Reviewer:
- Priority:
- Status:
- ETA:
- Risks:
- Notes:


## 7. Immediate Next Actions

1. Confirm if this backlog should be tracked in GitHub Issues, Linear, or a markdown checklist.
2. Assign owners for `QP-001` through `QP-004`.
3. Start `QP-001` and `QP-002` in parallel if two engineers are available.
