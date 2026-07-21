# Mosaic Delete Dbf Lock Layer Sweep Design and Implementation Plan

- Date: 2026-03-02
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- Runtime delete fails on Windows with:
  - `[WinError 32] ... tiles.dbf`
- Verified in log:
  - `%USERPROFILE%\ImageMateCampaigns\campaigns\azerbaijan_mosaic\logs\image_mate_qgis_20260302T155614Z.log`
  - `delete_failed project=vancouver_mosaic ... \thai_caas\collections\mosaic\vancouver_mosaic\tiles.dbf`
- Existing fix already covered sqlite handles (`mosaic_tracking.sqlite3`) but not shapefile sidecar locks (`tiles.dbf`).
- Runtime lock probe identified lock owner process as `qgis-bin.exe` (same app process), indicating delayed in-process handle release.

## Existing Reusable Components
- `ImageMatePlugin._clear_mosaic_tiling_layer()` removes the currently tracked tiling layer id.
- `CampaignStorageService.delete_mosaic_project()` already has WinError 32 retries and GC backoff.
- `handle_mosaic_delete_request()` is the central delete orchestration point.

## Proposed Backend Changes
- Add plugin helper to release all loaded map layers tied to the target mosaic project, not only the tracked tiling id:
  - Match by `image_mate/mosaic_project_id` custom property.
  - Match by layer source path under target `collections/mosaic/<project_id>/`.
  - Match direct `tiles.shp` source.
- Run this sweep before `delete_mosaic_project`.
- Flush Qt events + Python GC before delete to shorten lock lifetime.
- Extend delete retries in storage service and add retry callback hook so plugin can pump events/release layers between lock retries.

## UI Wiring Changes (Minimal)
- No UI widget changes.
- Reuse existing `Delete Mosaic` action and status/log outputs.

## Implementation Steps
- Update `qgis_plugin/image_mate_qgis_plugin/plugin.py`:
  - Add layer-source/path helpers.
  - Add `_release_mosaic_project_layers(...)`.
  - Invoke sweep + event/GC flush in `handle_mosaic_delete_request` before filesystem deletion.
  - Pass `on_lock_retry` callback to re-run layer sweep and event pumping on each lock retry.
- Update `qgis_plugin/image_mate_qgis_plugin/services/campaign_storage_service.py`:
  - Add configurable `max_attempts`.
  - Add `on_lock_retry` callback hook for WinError32 retries.
- Update `qgis_plugin/test/mosaic_delete_lock_release_smoke.py` to assert new sweep invocation/order.

## Terminal-Only Test Plan
- `py -3 -m compileall qgis_plugin/image_mate_qgis_plugin/plugin.py qgis_plugin/image_mate_qgis_plugin/services/campaign_storage_service.py qgis_plugin/test/mosaic_delete_lock_release_smoke.py`
- `py -3 qgis_plugin/test/mosaic_delete_lock_release_smoke.py`

## Risks and Rollback
- Risk: sweep removes layers that point into the target mosaic project directory (intended during delete).
- Rollback: revert plugin sweep helper + delete hook changes if unintended layer removals are observed.
