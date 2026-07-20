# Finite Variable Angle Strips2 Balanced Strip Count Waste Coverage Design and Implementation Plan

- Date: 2026-05-04
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
The strip cover utility must cover the full AOI while balancing two competing
goals:

- Use as few strips as practical.
- Avoid obviously wasteful strips when a near-best coverage alternative exists.

The previous pure max-coverage heuristic drove strip count down but could pick
very wasteful strips. The previous pure minimum-waste heuristic could fragment
coverage and fail the practical strip-count goal.

## Existing Reusable Components
- `find_best_strip_for_remaining(...)` already enumerates candidate angles and
  offsets for each greedy iteration.
- `BestCandidate` already carries overlap area, finite strip length, and strip
  area.
- `greedy_finite_strip_cover(...)` already tracks remaining geometry.
- `build_output_gdf(...)` already creates clipped or full strip outputs.

## Proposed Backend Changes
- Add `BestCandidate.unused_area_m2` and `BestCandidate.waste_ratio`.
- Keep the top 3 candidates by AOI overlap during each search.
- Candidate selection:
  - Review the top 3 candidates by AOI overlap.
  - Select the first candidate with `waste_ratio <= 50%`.
  - If all top 3 exceed 50% waste, select the lowest-waste candidate among
    those top 3.
- Add an output coverage validation step:
  - Compute `target_aoi - union(output_strips)` in the working CRS.
  - Exit non-zero if the output gap or remaining loop gap exceeds tolerance.
- Remove any stale output dataset before processing begins, so a failed run
  cannot leave an old partial output that looks like the latest result.
- Read the written dataset back from disk and repeat the AOI coverage check
  against the persisted output.
- Keep waste summary fields for diagnostics.

## UI Wiring Changes (Minimal)
None. This is a terminal utility change.

## Implementation Steps
1. Add candidate waste properties.
2. Replace single-candidate max-overlap comparator with a top-candidate pool.
3. Update vectorized and loop candidate evaluation paths to populate the pool.
4. Add output union coverage validation before writing the output.
5. Add written-output validation after writing the output.
6. Add a terminal smoke test that runs the script, reads the output, and
   independently verifies AOI coverage.

## Terminal-Only Test Plan
- `python -m py_compile qgis_plugin/scripts/utils/finite_variable_angle_strips2.py`
- `python qgis_plugin/test/finite_variable_angle_strips2_coverage_smoke.py`
- Manual fixture command:
  - `python qgis_plugin/scripts/utils/finite_variable_angle_strips2.py --clip-output qgis_plugin/scripts/utils/linear_polygon.geojson qgis_plugin/scripts/utils/tmp_balanced_strip_output.geojson`

## Risks and Rollback
- This remains a greedy heuristic; it balances strip count and waste locally,
  not with a global optimizer.
- A 50% waste threshold and 3-candidate review window are explicit policy
  choices. Different AOIs may need different policy constants.
- Rollback is limited to `finite_variable_angle_strips2.py` and the smoke test
  added for this behavior.
