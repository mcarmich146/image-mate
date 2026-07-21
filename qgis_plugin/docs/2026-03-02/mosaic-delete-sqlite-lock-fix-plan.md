# Mosaic Delete SQLite Lock Fix Plan

- Date: 2026-03-02
- Scope: `qgis_plugin/**`

## Problem
- Deleting a Mosaic project failed with:
  - `[WinError 32] The process cannot access the file because it is being used by another process`
  - Path: `...\\mosaic_tracking.sqlite3`
- Observed in log:
  - `%USERPROFILE%\ImageMateCampaigns\campaigns\thai_caas\logs\image_mate_qgis_20260302T152108Z.log`
  - `delete_failed project=vancouver_mosaic ... mosaic_tracking.sqlite3`

## Root Cause
- `MosaicTrackingStore` used `with self._connect() as conn` with `_connect()` returning raw sqlite connection.
- SQLite connection context manager commits/rolls back but does not explicitly close the connection in that context path.
- On Windows, even short-lived handles can block `shutil.rmtree` and produce WinError 32.

## Implementation
- Updated `MosaicTrackingStore._connect` to a real context manager that always closes connection in `finally`.
- Hardened project deletion in `CampaignStorageService.delete_mosaic_project`:
  - Retry loop for transient lock errors (including `winerror=32`).
  - `gc.collect()` + short backoff between retries.
- Updated plugin delete flow to release map layers before filesystem delete:
  - Clear Mosaic tiling layer and Mosaic preview layers first.

## Files Changed
- `qgis_plugin/image_mate_qgis_plugin/services/mosaic_tracking_store.py`
- `qgis_plugin/image_mate_qgis_plugin/services/campaign_storage_service.py`
- `qgis_plugin/image_mate_qgis_plugin/plugin.py`
- `qgis_plugin/test/mosaic_delete_lock_release_smoke.py` (new)

## Terminal Verification
- `py -3 -m compileall qgis_plugin/image_mate_qgis_plugin/services/mosaic_tracking_store.py qgis_plugin/image_mate_qgis_plugin/services/campaign_storage_service.py qgis_plugin/image_mate_qgis_plugin/plugin.py qgis_plugin/test/mosaic_delete_lock_release_smoke.py`
- `py -3 qgis_plugin/test/mosaic_delete_lock_release_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_preview_telluric_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_preview_multi_smoke.py`

## Expected Runtime Outcome
- Mosaic delete should no longer fail on transient sqlite lock handles.
- If lock remains external/persistent, retries provide resilience and final error remains visible in log/UI.
