# Asset Intel Manual Unit Persistence Design and Implementation Plan

- Date: 2026-02-26
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- User-created fielded units in Asset Intel were not visible after creation/reload.
- Reproduction showed `create_unit(...)` inserts successfully, but a subsequent `validate()` removed the row.
- Root cause: `_sync_fleet_units()` pruned **all** units without identifiers, including `source='manual'` rows created from the UI.

## Existing Reusable Components
- `AssetIntelService.create_unit(...)` already persists manual units correctly.
- `AssetIntelService.validate()` is the canonical refresh path and already routes through `_sync_fleet_units()`.
- Existing smoke test pattern under `qgis_plugin/test/*_smoke.py` fits this regression scenario.

## Proposed Backend Changes
- Update `_sync_fleet_units()` prune query to delete only parser-generated orphan rows:
  - keep manual rows with no identifiers
  - continue pruning parser rows that have no linked identifier
- Keep change isolated to service layer; no UI logic required.

## UI Wiring Changes (Minimal)
- None required.
- Existing UI mutation flow remains unchanged; persistence issue is fixed at backend sync stage.

## Implementation Steps
- Reproduce with temporary DB copy:
  - create asset
  - create manual unit
  - run `validate()`
  - confirm row deletion before fix
- Patch prune SQL in `asset_intel_service.py`.
- Add regression smoke test:
  - `qgis_plugin/test/asset_intel_manual_unit_persistence_smoke.py`
  - asserts manual unit survives follow-up `validate()`.

## Terminal-Only Test Plan
- `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/asset_intel_service.py`
- `py -3 qgis_plugin/test/asset_intel_manual_unit_persistence_smoke.py`
- `py -3 qgis_plugin/test/asset_intel_domain_hierarchy_smoke.py`
- `py -3 qgis_plugin/test/mosaic_preview_resolution_smoke.py`
- `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`

## Risks and Rollback
- Risk: parser orphan cleanup now excludes non-parser sources by design; parser cleanup behavior is preserved.
- Rollback: restore previous DELETE predicate in `_sync_fleet_units()` if downstream workflows require aggressive prune.
