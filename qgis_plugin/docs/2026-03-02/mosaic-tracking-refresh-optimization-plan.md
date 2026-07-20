# Mosaic Tracking Refresh Optimization Design and Implementation Plan

- Date: 2026-03-02
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

- Bulk `Refresh Status` currently processes all non-accepted rows, including terminal `Failed` collections that will not change.
- Mosaic Tracking rows do not provide a per-row status refresh action, forcing whole-project refresh even when only one row needs update.
- The result is slower refresh cycles and unnecessary API calls.

## Existing Reusable Components

- `plugin.py::handle_mosaic_refresh_status_request` already routes tracking refresh from UI to service.
- `services/mosaic_tasking_service.py::refresh_non_accepted_statuses` already centralizes status fetch/update logic for non-accepted tiles.
- `ui/main_dock.py::set_mosaic_tracking_rows` already renders per-row action buttons (`Accept`, `Re-Task`, `Cancel`, `More`) and can be extended with one more thin UI action.

## Proposed Backend Changes

- Extend `MosaicTaskingService.refresh_non_accepted_statuses(...)` with:
  - `tile_ids: list[str] | None` to support single-tile refresh.
  - `skip_failed: bool` to skip terminal failed rows before API calls.
- Add terminal-failed detection helper in service (`_is_terminal_failed_status`) to keep status filtering in backend logic.
- Update plugin refresh handler to pass optional `tile_id` from payload into service as `tile_ids=[tile_id]`.
- Keep status/telemetry reporting in plugin while preserving existing refresh entry-point.

## UI Wiring Changes (Minimal)

- Add `Refresh` button per row in Mosaic Tracking table.
- Wire row button to emit existing `mosaic_refresh_status_requested` signal with both `project_id` and `tile_id`.
- Keep UI thin by avoiding status decision logic in UI; only disable row refresh button for obvious terminal rows (`Accepted` or `Failed`).

## Implementation Steps

1. Update service refresh method signature and filtering logic.
2. Update plugin refresh handler to consume `tile_id` payload and forward tile filter to service.
3. Add row-level `Refresh` button and payload emitter in `main_dock.py`.
4. Update existing static wiring smoke test for new tracking column layout.
5. Add dedicated smoke tests:
   - static wiring (`mosaic_tracking_refresh_wiring_smoke.py`)
   - runtime refresh behavior (`mosaic_refresh_skip_failed_smoke.py`)

## Terminal-Only Test Plan

- `py -3 qgis_plugin/test/mosaic_tracking_more_wiring_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_refresh_wiring_smoke.py`
- `py -3 qgis_plugin/test/mosaic_refresh_skip_failed_smoke.py`
- `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback

- Risk: treating `Failed` as terminal may skip rare vendor-side recoveries.
  - Mitigation: single-tile refresh still exists; terminal-skip behavior is isolated in one helper and can be relaxed quickly.
- Risk: table column index changes can break existing action wiring.
  - Mitigation: static wiring smoke checks updated to assert exact indices and signal snippets.
- Rollback: revert changes in `main_dock.py`, `plugin.py`, and `mosaic_tasking_service.py` to restore prior full-refresh-only behavior.
