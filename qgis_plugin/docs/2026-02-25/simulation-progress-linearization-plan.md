# Simulation Progress Linearization Design and Implementation Plan

- Date: 2026-02-25
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
Simulation progress can reach 100% before worker completion, then appear stuck for a long time (especially long-duration runs). This is misleading for operators and makes long jobs look hung.

## Existing Reusable Components
- Existing worker progress emission contracts:
  - `CoverageSimulationWorker.progress`
  - `PointRevisitSimulationWorker.progress`
- Existing UI renderer:
  - `ui/main_dock.py::set_simulation_progress(current, total, text)`
- Existing simulation orchestration:
  - `mixins/simulation_execution.py::_on_simulation_worker_progress(...)`

## Proposed Backend Changes
- Add pure progress-planning helper module:
  - `services/simulation_progress_planner.py`
  - deterministic per-satellite and finalization unit budgets for coverage/revisit scenarios.
- Refactor coverage worker progress behavior:
  - avoid consuming full per-satellite budget during sample loop
  - reserve satellite tail for pass-processing
  - reserve global finalization budget for day-union/geojson post-processing
  - reach 100% only at true completion.
- Refactor revisit worker progress behavior:
  - reserve global finalization budget for sort/metrics/day rollup work
  - emit incremental finalization progress during `_build_days(...)`.

## UI Wiring Changes (Minimal)
- No UI logic changes required; existing progress bar already supports arbitrary `current/total`.
- Progress text now reflects finalization stages instead of immediately saying completed.

## Implementation Steps
1. Add progress planner helper functions in `services/`.
2. Integrate planner budgets into `coverage_worker.py`.
3. Integrate planner budgets into `revisit_worker.py`.
4. Add day-rollup callback progress in revisit worker.
5. Add terminal smoke test for planner helper behavior.
6. Run compile/smoke/scope checks.

## Terminal-Only Test Plan
- Compile checks:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/simulation_progress_planner.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/simulation/coverage_worker.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/simulation/revisit_worker.py`
- Smoke checks:
  - `py -3 qgis_plugin/test/simulation_progress_planner_smoke.py`
- Scope checks:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- Derived CLI checklist:
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback
- Risk: overly conservative finalization budgets could make progress feel slower than work.
  - Mitigation: bounded budgets with deterministic caps and staged text.
- Risk: too many progress emissions could increase UI chatter.
  - Mitigation: stride-based updates in high-frequency loops.
- Rollback:
  - remove planner integration and restore old direct unit math in workers.
