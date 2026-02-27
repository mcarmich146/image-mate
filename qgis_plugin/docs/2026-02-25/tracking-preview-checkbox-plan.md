# Tracking Preview Checkbox Design and Implementation Plan

- Date: 2026-02-25
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

Tracking currently exposes `Last Sync (UTC)` but does not provide an operator-controlled preview action in-row for acceptance workflow. Operators need a clear preview toggle per tile that is only actionable when the tasking collection/order reached `Completed`.

## Existing Reusable Components

- `ui/main_dock.py` already owns Mosaic Tracking table rendering and row-level actions (`Accept`, `Re-Task`, `Cancel`).
- `plugin.py` already handles Mosaic Tracking events and can load tile/order state from `MosaicTrackingStore` + `SourceService`.
- `mixins/search_streaming.py` already provides reusable image rendering methods:
  - `_build_stream_layer_for_item`
  - `_load_item_imagery_layer`
  - `_add_layer_to_image_mate_group`
- `SourceService.get_tasking_order(...)` already fetches live order detail by `latest_collection_id`.

## Proposed Backend Changes

- Add `services/mosaic_preview_resolution.py` with pure helper functions:
  - completed-status gating
  - preview enablement rule
  - candidate item-id extraction from tasking payloads
  - collection fallback candidates
  - preview search time window
  - order geometry extraction
- Add `SourceService.item_by_id(...)` public wrapper for source-manager item lookup.
- Add plugin handlers in `plugin.py`:
  - `handle_mosaic_tracking_preview_toggled`
  - preview item resolution from order detail + STAC fallback search
  - dedicated layer lifecycle for mosaic tracking preview.

## UI Wiring Changes (Minimal)

- Replace `Last Sync (UTC)` column with `Preview`.
- Render a `QCheckBox` per row in the `Preview` column.
- Enable checkbox only when:
  - `API Status == Completed`
  - `latest_collection_id` is present.
- Emit new signal payload:
  - `mosaic_tracking_preview_toggled({project_id, tile_id, enabled})`
- Keep UI logic limited to state binding + signal emission; no source/order lookup in UI.

## Implementation Steps

1. Add preview-resolution helper module under `services/`.
2. Add `item_by_id` in `SourceService`.
3. Update `main_dock.py` table schema and checkbox wiring.
4. Add plugin preview toggle handler and preview layer lifecycle management.
5. Add terminal smoke test covering preview-resolution helper behavior.
6. Run scope guard + derived CLI tests + targeted smoke scripts.

## Terminal-Only Test Plan

- New deterministic smoke:
  - `qgis_plugin/test/mosaic_preview_resolution_smoke.py`
  - Validates status gating, ID extraction, collection candidates, search window, geometry extraction.
- Existing regression smoke:
  - `qgis_plugin/test/mosaic_status_rules_smoke.py`
  - Ensures completed API status does not alter QA acceptance rule.
- Scope enforcement:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`

## Risks and Rollback

- Risk: Tasking order payload may not include direct STAC item IDs.
  - Mitigation: fallback geometry/time-window STAC search across prioritized collections.
- Risk: Preview loading may fail for some completed orders.
  - Mitigation: explicit status feedback, checkbox reset, non-destructive behavior for tracking rows.
- Rollback:
  - Revert changes in `main_dock.py`, `plugin.py`, `source_service.py`, and preview helper module.
  - Existing Accept/Re-Task/Cancel workflow remains unchanged.
