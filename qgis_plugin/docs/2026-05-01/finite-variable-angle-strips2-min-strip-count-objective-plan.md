# Finite Variable Angle Strips2 Min Strip Count Objective Design and Implementation Plan

- Date: 2026-05-01
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
`finite_variable_angle_strips2.py` was previously selecting strips by minimizing
unused strip area cost. The new requirement is to minimize the total number of
strips needed to cover the polygon.

For a fixed strip width and overlap policy, the greedy proxy for minimum strip
count is: at each iteration choose the candidate strip that covers the largest
remaining polygon area.

## Existing Reusable Components
- `find_best_strip_for_remaining(...)` already enumerates all candidate
  angle/offset combinations.
- `make_candidate_from_overlap(...)` already computes `base_area_m2` and
  `strip_area_m2` for each candidate.
- `candidate_is_better(...)` is the single decision point for candidate ranking.
- `greedy_finite_strip_cover(...)` already loops until remaining area reaches
  tolerance and records strip metadata.

## Proposed Backend Changes
- Update top-level algorithm docs to reflect max-overlap objective.
- Change `candidate_is_better(...)` ranking logic:
  1. Primary: maximize `base_area_m2` (newly covered remaining area).
  2. Tie-breaker: smaller `strip_area_m2` (lower waste when overlap is equal).
  3. Tie-breaker: shorter `finite_length_m`.
- Update search-progress log text and final summary text so operators can see
  the active objective unambiguously.
- Keep `unused_km2` output field and cost summary as diagnostics only.

## UI Wiring Changes (Minimal)
None. Script is terminal-driven and does not require QGIS UI changes.

## Implementation Steps
1. Edit objective statement in module docstring.
2. Edit `candidate_is_better(...)` comparator.
3. Update objective wording in logs and summary output.
4. Run `py_compile` and run a CLI smoke test on
   `qgis_plugin/scripts/utils/linear_polygon.geojson`.
5. Run scope and derived-test helper scripts from the skill.

## Terminal-Only Test Plan
- Compile check:
  - `python -m py_compile qgis_plugin/scripts/utils/finite_variable_angle_strips2.py`
- Functional smoke:
  - Run the script with `--clip-output` on `linear_polygon.geojson`.
  - Confirm complete coverage and verify strip count does not regress relative
    to previous max-overlap behavior on this fixture.
- Logging/summary checks:
  - Confirm objective text reports "maximize overlap each iteration".
  - Confirm output still contains strip diagnostics (`unused_km2`, totals).

## Risks and Rollback
- Greedy max-overlap is still a heuristic and does not guarantee global optimum
  strip count for all geometries.
- Coarse angle/offset sampling can miss a better orientation and increase strip
  count; operators can reduce `--angle-step` or `--offset-step-km`.
- Rollback: revert `candidate_is_better(...)` comparator and objective text in
  this file only.
