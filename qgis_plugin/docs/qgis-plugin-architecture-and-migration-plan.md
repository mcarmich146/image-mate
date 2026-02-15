# QGIS Plugin Architecture and Migration Plan

## 1. Goal

Convert `image-mate` from a web app (FastAPI + Leaflet frontend) into a QGIS plugin while preserving the highest-value operational capabilities.

Primary objective:
- Keep existing source/provider logic and GEOINT workflows.
- Replace web UI/runtime concerns with native QGIS UX patterns.
- Remove dependence on permanent bearer token storage and use safer credential handling.


## 2. Current System Snapshot

Current stack:
- Backend API and orchestration: `backend/app/main.py`
- Provider/source clients:
  - `backend/app/satellogic_client.py`
  - `backend/app/merlin_sentinel2_client.py`
  - `backend/app/source_manager.py`
- Analysis/media services:
  - `backend/app/services.py`
  - `backend/app/geoagent.py`
- Monitoring state:
  - `backend/app/monitoring_store.py`
- Web UI:
  - `frontend/index.html`
  - `frontend/app.js`


## 3. Feature Transferability

Estimated transferability if we reuse backend Python modules in-plugin:
- Total transfer: `~70-80%`

Estimated transferability if we rewrite most logic for plugin-only implementation:
- Total transfer: `~50-60%`

### High transfer
- Archive search and source abstraction (`/api/archive/search`)
- Contracts/collections/source discovery (`/api/contracts`, `/api/collections`, `/api/sources`)
- Satellogic tasking operations (`/api/tasking/*`)
- Sentinel WMTS use (prefer direct QGIS WMTS layer over custom proxy where possible)
- Monitoring/cues storage patterns (SQLite-backed)
- GeoAgent report generation flow

### Medium transfer
- ZIP asset bundling/downloading
- Animation/GIF and MP4 generation pipelines
- Workbench workflows/runs/schedules model

### Low direct transfer
- Leaflet-specific interactions and state machine (`frontend/app.js`)
- FastAPI route layer itself (unless retained as optional local sidecar)


## 4. Recommended Plugin Architecture

Create a layered plugin:

1. `ui/` (PyQt + QGIS widgets)
- Main dock widget with tabs:
  - Explore
  - Tasking
  - Monitoring
  - Workflows/Runs
- AOI drawing tools using `QgsMapTool`/QGIS digitizing.

2. `domain/` (reused/adapted logic)
- Import/adapt existing backend modules:
  - source manager
  - provider clients
  - geo report + media services
- Keep request/response normalization close to current data model.

3. `qgis_integration/`
- Convert search results into:
  - vector footprint layers
  - optional memory layers for session state
- Add raster layers:
  - Sentinel WMTS (native provider)
  - full-res assets as raster layers when available

4. `infra/`
- Credential manager (QGIS Auth Manager integration)
- settings persistence (`QSettings`)
- async jobs (`QgsTask`) for network/media/report work
- local state store (SQLite)


## 5. Security and Auth Design

Current concern:
- historical use of permanent bearer token.

Plugin direction:
- Prefer OAuth client credentials where supported.
- Store secrets in QGIS authentication system, not plain plugin files.
- Keep contract selection explicit and scoped per request.
- Add token refresh handling in a central auth service.


## 6. API/Logic Reuse Strategy

Use existing backend code as a library first, then peel off web concerns.

Approach:
1. Extract or wrap reusable logic from `backend/app/*` that does not require FastAPI objects.
2. Replace endpoint calls with direct function/service invocations from plugin controllers.
3. Keep data contracts mostly unchanged to reduce rewrite and regression risk.

Pragmatic rule:
- Reuse provider/search/tasking/report/media code.
- Rewrite web-only orchestration and view-state logic.


## 7. Proposed Plugin Modules (Initial)

- `qgis_plugin/plugin.py`
  - plugin entrypoint, action registration, lifecycle hooks
- `qgis_plugin/ui/main_dock.py`
  - dock widget + tab wiring
- `qgis_plugin/controllers/search_controller.py`
  - AOI/date/filter search and layer creation
- `qgis_plugin/controllers/tasking_controller.py`
  - create/list/update tasking orders
- `qgis_plugin/controllers/monitoring_controller.py`
  - subscriptions/events/cues
- `qgis_plugin/services/auth_service.py`
  - credentials, token retrieval/refresh
- `qgis_plugin/services/source_service.py`
  - wraps source manager + provider clients
- `qgis_plugin/services/report_service.py`
  - geoagent report generation
- `qgis_plugin/services/media_service.py`
  - GIF/MP4 workflows
- `qgis_plugin/storage/state_store.py`
  - SQLite-backed monitoring/workflow local state


## 8. Migration Plan

### Phase 0: Foundation
- Set plugin skeleton and dependency strategy.
- Decide packaging approach for backend module reuse.
- Establish auth handling with QGIS Auth Manager.

### Phase 1: Explore MVP
- AOI draw/select in map canvas.
- Archive search with filters.
- Result footprints on map + attributes table.
- Load selected imagery layers.

### Phase 2: Tasking + Downloads
- List tasking products/projects/orders.
- Submit point/area tasking requests.
- Download selected assets/zip bundles.

### Phase 3: Analytics + Reporting
- Time-series selection.
- GIF/MP4 generation from selected scenes.
- GeoAgent report generation and artifact export.

### Phase 4: Monitoring + Workbench
- Monitoring subscriptions/events/cues.
- Workflow/runs/schedules integration (as needed for user operations).


## 9. “Next Step” Recommendation

Start with a **2-week Explore MVP spike** focused on Phase 1 only.

Deliverables:
1. Plugin loads in QGIS and opens dock.
2. AOI draw tool works.
3. Search works against both sources (`satellogic`, `merlin-s2`).
4. Results render as vector footprints with key attributes.
5. Selecting a result loads preview/visual layer.
6. Credential setup flow (no permanent token hardcoded in plugin files).

Why this first:
- It validates the hardest architectural choices (module reuse, auth, QGIS layer integration) before building tasking/workflow UX.


## 10. Risks and Mitigations

- Risk: tight coupling to FastAPI route functions.
  - Mitigation: thin adapter services around reusable domain logic.
- Risk: UI parity expectations with Leaflet timeline/compare tools.
  - Mitigation: define explicit “QGIS-native” UX rather than 1:1 port.
- Risk: credential handling complexity across providers.
  - Mitigation: central auth service and early auth validation tooling.
- Risk: performance when loading many scenes/tiles.
  - Mitigation: paging, async tasks, layer throttling, cached metadata.


## 11. Definition of Success

The migration is successful when analysts can do the core mission loop inside QGIS:
1. define AOI
2. search and inspect imagery across providers
3. create tasking requests
4. generate temporal report outputs
5. manage monitoring events/cues

without requiring the legacy web frontend.
