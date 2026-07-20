# Mosaic Tracking Preview All Candidate Items Design and Implementation Plan

- Date: 2026-02-27
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- In Mosaic Tracking preview flow, `_resolve_mosaic_tracking_preview_item(...)` returned on the first usable id from `preview_item_id_candidates(...)`.
- For acquisitions represented by multiple item ids/tiles, this rendered only one item instead of the full acquisition footprint.
- Goal for this iteration: update the `preview_item_id_candidates` resolution path to use all usable candidate ids for a tile preview.

## Existing Reusable Components
- `preview_item_id_candidates(...)` in `services/mosaic_preview_resolution.py` already extracts an ordered id list.
- `_mosaic_preview_item_is_usable(...)` already validates item assets before rendering.
- `_render_mosaic_tracking_preview_item(...)` already renders one resolved item into a QGIS layer.
- `handle_mosaic_tracking_preview_toggled(...)` already owns preview lifecycle, status text, and dock sync.

## Proposed Backend Changes
- Replace single-item resolver with multi-item resolver:
  - `plugin.py` `_resolve_mosaic_tracking_preview_items(...)` returns all usable items resolved from `preview_item_id_candidates(...)`.
  - Keep STAC search fallback behavior unchanged except return list payload shape.
- Update render lifecycle to support multiple layers for one tile:
  - `_mosaic_tracking_preview_layer_ids` map value becomes list-capable (`tile_id -> [layer_id, ...]`).
  - `_clear_mosaic_tracking_preview_layer(...)` and `_clear_mosaic_tracking_preview_layer_for_tile(...)` remove all layer ids for each tile.
  - `_render_mosaic_tracking_preview_item(...)` appends layer ids for the tile instead of replacing them.
- Update toggle flow:
  - `handle_mosaic_tracking_preview_toggled(...)` resolves `items`, clears tile once, then renders every item.
  - Status/log updated to report item count and first item id.

## UI Wiring Changes (Minimal)
- No UI widget changes.
- Existing preview checkbox state sync remains by tile id list, unaffected by multiple layers per tile.

## Implementation Steps
- Modify `plugin.py` preview resolver path to fan out over all candidate item ids.
- Modify preview layer bookkeeping to handle multiple layer ids per tile.
- Update preview toggle render loop to render all resolved items for enabled tile.
- Keep search fallback and non-preview logic unchanged.

## Terminal-Only Test Plan
- Static smoke: `py -3 qgis_plugin/test/mosaic_tracking_preview_all_candidates_smoke.py`
  - Confirms candidate fan-out resolution method and render loop are present.
  - Confirms preview layer clear/bookkeeping supports list-valued layer id entries.
- Regression smoke:
  - `py -3 qgis_plugin/test/mosaic_tracking_preview_multi_smoke.py`
  - `py -3 qgis_plugin/test/mosaic_preview_resolution_smoke.py`
- Syntax check:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/plugin.py`

## Risks and Rollback
- Risk: multiple candidate layers may increase visual clutter/performance cost for some acquisitions.
- Risk: candidate order may affect layer stack order.
- Rollback: revert `plugin.py` preview resolver/render bookkeeping and remove new smoke file.
