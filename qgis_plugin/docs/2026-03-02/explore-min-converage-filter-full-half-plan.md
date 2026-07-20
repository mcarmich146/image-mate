# Explore Min Converage Filter Full Half Design and Implementation Plan

- Date: 2026-03-02
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- Explore search currently exposes a binary checkbox for coverage filtering and labels it as `Coverage Filter`.
- Request is to expose explicit operator choices: `Full Coverage` and `Half Coverage`.
- Form label must be updated to `Min. Converage Filter`.

## Existing Reusable Components
- `ImageMateMainDock.current_search_payload()` already emits coverage semantics via `require_full_aoi_overlap`.
- `SearchController.build_search_request()` normalizes payload into backend request shape.
- `ImageMatePlugin.handle_search_request()` already applies geometry filtering through `_filter_items_full_aoi_overlap`.
- Source-specific UX guard exists in `SearchStreamingMixin._on_source_changed()` for Sentinel-2 behavior.

## Proposed Backend Changes
- Add `min_coverage_filter` mode propagation (`full` / `half`) through UI payload and search controller.
- Keep backwards compatibility by still emitting `require_full_aoi_overlap`, derived from mode.
- Add `_filter_items_min_aoi_overlap(..., min_overlap_ratio)` to support thresholded AOI coverage.
  - `full` => threshold `1.0` (full AOI containment semantics).
  - `half` => threshold `0.5` (at least 50% AOI covered by candidate geometry).
- Keep existing Sentinel-2 full-coverage fallback behavior (if full mode returns zero results, fallback to overlap results).

## UI Wiring Changes (Minimal)
- Replace checkbox control with a combo:
  - `Half Coverage` (`half`) default.
  - `Full Coverage` (`full`).
- Rename row label from `Coverage Filter` to `Min. Converage Filter`.
- Maintain legacy fallback branch in payload assembly for any stale UI state.

## Implementation Steps
- Updated `ui/main_dock.py`:
  - New combo widget and label.
  - Payload now emits both `min_coverage_filter` and legacy bool mapping.
- Updated `controllers/search_controller.py`:
  - Normalizes `min_coverage_filter`.
  - Derives legacy `require_full_aoi_overlap` from normalized mode.
- Updated `mixins/search_streaming.py`:
  - Source-change guard now handles combo mode and auto-adjusts Sentinel-2 `full` to `half`.
- Updated `plugin.py`:
  - Search flow now resolves coverage mode and threshold.
  - Added threshold-based filter helper; full filter now delegates to this helper.
- Added smoke test:
  - `qgis_plugin/test/explore_min_converage_filter_smoke.py`

## Terminal-Only Test Plan
- Scope check:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- Test checklist derivation:
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`
- Static smoke checks:
  - `py -3 qgis_plugin/test/explore_download_selected_enhancements_smoke.py`
  - `py -3 qgis_plugin/test/explore_min_converage_filter_smoke.py`
- Syntax validation:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py qgis_plugin/image_mate_qgis_plugin/controllers/search_controller.py qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py qgis_plugin/image_mate_qgis_plugin/plugin.py`

## Risks and Rollback
- Risk: half-coverage threshold may exclude low-overlap results previously included.
- Risk: geometry intersection failures can reduce retained items; handled by defensive exceptions and deterministic fallback.
- Rollback:
  - Revert combo control to legacy checkbox.
  - Revert threshold helper and mode-based filtering path to legacy full/overlap toggle.
