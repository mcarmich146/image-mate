# Mosaic Tracking Preview Multi Thumbnail Fix Design and Implementation Plan

- Date: 2026-02-27
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

Mosaic Tracking preview behavior has three defects:

1. Preview layer sometimes appears as streamed tile context rather than full thumbnail-style image context.
2. Unchecking Preview can leave imagery on the map.
3. Only one row can be previewed at a time; selecting a second row clears the first preview.

Required behavior:

- Preview should prioritize full-image preview/thumbnail rendering.
- Uncheck should remove only that row's preview layer.
- Multiple rows should be previewable concurrently.

## Existing Reusable Components

- `ImageMateMainDock` already emits row-level preview toggle payloads.
- `ImageMatePlugin.handle_mosaic_tracking_preview_toggled(...)` already owns backend orchestration.
- Existing layer helpers are reusable: `_add_layer_to_image_mate_group`, `_remove_layer_by_id`.
- Existing imagery fallback chain is reusable:
  - `_load_item_imagery_layer` (asset-based preview/thumbnail path)
  - `_build_stream_layer_for_item` (stream fallback).

## Proposed Backend Changes

- Switch Mosaic tracking preview state from single layer id to per-tile map:
  - `tile_id -> layer_id`.
- Add per-tile clear helper:
  - `_clear_mosaic_tracking_preview_layer_for_tile(tile_id=...)`.
- Update toggle handler:
  - `enabled=false` clears only the target tile preview layer.
  - supports multiple active preview layers in same project.
  - preserves existing active previews while adding new ones.
- Update render strategy:
  - prefer `_load_item_imagery_layer(item)` first (thumbnail/preview assets),
  - fallback to `_build_stream_layer_for_item(item)` only when asset load fails.
- Strengthen preview asset handling in streaming mixin:
  - for `preview`/`thumbnail`, require georeference (attempt georeference from item bounds; otherwise failover).

## UI Wiring Changes (Minimal)

- Switch UI preview selection state from single tile id to set of tile ids.
- Keep existing row checkboxes; remove implicit single-select behavior.
- Add `set_mosaic_tracking_preview_tiles(...)` for bulk sync from backend state.
- Keep `set_mosaic_tracking_preview_tile(...)` as compatibility wrapper.

## Implementation Steps

1. Convert UI preview state to set semantics and checkbox sync by set membership.
2. Convert plugin preview layer state to per-tile map and add clear-per-tile helper.
3. Update preview toggle handler to clear/add by tile and sync checked set.
4. Update render path to thumbnail-first with stream fallback.
5. Tighten preview/thumbnail georeference checks in streaming loader.
6. Add terminal smoke check script for multi-preview and thumbnail-first wiring.

## Terminal-Only Test Plan

- Static behavior smoke:
  - `py -3 qgis_plugin/test/mosaic_tracking_preview_multi_smoke.py`
  - validates multi-preview state maps, per-tile clear wiring, thumbnail-first render ordering, and preview georef guard snippets.
- Syntax checks:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/plugin.py qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py`

## Risks and Rollback

- Risk: some preview/thumbnail assets may be non-georeferenced and fail.
  - Mitigation: automatic fallback to stream layer path when asset-based preview cannot be georeferenced.
- Risk: stale UI checkboxes if layers are manually removed outside plugin flow.
  - Mitigation: backend sync resets checkbox set on project reload and toggle events.
- Rollback: revert per-tile preview map/state and restore prior single-preview behavior.
