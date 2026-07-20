# Finite Variable Angle Strips Final Random Seed Grow Design and Implementation Plan

- Date: 2026-05-04
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
The current optimizer is angle/offset exhaustive and prioritizes immediate AOI
gain. The target objective is now minimum total linear strip length. A new
script is required, not a fallback mode inside the existing script.

## Existing Reusable Components
- Input/output vector handling and CRS normalization.
- Geometry cleanup and polygon dissolve helpers.
- Output post-processing (`--clip-output`) and effective-width coverage gap
  validation.
- Along-track gap clustering helper to prevent tele-connecting captured AOI.

## Proposed Backend Changes
- Create `finite_variable_angle_strips_final.py` as a standalone optimizer.
- Keep reusable geometry I/O and output validation helpers imported from
  `finite_variable_angle_strips2.py`.
- Implement randomized whole-plan trials with the user-defined loop:
  - initialize `bestTotalStripLength = 1e6`
  - dedensify once at startup and cache search polygon
  - for each trial, repeatedly:
    - sample random point in remaining AOI
    - find shortest chord through that point on cached dedensified AOI
    - use chord center and perpendicular direction for strip placement
    - choose the longest contiguous strip not exceeding AOI and max length
    - apply end padding for reported strip length
    - subtract covered AOI from exact remaining AOI and cached search AOI
  - when AOI is covered, compute cumulative strip length
  - update best configuration only when trial total length is <= current best.

## UI Wiring Changes (Minimal)
- None. This is a new CLI utility under `qgis_plugin/scripts/utils`.

## Implementation Steps
- Add new script and compatibility entrypoint file with requested naming.
- Add smoke test for AOI coverage and summary metrics in
  `qgis_plugin/test/finite_variable_angle_strips_final_smoke.py`.
- Keep script-specific CLI options for trials, seed, chord angle sampling, min
 /max strip length, along-track gap guard, search de-densify, and end padding.

## Terminal-Only Test Plan
- Compile new script and smoke test with repository `.venv`.
- Run new smoke test.
- Run scope checker and derived CLI test helper.
- Verify summary lines include total linear strip length and unique AOI captured.

## Risks and Rollback
- Stochastic trials can vary quality; determinism is controlled by `--random-seed`.
- Too few trials may miss good solutions; user can increase `--trials`.
- If a dataset is hard to cover under strict tolerance, increase trials or reduce
  chord-angle step to improve local orientation quality.
