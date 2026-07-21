# Finite Variable Angle Strips2 Side Buffer Effective Width Design and Implementation Plan

- Date: 2026-05-04
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
`finite_variable_angle_strips2.py` currently treats the full strip width as
available AOI coverage. The user needs a protective side margin so AOI coverage
is planned only inside the center swath. Example: a 5 km physical strip with a
0.25 km side buffer has a 4.5 km effective coverage width.

## Existing Reusable Components
- Candidate search already accepts a strip width and produces rectangular strip
  candidates in rotated coordinates.
- Selected strip rows already preserve `ang_deg`, `off_m`, and output geometry,
  which can be used to reconstruct effective coverage footprints.
- Existing in-memory and written-output coverage checks can be reused if they
  validate the effective footprint instead of the full physical output polygon.

## Proposed Backend Changes
- Add `--strip-side-buffer-km`, default `0`.
- Validate that `2 * strip_side_buffer_km < width_km`.
- Use `width_km - 2 * strip_side_buffer_km` as the effective width for search,
  scoring overlap, iterative subtraction, and coverage validation.
- Keep output geometry at the full physical width by expanding the effective
  swath by the side buffer on both sides.
- Store `eff_w_km` and `sidebuf_km` in output attributes.
- Reconstruct the effective footprint for both in-memory and written-output gap
  validation so buffer-only coverage cannot hide an AOI gap.

## UI Wiring Changes (Minimal)
- None. This is a CLI utility change.

## Implementation Steps
- Thread physical width, effective width, and side buffer through the greedy
  cover loop.
- Keep selected-row `geometry` as the physical strip and add internal
  `coverage_geometry` for the effective swath.
- Update padded `--clip-output` post-processing to trim/pad length while keeping
  full physical width and effective center coverage metadata.
- Update CLI help and terminal summary.
- Update the smoke test to run with a 0.25 km side buffer and validate coverage
  using reconstructed effective swaths.

## Terminal-Only Test Plan
- Compile `finite_variable_angle_strips2.py` and its smoke test with `.venv`.
- Run `qgis_plugin/test/finite_variable_angle_strips2_coverage_smoke.py`.
- Run a direct CLI command with `--clip-output --strip-side-buffer-km 0.25` and
  verify zero effective coverage gap.
- Run scope and derived CLI-test helpers.

## Risks and Rollback
- A positive side buffer reduces effective width, so some AOIs may require more
  strips. This is expected and safer than counting buffer-only coverage.
- Written-output validation depends on output metadata (`ang_deg`, `off_m`,
  `eff_w_km`) to reconstruct effective coverage. If external tools remove those
  fields, validation falls back to full geometry and logs a warning.
