# Simulation Results Day Navigation Controls Design and Implementation Plan

- Date: 2026-02-25
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
In Simulation results day navigation, add larger time-step controls and boundary jumps:
- back to beginning (`<<`)
- back 30 days (`30d<`)
- back 1 day (`1d<`)
- forward 1 day (`>1d`)
- forward 30 days (`>30d`)
- jump to end (`>>`)

Requested layout is a single button row in that order.

## Existing Reusable Components
- Existing day-navigation signals and handlers:
  - `simulation_prev_day_requested`
  - `simulation_next_day_requested`
  - `handle_simulation_prev_day_request`
  - `handle_simulation_next_day_request`
- Existing day rendering and clamped index application in:
  - `_simulation_apply_day(...)`
- Existing UI state binding in:
  - `set_simulation_day(...)`

## Proposed Backend Changes
- Add reusable day-index navigation helpers in a pure module:
  - `services/simulation_day_navigation.py`
  - functions for clamp/shift/start/end and button-state.
- Extend simulation execution mixin with handlers:
  - first day
  - previous 30 days
  - next 30 days
  - last day
- Reuse shared helper logic for all day movement to avoid scattered index math.

## UI Wiring Changes (Minimal)
- Add four new Simulation signals:
  - `simulation_first_day_requested`
  - `simulation_prev_30_days_requested`
  - `simulation_next_30_days_requested`
  - `simulation_last_day_requested`
- Update day navigation button row to exactly:
  - `<< | 30d< | 1d< | >1d | >30d | >>`
- Keep date/index label and day metrics under the row.
- Use shared helper-based state to enable/disable all six nav buttons.

## Implementation Steps
1. Add shared day-navigation helpers under `services/`.
2. Add a terminal smoke test for navigation helper behavior.
3. Update simulation mixin to expose and use new day-jump handlers.
4. Wire new signals in `plugin.py`.
5. Update Simulation tab UI button row and state handling in `main_dock.py`.
6. Run compile, smoke, and scope checks.

## Terminal-Only Test Plan
- Compile checks:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/simulation_day_navigation.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/mixins/simulation_execution.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/plugin.py`
- Smoke checks:
  - `py -3 qgis_plugin/test/simulation_day_navigation_smoke.py`
- Scope checks:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- Derived CLI checklist:
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback
- Risk: index navigation could move outside valid day range.
  - Mitigation: central clamp logic in `simulation_day_navigation.py`.
- Risk: UI/control mismatch when no result days are available.
  - Mitigation: helper-driven button state with `total_days=0` fallback.
- Rollback:
  - remove new signals/buttons and handler connections
  - keep existing `1d<`/`>1d` behavior only
