# Explore Download Selected Vrt Naming Band Order Resampling Design and Implementation Plan

- Date: 2026-03-02
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- Explore > Collection Search supports multi-select download, but bulk selection is manual.
- Downloaded layer naming is opaque and not operator-friendly.
- L1D-SR visual band order can arrive as `Blue, Green, Red, and NIR`, so default `R=1,G=2,B=3` renders false-color.
- Downloaded imagery display defaults should enforce better interpolation and higher oversampling tolerance.

## Existing Reusable Components
- `MainDock.current_download_selected_payload()` already groups selected rows and emits download request payloads.
- `ImageMatePlugin._resolve_download_selected_groups()` already expands group item IDs into full cached search item dicts (`self.search_items`).
- `ImageMatePlugin._run_download_selected_task()` and `_on_download_selected_task_finished()` already own backend download/VRT/layer-add flow.
- Search items retain raw STAC-like payload (`item["raw"]`), allowing band-order inference from `properties`/`eo:bands` without UI changes.

## Proposed Backend Changes
- Add helpers in `plugin.py` to derive:
  - Display timestamp (`YYYY-MM-DDTHH:MM:SS`) from group item datetimes.
  - Layer name as `<timestamp> <outcome_id>` with robust fallback.
  - Band-order tokens from free-form strings (supports forms like `Blue, Green, Red, and NIR` and `RGB NIR`).
  - RGB band index mapping from token order.
- Store `display_timestamp` and `band_order_text` in each `group_result` during `_run_download_selected_task`.
- Apply rendering immediately before layer add:
  - Set renderer RGB band indices from inferred band-order map.
  - Set `QgsCubicRasterResampler` for zoomed-in and zoomed-out resampling.
  - Set max oversampling to `5.0`.

## UI Wiring Changes (Minimal)
- Add `Select All` button beside `Download Selected` in Explore search controls.
- Keep UI logic thin: `_select_all_search_results()` only checks rows, updates checked ID set, and refreshes existing backend-facing state.

## Implementation Steps
- Updated `ui/main_dock.py`:
  - Added `self.select_all_results_btn` and click wiring.
  - Implemented `_select_all_search_results`.
- Updated `plugin.py`:
  - Added naming/timestamp/band-order parsing helpers.
  - Added rendering application helper.
  - Threaded metadata through download task result and layer-add path.
- Added terminal smoke test:
  - `qgis_plugin/test/explore_download_selected_enhancements_smoke.py`

## Terminal-Only Test Plan
- Scope enforcement:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- Derived checklist:
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`
- Static behavior smoke:
  - `py -3 qgis_plugin/test/explore_download_selected_enhancements_smoke.py`
- Syntax check:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py qgis_plugin/image_mate_qgis_plugin/plugin.py`

## Risks and Rollback
- Risk: band-order metadata may be absent for some products; fallback remains existing default renderer mapping.
- Risk: some raster providers may not expose all resample filter APIs; code guards with `hasattr` and soft-fails to log.
- Rollback:
  - Revert added helper calls in `_on_download_selected_task_finished`.
  - Revert `Select All` button and `_select_all_search_results` method.
