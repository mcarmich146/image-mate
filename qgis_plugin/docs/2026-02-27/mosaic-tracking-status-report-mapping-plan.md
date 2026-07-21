# Mosaic Tracking Status Report Mapping Design and Implementation Plan

- Date: 2026-02-27
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

In `Collection Requests -> Mosaic -> Tracking`, API status refresh stores lifecycle `closed` for finished orders.
For campaign `thai_caas`, project `vancouver_mosaic`, this makes all 6 tiles appear `closed`, while operator intent is:

- 3 tiles `Completed`
- 3 tiles `Failed`

Root cause: refresh currently reads `order.status` directly and does not resolve final operator outcome.

## Existing Reusable Components

- `SourceService.get_tasking_order(...)` already centralizes order fetch/normalization.
- `MosaicTaskingService.refresh_non_accepted_statuses(...)` already persists refreshed `api_status`.
- `SatellogicClient` already wraps v2 order endpoints and auth headers.
- `MosaicTrackingStore.update_tile_api_status(...)` already writes status transitions and history.

## Proposed Backend Changes

- Extend `SatellogicClient` with `list_order_deliverables(order_id, contract_id)` for v2 deliverable lookup.
- Extend `SourceService` with `resolve_tasking_order_status(...)` to map operator-visible status:
  - Use `status_report` first when present.
  - For lifecycle `closed`, inspect deliverables:
    - delivered/completed/success -> `Completed`
    - no deliverables or failed/rejected/expired/cancelled deliverables -> `Failed`
  - Non-closed lifecycle statuses pass through unchanged.
- Update `SourceService.get_tasking_order(...)` to return resolved status in `order.status`.

## UI Wiring Changes (Minimal)

None. Existing Mosaic tracking refresh path already consumes `get_tasking_order(...).order.status`.

## Implementation Steps

1. Add deliverables client endpoint wrapper in `clients/satellogic_client.py`.
2. Add status resolution helpers and resolver in `services/source_service.py`.
3. Apply resolver in `get_tasking_order(...)` before returning normalized order.
4. Add a deterministic smoke test for resolver rules under `qgis_plugin/test/`.
5. Verify with live `thai_caas -> vancouver_mosaic` order IDs for expected 3/3 split.

## Terminal-Only Test Plan

- Run `qgis_plugin/test/tasking_order_status_resolution_smoke.py` (no GUI, no network).
- Live probe (manual verification) with `SourceService.get_tasking_order` on:
  - `012712`, `012713`, `012714`, `012715`, `012716`, `012717`
- Assert counts from resolved statuses:
  - `Completed`: 3
  - `Failed`: 3

## Risks and Rollback

- Risk: Some closed orders in other campaigns may prefer `Cancelled` labeling.
  - Mitigation: current mapping keeps non-closed states unchanged and only specializes closed finalization.
- Rollback: revert `SourceService` resolver + `SatellogicClient.list_order_deliverables` and statuses return to lifecycle values.
