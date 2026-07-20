# Download Selected Progress Monitoring Table Design and Implementation Plan

- Date: 2026-02-23
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
`Download Selected` runs in background, but operators currently have no live visibility during large GeoTIFF downloads. The Activity Log tab should provide:
- A live progress bar for current background download task.
- A tracking table with task-level status and counters.
- Final status persistence after task completion/failure.

## Existing Reusable Components
- Existing background execution with `QgsTask.fromFunction` in `plugin.py`.
- Existing download business logic:
  - `_resolve_download_selected_groups`
  - `_download_geotiff_asset_for_item`
  - `_run_download_selected_task`
  - `_on_download_selected_task_finished`
- Existing Activity Log text area in `ui/main_dock.py` and existing search log append methods.

## Proposed Backend Changes
- Add plugin-side task monitor state:
  - `_download_selected_tasks` registry keyed by `task_id`.
  - `_download_selected_monitor_timer` polling active tasks every 500 ms.
- Generate deterministic `task_id` and metadata on task creation (`started_utc`, totals, status).
- Keep heavy monitoring logic in plugin backend:
  - `_download_task_status_text`
  - `_poll_download_selected_tasks`
  - `_sync_download_monitor_to_dock`
- Update completion callback signature to include `task_id`:
  - `_on_download_selected_task_finished(task_id, exception, result)`
- Enable true parallel execution by removing single-active download gating and submitting one `QgsTask` per selected capture group.
- Monitor header progress reflects aggregate active tasks (average progress), not only latest task.
- Push thin UI payload updates only (no business logic in dock):
  - status
  - progress
  - group/item totals
  - downloaded file count
  - timestamps
  - note

## UI Wiring Changes (Minimal)
- Activity Log tab additions:
  - `QLabel` for monitor status text.
  - `QProgressBar` for live percent.
  - `QTableWidget` for task tracking rows.
- Add thin dock update methods:
  - `set_download_monitor_progress(progress_pct, status_text)`
  - `upsert_download_task_status(task_id, payload)`
- Keep existing `search_log` area intact under monitoring widgets.

## Implementation Steps
1. Extend Activity Log UI with progress bar + task table.
2. Add thin dock API methods for monitor row upsert and progress updates.
3. Extend plugin task lifecycle:
   - register task metadata on submit
   - start monitor timer
   - poll and update UI until completion
   - finalize task row with terminal state
4. Ensure unload cleanup:
   - stop monitor timer
   - clear in-memory task registry
5. Resync monitor UI on dock recreation if tasks are active.

## Terminal-Only Test Plan
- Static checks:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/plugin.py`
- Diff-derived checks:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`
- Behavioral CLI probes (log-based):
  - Verify task registry creation on `handle_download_selected_request`.
  - Verify polling updates status/progress payload shape for dock methods.
  - Verify completion updates terminal row states (`complete`, `failed`, `canceled`).

## Risks and Rollback
- Risk: QGIS task status enum drift across versions.
  - Mitigation: map unknown status to `unknown` and keep polling resilient.
- Risk: frequent UI updates spam table rendering.
  - Mitigation: 500 ms polling cadence and lightweight row updates.
- Rollback:
  - Remove monitor timer and row upsert calls while preserving core download execution path.
