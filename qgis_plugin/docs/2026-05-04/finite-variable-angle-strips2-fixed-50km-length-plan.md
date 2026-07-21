# Finite Variable Angle Strips2 Fixed 50km Length Design and Implementation Plan

- Date: 2026-05-04
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
`finite_variable_angle_strips2.py` previously trimmed each selected strip to the
along-track extent of the polygon overlap. The new requirement is fixed-size
strips: default length 50 km and default width 5 km. Candidate search must
therefore choose an along-track placement in addition to angle and cross-track
offset.

## Existing Reusable Components
- Existing rotated-coordinate search over angle and cross-track offsets.
- `BestCandidate` metadata, strip output rows, and AOI coverage validation.
- Existing terminal fixture `qgis_plugin/scripts/utils/linear_polygon.geojson`.

## Proposed Backend Changes
- Add fixed `--length-km` CLI option with default `50.0`.
- Extend `BestCandidate` with fixed strip `x0_m` and `x1_m`.
- Replace variable-length candidate construction with fixed-length windows.
- For each band overlap, evaluate candidate along-track starts using:
  - centered placement when the overlap span is <= fixed length;
  - grid starts using `--offset-step-km`;
  - optional vertex-aligned starts when vertex offsets are available.
- Keep the top-coverage candidate pool and 50% waste gate.
- Keep in-memory and written-output AOI coverage verification.

## UI Wiring Changes (Minimal)
None. This is a CLI utility change.

## Implementation Steps
1. Add fixed-length candidate placement helpers.
2. Thread `strip_length_m` through search and greedy cover functions.
3. Update output metadata so `len_km` is fixed at `50.0` by default.
4. Update smoke test to assert full AOI coverage and fixed `len_km`.
5. Validate with the exact `.venv` command and independent read-back.

## Terminal-Only Test Plan
- `.\.venv\Scripts\python.exe -m py_compile .\qgis_plugin\scripts\utils\finite_variable_angle_strips2.py .\qgis_plugin\test\finite_variable_angle_strips2_coverage_smoke.py`
- `.\.venv\Scripts\python.exe .\qgis_plugin\test\finite_variable_angle_strips2_coverage_smoke.py`
- Exact shared-drive command supplied by the user.
- Independent read-back check:
  - all output `len_km` values equal `50.0`;
  - `target_aoi - union(output_strips)` has zero area within tolerance.

## Risks and Rollback
- Fixed-length strips can require more strips and more waste than variable
  length strips, especially near AOI slivers.
- Along-track grid spacing uses `--offset-step-km`; finer spacing improves
  placement quality at higher runtime cost.
- Rollback is limited to the candidate construction and `--length-km` threading
  in `finite_variable_angle_strips2.py`.
