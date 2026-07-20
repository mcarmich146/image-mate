# Collection Search Min Coverage Touching Option Design and Implementation Plan

- Date: 2026-03-12
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- Collection Search currently exposes only `Half Coverage` and `Full Coverage` minimum AOI-overlap modes.
- Operators need a `Touching` mode that behaves like no overlap threshold filter (keep all geometric overlaps returned by API search).
- The mode must flow end-to-end:
  - UI selection (`touching`)
  - request assembly
  - result filtering decision in plugin runtime
  - source-change tooltip guidance

## Existing Reusable Components
- `ui/main_dock.py` already owns the Explore filter combo and payload serialization (`min_coverage_filter`).
- `controllers/search_controller.py` normalizes search request payloads and keeps legacy `require_full_aoi_overlap`.
- `plugin.py` already computes `min_overlap_ratio` from `min_coverage_filter`; `None` means filter off.
- `mixins/search_streaming.py` updates coverage filter tooltip and Sentinel-2-specific guidance on source change.
- `qgis_plugin/test/explore_min_converage_filter_smoke.py` provides static wiring checks for this filter path.

## Proposed Backend Changes
- Extend coverage mode normalization to include `touching` in:
  - `controllers/search_controller.py`
  - `plugin.py`
- Preserve backward compatibility:
  - keep `require_full_aoi_overlap=True` equivalent to `full`
  - fallback remains `full`/`half` when payload has invalid mode
- Keep runtime behavior:
  - `touching` resolves to `min_overlap_ratio=None`, which skips post-search overlap threshold filtering.

## UI Wiring Changes (Minimal)
- Add `Touching (No Filter)` option to `min_coverage_filter_combo`.
- Keep default selection as `Half Coverage` (existing behavior) by explicitly setting combo index to `half`.
- Update coverage tooltip text to describe `Touching` semantics.
- Keep payload key unchanged: `min_coverage_filter`.

## Implementation Steps
- Update Explore tab combo options/tooltips and payload mode guard in `ui/main_dock.py`.
- Update request normalization guard in `controllers/search_controller.py`.
- Update runtime filtering mode guard in `plugin.py`.
- Update source-change tooltip text in `mixins/search_streaming.py`.
- Extend `qgis_plugin/test/explore_min_converage_filter_smoke.py` assertions for new `touching` mode.

## Terminal-Only Test Plan
- Syntax checks:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py qgis_plugin/image_mate_qgis_plugin/controllers/search_controller.py qgis_plugin/image_mate_qgis_plugin/plugin.py qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py qgis_plugin/test/explore_min_converage_filter_smoke.py`
- Static smoke:
  - `py -3 qgis_plugin/test/explore_min_converage_filter_smoke.py`
- Scope enforcement:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- Derived checklist:
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback
- Risk: Changing default mode unintentionally could alter result volume.
  - Mitigation: explicitly keep default combo selection on `half`.
- Risk: Sentinel-2 guidance could conflict with no-filter semantics.
  - Mitigation: keep Sentinel-2 auto-adjust only for `full`; `touching` remains untouched.
- Rollback:
  - Remove `touching` combo option.
  - Revert normalization guards to `{full, half}`.
  - Revert smoke assertions and tooltip text.
