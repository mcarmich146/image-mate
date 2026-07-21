# Finite Variable Angle Strips2 Along Track Gap And Metrics Design and Implementation Plan

- Date: 2026-05-04
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
Some long strip candidates touch two separated AOI sections with a large empty
along-track gap between them. Total overlap can make these candidates look good,
but the resulting strip has poor operational value. The user also needs summary
metrics for total linear strip length and unique AOI area captured.

## Existing Reusable Components
- Candidate scoring already rotates each AOI/strip overlap into strip
  coordinates.
- The selected-row model now distinguishes physical strip output from effective
  coverage geometry.
- Existing output gap validation can provide the unique AOI-captured area.

## Proposed Backend Changes
- Add `--max-along-track-gap-km`, default `5`, with `0` disabling the guard.
- Split each strip/AOI overlap into along-track clusters by polygon component
  x-intervals. Components separated by more than the configured gap become
  separate candidate clusters.
- Score each cluster independently and preserve the selected cluster as the
  candidate's captured effective swath.
- Use the captured swath for iterative subtraction and `--clip-output`
  post-processing so distant AOI patches are covered by separate future strips.
- Add summary lines for total linear strip length, unique AOI captured by strips,
  and unique AOI captured ratio.

## UI Wiring Changes (Minimal)
- None. This is a CLI utility change.

## Implementation Steps
- Add helpers for polygon component interval clustering and preferred-cluster
  selection during exact rescoring.
- Thread the maximum along-track gap through loop and vectorized candidate
  scoring.
- Extend `BestCandidate` with a captured rotated strip used for subtraction.
- Update the smoke test to exercise the new CLI option and summary output.

## Terminal-Only Test Plan
- Compile `finite_variable_angle_strips2.py` and its smoke test using `.venv`.
- Run `qgis_plugin/test/finite_variable_angle_strips2_coverage_smoke.py`.
- Run a direct CLI probe with `--clip-output --strip-side-buffer-km 0.25
  --max-along-track-gap-km 5` and verify zero effective coverage gap plus
  reported total length and captured AOI metrics.
- Run the QGIS plugin scope checker and CLI test derivation helper.

## Risks and Rollback
- Splitting clusters can increase strip count when disconnected AOI pieces were
  previously captured by one long strip. That is intentional because the skipped
  gap was operationally undesirable.
- The interval-based split treats connected AOI inside the strip as continuous
  even if it is narrow. If stricter behavior is required later, the same
  parameter can be backed by a sampled occupancy profile.
- Set `--max-along-track-gap-km 0` to disable the guard and return to the
  previous candidate behavior.
