# Mosaic Point Target 3km Update Design and Implementation Plan

- Date: 2026-02-25
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
Mosaic v1 currently builds 10km x 10km tiles and submits each tile as an area tasking request (`TSKARE-M`).
For the current contract setup, area tasking SKUs are not available, so submissions fail with `400 Invalid product`.
The workflow needs to switch to point tasking while keeping tiled-AOI planning and tracking.

User-requested deltas:
- Tile size changes to `3km x 3km`.
- Tasking submits one point target per tile using the tile center point.
- Create tab adds `Add Tasking` checkbox to control immediate submission.
- Tracking adds `Delete Mosaic` that removes the entire project directory under campaign storage.
- Tracking adds `Show Tiling` checkbox that toggles saved tiled AOI display.
- Tracking moves tile actions to per-row buttons (`Accept`, `Re-Task`) instead of bottom action buttons.
- Tracking adds per-row `Cancel` to cancel the active tasking order for a tile.
- Tiling display styling:
  - Unselected tile outline width `0.25 mm`
  - Selected tile outline width `0.75 mm`
  - Accepted tiles use light-green fill at 50% opacity
- Tracking area column label is `Area (km2)` with `#,##0.00` formatting.
- Map-to-table sync: clicking a shown tiling polygon selects and scrolls to the matching tile row (`tile_id`) in Tracking.

## Existing Reusable Components
- `MosaicGridService`: deterministic world-grid tiling and clipped-area pricing from AOI.
- `MosaicTaskingService`: per-tile submit/refresh/retask orchestration and shapefile export.
- `MosaicTrackingStore`: project/tile/attempt persistence and status model.
- `CampaignStorageService`: campaign-scoped mosaic path helpers.
- `ImageMateMainDock` + `plugin.py` Mosaic signal/handler wiring.

## Proposed Backend Changes
- Change Mosaic defaults in `mosaic_contracts.py`:
  - `GRID_SIZE_M = 3000.0`
  - `TASKING_DEFAULT_TARGET_TYPE = "point"`
  - `TASKING_DEFAULT_SKU = "TSKPOI-M"`
- Update `MosaicTaskingService`:
  - Build point geometry from tile center using grid indices (`tile_<grid_x>_<grid_y>`) in equal-area grid CRS.
  - Transform tile-center point to WGS84 for submission geometry.
  - Fallback to clipped geometry centroid when grid index cannot be resolved (older rows).
- Add `CampaignStorageService.delete_mosaic_project(campaign_uid, project_id)` for recursive project directory deletion.
- Add plugin-side Mosaic tiling layer utilities:
  - Load saved project shapefile.
  - Apply style: no fill + yellow outline with 50% transparency.
  - Track and clear active tiling preview layer id.

## UI Wiring Changes (Minimal)
- `ImageMateMainDock` new signals:
  - `mosaic_delete_requested(dict)`
  - `mosaic_show_tiling_requested(dict)`
- `Mosaic Create` accepts payload now includes `add_tasking` (default true).
- Tracking control row adds two buttons to the right of `Refresh Status`:
  - `Delete Mosaic`
  - `Show Tiling` (checkbox toggle)
- Tracking table adds action columns with per-tile buttons:
  - `Accept`
  - `Re-Task`
  - `Cancel`
- Delete action includes explicit confirmation warning that the entire project directory is removed.
- Plugin signal wiring in `show_dock()` connects new signals to handlers:
  - `handle_mosaic_delete_request`
  - `handle_mosaic_show_tiling_request`

## Implementation Steps
1. Update Mosaic constants for tile size and point-tasking defaults.
2. Update tasking payload generation to use tile-center point geometry.
3. Add campaign storage delete helper for Mosaic project directory.
4. Add UI signals/buttons and emitters for delete/show actions.
5. Add plugin handlers for delete/show and map layer rendering style.
6. Add `add_tasking` gating in accept workflow (persist-only mode).
7. Move Tracking tile actions to per-row table buttons.
8. Update Mosaic smoke tests for new defaults and limits.
9. Run terminal verification (`py_compile`, smoke scripts, scope checks).

## Terminal-Only Test Plan
- `py -3 -m py_compile` for touched modules under `qgis_plugin/image_mate_qgis_plugin`.
- `py -3 qgis_plugin/test/mosaic_project_validation_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_store_smoke.py`
- `py -3 qgis_plugin/test/mosaic_status_rules_smoke.py`
- `py -3 qgis_plugin/test/mosaic_submission_payload_smoke.py`
- `py -3 qgis_plugin/test/mosaic_grid_pricing_smoke.py` (QGIS-dependent; may skip if unavailable)
- `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback
- Risk: `tile_id` parsing for center point could fail on legacy/custom IDs.
  - Mitigation: fallback to clipped polygon centroid.
- Risk: deleting project directory removes local tracking history irreversibly.
  - Mitigation: explicit UI confirmation before deletion.
- Rollback: revert touched Mosaic files and restore previous constants (`10km`, `area`, `TSKARE-M`).
