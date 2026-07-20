# Mosaic Tracking More Button Api Detail Popup Design and Implementation Plan

- Date: 2026-02-27
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

Operators need quick access to full collection/order API detail while reviewing rows in:
`Collection Requests -> Mosaic -> Tracking`.

Current state only shows summary columns in the table and requires manual external API probing.
Requested behavior is a per-row `More` button that opens a popup with full API detail.

## Existing Reusable Components

- `SourceService.get_tasking_order(order_id, contract_id)` already fetches and returns:
  - normalized `order`
  - full API response `raw`
- `MosaicTrackingStore.load_tile(project_id, tile_id)` already resolves `latest_collection_id`.
- Existing Mosaic row action pattern in `main_dock.py`:
  - per-row buttons (`Accept`, `Re-Task`, `Cancel`)
  - signal emission from UI to plugin handlers.

## Proposed Backend Changes

- Add plugin handler `handle_mosaic_more_request(payload)`:
  - validate project/tile context
  - load tile from Mosaic store
  - resolve collection id and contract id
  - fetch full detail via `SourceService.get_tasking_order(...)`
  - send assembled payload to UI popup renderer.
- Keep API call orchestration in plugin/backend (UI remains orchestration/render-only).

## UI Wiring Changes (Minimal)

- Add new signal: `mosaic_more_requested`.
- Add `More` button as a new column in the Mosaic tracking table.
- Add popup renderer method:
  - `show_mosaic_collection_api_detail_popup(payload)`
  - displays pretty JSON and basic summary header.

## Implementation Steps

1. Add `More` signal and row button wiring in `ui/main_dock.py`.
2. Expand tracking table to 11 columns and append `More` header/column.
3. Add popup dialog method in `ui/main_dock.py` for API detail rendering.
4. Connect new UI signal to plugin handler in `plugin.py`.
5. Implement plugin handler to fetch API detail and invoke popup.
6. Add terminal smoke test for wiring integrity.

## Terminal-Only Test Plan

- Static wiring smoke:
  - `py -3 qgis_plugin/test/mosaic_tracking_more_wiring_smoke.py`
  - verifies signal, table column/header, button wiring, plugin connection and handler API call.
- Scope and derived-check tooling:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback

- Risk: Popup payload may be large for complex API responses.
  - Mitigation: use read-only text area with scroll; no blocking post-processing.
- Risk: Row without collection id cannot fetch detail.
  - Mitigation: disable `More` button when `latest_collection_id` is missing.
- Rollback: remove `More` column/signal/handler only; no schema or persistence migration required.
