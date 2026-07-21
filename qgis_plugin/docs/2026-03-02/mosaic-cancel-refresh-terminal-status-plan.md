# Mosaic Cancel Refresh Terminal Status Design and Implementation Plan

- Date: 2026-03-02
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

- In campaign `azerbaijan_mosaic` (project `Baku_Mosaic`), canceled rows were being overwritten to `in_progress` during status refresh.
- Evidence from log/DB:
  - Log file `image_mate_qgis_20260302T162535Z.log` shows `cancel_tasking ... api_status=canceled` followed by `refresh_status_complete ... changed=1` for the same tile.
  - Tracking DB history contains transitions such as `from_api_status='canceled' -> to_api_status='in_progress'` with `mutation_source='refresh_status'` (for example around `2026-03-02T16:27:03+00:00` and `2026-03-02T16:29:05+00:00`).
- Root cause: refresh path did not treat canceled statuses as terminal, so transient upstream `in_progress` responses could regress local canceled state.

## Existing Reusable Components

- `MosaicTaskingService.refresh_non_accepted_statuses(...)` already contains terminal-skip behavior for `Failed`.
- `ImageMatePlugin.handle_mosaic_refresh_status_request(...)` already computes refresh summary/skipped counters.
- `ImageMateMainDock.set_mosaic_tracking_rows(...)` already supports per-row refresh button enable/disable rules.

## Proposed Backend Changes

- Extend terminal-skip behavior in `refresh_non_accepted_statuses(...)` to include canceled statuses (`canceled`, `cancelled`) with reason `terminal_canceled`.
- Keep existing `skip_failed` flag for compatibility; use it as a terminal-skip gate for both failed and canceled.
- Add helper `MosaicTaskingService._is_terminal_canceled_status(...)`.
- Update plugin refresh summary/log counters to report skipped canceled rows (`skipped_canceled`) for faster log diagnosis.

## UI Wiring Changes (Minimal)

- Update per-row `Refresh` button disable condition to treat canceled statuses as terminal (`failed`, `canceled`, `cancelled`).
- Keep business decisions in backend service; UI only avoids unnecessary manual refresh attempts.

## Implementation Steps

1. Add terminal canceled detection/helper in `mosaic_tasking_service.py`.
2. Add skip branch with `reason=terminal_canceled` in refresh loop.
3. Update plugin status/log summary counters (`skipped_canceled`).
4. Update row refresh button disable condition in `main_dock.py`.
5. Update smoke tests for terminal canceled behavior and static wiring snippets.

## Terminal-Only Test Plan

- `py -3 qgis_plugin/test/mosaic_tracking_refresh_wiring_smoke.py`
- `py -3 qgis_plugin/test/mosaic_refresh_skip_failed_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_more_wiring_smoke.py`
- `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/mosaic_tasking_service.py qgis_plugin/image_mate_qgis_plugin/plugin.py qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
- `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`

## Risks and Rollback

- Risk: if backend eventually transitions canceled rows into another terminal code, skipping refresh may hide that transition.
  - Mitigation: terminal skip logic is isolated and can be adjusted quickly.
- Rollback: revert service/plugin/UI changes from this patch to restore prior refresh behavior.
