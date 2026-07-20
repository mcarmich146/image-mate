# Finite Variable Angle Strips2 Search Dedensify Design and Implementation Plan

- Date: 2026-05-04
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
Dense AOI boundaries make `finite_variable_angle_strips2.py` expensive because
each iteration rotates and scores the remaining polygon many times. The user
wants an internal search version of the AOI with less-dense vertices, nominally
50 m spacing/tolerance, while preserving exact coverage behavior.

## Existing Reusable Components
- `finite_variable_angle_strips2.py` already has a candidate-search stage that
  can score against a search geometry before recomputing the selected strip on
  the exact remaining AOI.
- Existing `fix_geometry`, projected working CRS selection, and final output
  gap validation can be reused without UI changes.

## Proposed Backend Changes
- Add a first-class `--search-dedensify-m` CLI option, defaulting to `50`, with
  `--search-simplify-m` retained as a compatibility alias.
- Build a topology-preserving simplified internal geometry for candidate
  scoring only.
- Log vertex count before and after de-densification so terminal runs can
  confirm the search geometry is smaller.
- Keep exact AOI geometry authoritative for selected-strip rescoring,
  subtraction, output writing, and final coverage-gap validation.

## UI Wiring Changes (Minimal)
- None. This is a CLI utility change under `qgis_plugin/scripts/utils`.

## Implementation Steps
- Add a small helper to prepare the internal search geometry.
- Rename internal search terminology from simplify to de-densify where the
  public behavior is exposed.
- Update the smoke test to pass the new configurable option explicitly.

## Terminal-Only Test Plan
- Compile the script and smoke test with the repository `.venv` Python.
- Run `qgis_plugin/test/finite_variable_angle_strips2_coverage_smoke.py`.
- Run the QGIS plugin scope checker and CLI-test derivation helper.

## Risks and Rollback
- Topology-preserving simplification can change candidate ranking. The selected
  strip is still recomputed against exact AOI geometry, so coverage remains
  protected by the existing final gap validation.
- If a dense AOI requires exact candidate ranking, set `--search-dedensify-m 0`
  to disable this search optimization.
