# Geoprocessing Resample Chain Tasks Design and Implementation Plan

- Date: 2026-02-24
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
Add resample-chain Geoprocessing -> Image Processing tasks:
- `Resample to 10.8->3m (PlanetScope)`
- `Resample to 2m->1m (Merlin)`
- `Resample to 3.76m->1m (Merlin)`

Each task must resample the selected raster in sequence (first stage, then second stage) and add the final output to the project.

## Existing Reusable Components
- Existing Geoprocessing tab and raster-layer selection dialogs in `ui/main_dock.py`.
- Existing processing runtime bootstrap in `plugin.py`:
  - `_ensure_processing_runtime(...)`
- Existing campaign output helper in `plugin.py`:
  - `_campaign_geoprocessing_output_path(...)`
- Existing local raster validation and CRS handling logic in current `handle_resample_image_10m_request`.
- Existing project layer insertion helper:
  - `_add_layer_to_image_mate_group(...)`

## Proposed Backend Changes
- Add reusable resample chain helpers in `plugin.py` so all resample actions share:
  - input-layer validation
  - output-path resolution
  - CRS/units handling
  - single GDAL warp step execution
- Keep `handle_resample_image_10m_request` but refactor it to reuse the new shared chain helper with one stage.
- Add handlers that execute fixed two-stage chains:
  - PlanetScope: `10.8m -> 3m`
  - Merlin: `2m -> 1m`
  - Merlin: `3.76m -> 1m`
- Add a shared, pure-Python workflow spec module:
  - `services/resample_workflows.py`
  - Holds action labels, operation keys, stage resolutions, and naming tokens.

## UI Wiring Changes (Minimal)
- Add new buttons under Geoprocessing -> Image Processing using workflow spec labels.
- Add UI signals emitted from thin dialog orchestration:
  - `resample_image_10p8_to_3m_requested`
  - `resample_image_2m_to_1m_requested`
  - `resample_image_3p76m_to_1m_requested`
- Reuse one generic resample request dialog builder for all fixed-resolution actions (`10m`, `10.8->3m`, `2->1m`, `3.76->1m`) to avoid duplicated UI logic.

## Implementation Steps
1. Create shared resample workflow specs in `services/resample_workflows.py`.
2. Extend `ui/main_dock.py` with resample-chain actions, signals, and thin dialog wrappers.
3. Connect new signals in `plugin.py::show_dock`.
4. Refactor and extend backend resample handling in `plugin.py` to support staged chains.
5. Add terminal smoke test for workflow presets under `qgis_plugin/test/`.
6. Run compile/smoke checks and scope validation scripts.

## Terminal-Only Test Plan
- Compile checks:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/plugin.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/resample_workflows.py`
- Smoke checks:
  - `py -3 qgis_plugin/test/resample_workflows_smoke.py`
- Scope checks:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- Derived CLI checklist:
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback
- Risk: stage 2 resampling may run against non-meter CRS input.
  - Mitigation: preserve existing behavior to force EPSG:3857 when source CRS map units are non-meter.
- Risk: intermediate files could clutter geoprocessing output storage.
  - Mitigation: keep intermediate files managed via campaign geoprocessing paths with clear operation prefixes.
- Rollback:
  - remove the two new signals/buttons and disconnect handlers
  - revert to the previous single-step `Resample to 10m` handler path
