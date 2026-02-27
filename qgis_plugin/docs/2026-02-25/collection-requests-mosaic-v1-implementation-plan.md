# Collection Requests Mosaic V1 Implementation Design and Implementation Plan

- Date: 2026-02-25
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
Implement Mosaic collection workflow under `Collection Requests` while preserving existing ad-hoc tasking behavior. The feature must support AOI breakdown into 10km x 10km clipped tiles, clipped-area pricing, campaign-local persistence (shapefile + SQLite), per-tile tasking submission, and tracking with manual acceptance + re-task.

## Existing Reusable Components
- Existing `Collection Requests` UI and plugin signal wiring:
  - `ui/main_dock.py::_build_tasking_tab`
  - `plugin.py::handle_tasking_*`
- Existing geometry source helpers:
  - `_current_extent_geometry_wgs84`
  - `_simulation_polygon_layer_geometry_wgs84`
- Existing campaign path management:
  - `services/campaign_storage_service.py`
- Existing tasking API integration seam:
  - `services/source_service.py::create_tasking_order/get_tasking_order`

## Proposed Backend Changes
- Add Mosaic contracts/constants module:
  - `services/mosaic_contracts.py`
- Add AOI tiling and pricing service:
  - `services/mosaic_grid_service.py`
- Add SQLite persistence store:
  - `services/mosaic_tracking_store.py`
- Add tasking orchestration service:
  - `services/mosaic_tasking_service.py`
- Extend campaign storage service with Mosaic project paths:
  - `campaign_mosaic_root`
  - `campaign_mosaic_project_dir`
  - project file helpers for shapefile/db/meta
  - project listing + existence checks
- Add plugin orchestration handlers:
  - `handle_mosaic_breakdown_request`
  - `handle_mosaic_accept_request`
  - `handle_mosaic_tracking_project_changed`
  - `handle_mosaic_refresh_status_request`
  - `handle_mosaic_mark_accepted_request`
  - `handle_mosaic_retask_request`
  - `handle_mosaic_refresh_projects_request`

## UI Wiring Changes (Minimal)
- Refactor Collection Requests into sub-tabs:
  - `Ad-hocs` (existing behavior unchanged)
  - `Mosaic`
- Add nested Mosaic tabs:
  - `Create`
  - `Tracking`
- Add thin UI-only signals + setters:
  - request signals for breakdown/accept/refresh/accept/retask
  - state setters for create status, tracking status, rows, project list, and estimated price

## Implementation Steps
1. Add Mosaic backend modules (`contracts`, `grid`, `tracking_store`, `tasking_service`).
2. Extend campaign storage service with campaign-local Mosaic path helpers.
3. Add plugin state + handler wiring for new Mosaic signals.
4. Implement AOI breakdown flow (map extent or polygon layer) and clipped-area pricing.
5. Implement accept flow:
   - project id validation
   - uniqueness check per campaign
   - shapefile write
   - SQLite project/tile creation
   - per-tile tasking attempts with continue-on-failure
6. Implement tracking flow:
   - project loading
   - status refresh for non-accepted tiles
   - manual accept
   - re-task for non-accepted tiles only
7. Add smoke tests for validation/store/rules/submission/pacing.

## Terminal-Only Test Plan
- Compile checks:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/mosaic_contracts.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/mosaic_grid_service.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/mosaic_tracking_store.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/mosaic_tasking_service.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/plugin.py`
- Smoke checks:
  - `py -3 qgis_plugin/test/mosaic_project_validation_smoke.py`
  - `py -3 qgis_plugin/test/mosaic_tracking_store_smoke.py`
  - `py -3 qgis_plugin/test/mosaic_status_rules_smoke.py`
  - `py -3 qgis_plugin/test/mosaic_submission_payload_smoke.py`
  - `py -3 qgis_plugin/test/mosaic_grid_pricing_smoke.py`
- Scope and derived test checks:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback
- Risk: Large AOI breakdown performance may degrade on low-resource endpoints.
  - Mitigation: deterministic grid loop, simple clipping path, and scoped performance smoke.
- Risk: API status semantics vary by backend order states.
  - Mitigation: display raw API status and keep manual acceptance terminal.
- Risk: Non-satellogic source selected during Mosaic actions.
  - Mitigation: enforce source-gated network actions and emit actionable UI status.

Rollback strategy:
1. Remove Mosaic signal wiring from plugin.
2. Revert `_build_tasking_tab` to ad-hoc-only layout.
3. Remove Mosaic service modules and tests.
4. Keep existing ad-hoc tasking code path intact.
