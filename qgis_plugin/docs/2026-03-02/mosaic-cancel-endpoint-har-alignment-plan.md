# Mosaic Cancel Endpoint HAR Alignment

- Date: 2026-03-02
- Scope: `qgis_plugin/**`

## Problem
- Mosaic Tracking `Cancel` failed from plugin with:
  - `403 Client Error: Forbidden for url: https://api.satellogic.com/v2/orders/{order_id}/cancel`
- User-provided HAR (`aleph_cancel.har`) shows browser cancellation succeeds via:
  - `PATCH https://api.satellogic.com/tasking/tasks/{task_id}/cancel/?api_url=https:%2F%2Fapi.satellogic.com`
  - JSON body: `{}`
  - Contract + auth headers present.

## Root Cause
- Plugin used legacy order-cancel endpoint (`/v2/orders/{order_id}/cancel`) for Mosaic cancel.
- Aleph now cancels by task id through `/tasking/tasks/{task_id}/cancel/`.

## Implementation
- Added `SatellogicClient.cancel_task(task_id, contract_id)` using:
  - `PATCH /tasking/tasks/{task_id}/cancel/`
  - `api_url` query parameter
  - empty JSON body.
- Updated `SourceService.cancel_tasking_order(...)`:
  - fetch order details first
  - extract `task_id` from `properties.parameters.task_id`
  - call `cancel_task(...)` when available
  - keep legacy `cancel_order(...)` as fallback if task id is missing.

## Files Changed
- `qgis_plugin/image_mate_qgis_plugin/clients/satellogic_client.py`
- `qgis_plugin/image_mate_qgis_plugin/services/source_service.py`
- `qgis_plugin/test/mosaic_cancel_endpoint_smoke.py` (new)

## Terminal Verification
- `py -3 -m compileall qgis_plugin/image_mate_qgis_plugin/clients/satellogic_client.py qgis_plugin/image_mate_qgis_plugin/services/source_service.py qgis_plugin/test/mosaic_cancel_endpoint_smoke.py`
- `py -3 qgis_plugin/test/mosaic_cancel_endpoint_smoke.py`
- `py -3 qgis_plugin/test/tasking_order_status_resolution_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_preview_telluric_smoke.py`
- `py -3 qgis_plugin/test/mosaic_tracking_preview_multi_smoke.py`
