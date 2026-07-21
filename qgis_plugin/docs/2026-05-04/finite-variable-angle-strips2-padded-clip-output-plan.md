# Finite Variable Angle Strips2 Padded Clip Output Design and Implementation Plan

- Date: 2026-05-04
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
`finite_variable_angle_strips2.py --clip-output` currently writes the geometric
intersection between each rectangular strip and the AOI. That produces
AOI-shaped polygons, but the intended output is still a strip rectangle: the
minimum along-strip length that preserves the same AOI intersection, padded at
both ends by a configurable distance.

## Existing Reusable Components
- Selected strips are already stored as full rectangular geometries in the
  projected working CRS.
- Each selected row stores `ang_deg` and `off_m`, which are enough to reconstruct
  a rectangle in the strip's rotated coordinate frame.
- Existing output coverage checks can verify that post-processed rectangles
  still cover the AOI before and after writing.

## Proposed Backend Changes
- Keep the existing `--clip-output` flag for compatibility, but change its
  behavior from AOI clipping to rectangular post-processing.
- For each selected strip, intersect the full strip with the AOI only to find
  the covered along-track bounds.
- Build a new rectangle using that minimum covered span plus end padding on both
  ends. Use `--overlap-km` as the padding value and add `--end-padding-km` as an
  alias for clarity.
- Recompute output `len_km`, `strip_km2`, and `unused_km2` from the
  post-processed rectangle.

## UI Wiring Changes (Minimal)
- None. This is a CLI utility behavior change only.

## Implementation Steps
- Add a helper that derives padded rectangular output geometry from each selected
  strip and its AOI intersection.
- Update `build_output_gdf` to call that helper when `--clip-output` is enabled.
- Update CLI help and terminal summary text to describe padded coverage-span
  rectangles instead of polygon clipping.
- Update the finite strip smoke test to assert coverage and rectangle-like
  output geometries.

## Terminal-Only Test Plan
- Compile the utility and smoke test with `.venv`.
- Run `qgis_plugin/test/finite_variable_angle_strips2_coverage_smoke.py`.
- Run a local CLI command against `linear_polygon.geojson` and verify zero output
  coverage gap plus non-50 km post-processed output lengths.
- Run the QGIS plugin scope checker and CLI test derivation helper.

## Risks and Rollback
- The `--clip-output` name is now compatibility terminology. The help text and
  summary describe the new behavior to avoid implying AOI-shaped clipping.
- Numerical rotation/projection precision could create tiny gaps. Existing
  in-memory and written-output coverage-gap validation remains the rollback
  guardrail.
