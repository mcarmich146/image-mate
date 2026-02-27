# Resample 10m Geoprocessing Action Design and Implementation Plan

- Date: 2026-02-23
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
Add a new Geoprocessing action to resample imagery to 10 m pixel resolution, and rename the existing "Image Enhancement" group to "Image Processing".

## Existing Reusable Components
- Existing utilities tab builder in `ui/main_dock.py` with Create VRT / Sharpen wiring.
- Existing signal-to-handler plugin wiring in `plugin.py` (`show_dock`).
- Existing campaign output helper:
  - `_campaign_geoprocessing_output_path(...)`
- Existing raster-layer lookup and local source validation:
  - `_project_raster_layer_by_id(...)`
  - `_resolve_local_raster_source_path(...)`
- Existing GDAL processing bootstrap:
  - `_ensure_processing_runtime(required_algorithms=...)`

## Proposed Backend Changes
- Add new plugin handler:
  - `handle_resample_image_10m_request(payload)`
- Execution behavior:
  - Resolve input raster layer from project.
  - Require local raster source path.
  - Resolve campaign output `.tif` path.
  - Run `gdal:warpreproject` with `TARGET_RESOLUTION=10.0` and bilinear resampling.
  - Add output raster to Image Mate group.
- CRS handling:
  - If source CRS map units are meters: resample in source CRS.
  - If source CRS is non-meter: reproject to `EPSG:3857` and log a warning note.

## UI Wiring Changes (Minimal)
- Rename utilities group title:
  - `Image Enhancement` -> `Image Processing`
- Add button to that group:
  - `Resample to 10m`
- Add dialog for request payload (input raster + optional output label), fixed target resolution at 10 m.
- Emit new thin signal:
  - `resample_image_10m_requested(dict)`

## Implementation Steps
1. Add new UI signal and button/dialog in `ui/main_dock.py`.
2. Connect signal in `plugin.py` `show_dock`.
3. Implement backend handler in `plugin.py` using existing helper utilities.
4. Validate compilation and scope.
5. Sync updated files to installed plugin profile for immediate QGIS use.

## Terminal-Only Test Plan
- Compile checks:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/plugin.py`
- Scope checks:
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- Derive checklist:
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback
- Risk: non-meter CRS could make "10 m" ambiguous.
  - Mitigation: force reproject to `EPSG:3857` for non-meter sources and log warning.
- Rollback:
  - Remove the new button + signal hookup and handler while retaining existing geoprocessing actions.
