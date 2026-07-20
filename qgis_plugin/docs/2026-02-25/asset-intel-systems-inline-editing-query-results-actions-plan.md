# Asset Intel Systems Inline Editing Query Results Actions Design and Implementation Plan

- Date: 2026-02-25
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- Asset Intel needed in-place CRUD for Systems tab entities without leaving detail context.
- `Modify Asset` / `Delete Asset` actions were on the query page instead of the results/detail page.
- Fielded Unit and Onboard System maintenance required faster edits (double-click row) and quick-add affordances.
- Identifier and unit-system fit child tables needed empty-area double-click insert behavior.

## Existing Reusable Components
- `AssetIntelService` already exposes mutation APIs:
  - `create_system`, `update_system`
  - `create_unit`, `update_unit`
  - `create_unit_identifier`, `update_unit_identifier`
  - `create_unit_system_fit`, `update_unit_system_fit`
- Plugin already had a stable post-mutation refresh path (`_refresh_asset_intel_after_mutation`) used by asset/note CRUD.
- Systems/units/detail table population already centralized in `ImageMateMainDock.set_asset_intel_detail`.

## Proposed Backend Changes
- No database schema change.
- Reuse existing Asset Intel service mutation methods.
- Add one plugin handler that dispatches UI structure mutation requests to service methods and refreshes selected asset detail.

## UI Wiring Changes (Minimal)
- Add one dock signal: `asset_intel_structure_mutation_requested`.
- Move `Modify Asset` and `Delete Asset` buttons from `Asset Query` page to `Query Results` page.
- Keep `Add Asset` on `Asset Query`.
- Add row double-click edit handlers for:
  - Fielded Units table
  - Onboard Systems table
  - Identifier table
  - Unit-system fit table
- Add `New Unit` / `New System` corner action button on Systems scope tabs; label switches by selected tab.
- Install event-filter handling for empty-area double-click on Identifier and unit-system fit tables to trigger create dialogs.

## Implementation Steps
- Extend dock with mutation signal and lightweight editor dialogs for unit/system/identifier/fit.
- Emit normalized mutation payloads from UI (action + payload + optional status text).
- Add plugin mutation dispatcher and connect new dock signal.
- Reuse existing detail refresh path to preserve selected asset context after each mutation.
- Ensure post-mutation refresh always reloads detail for the mutated asset id even when current query filters hide that asset from the results list.
- In plugin mutation dispatch, backfill missing `asset_id` from current selection for `create_unit` / `create_system` requests.
- Keep business rules in service layer and UI limited to input capture/validation.

## Terminal-Only Test Plan
- `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py qgis_plugin/image_mate_qgis_plugin/plugin.py qgis_plugin/image_mate_qgis_plugin/services/asset_intel_service.py`
- `py -3 qgis_plugin/test/asset_intel_domain_hierarchy_smoke.py`
- `py -3 qgis_plugin/test/mosaic_preview_resolution_smoke.py`
- `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback
- Risk: UI double-click can trigger unintended edits; mitigated by explicit dialog confirmation (OK/Cancel).
- Risk: stale selection after mutation; mitigated by central refresh path with selected asset re-selection.
- Rollback: revert `main_dock.py` and `plugin.py` hunks for mutation signal/handlers and double-click hooks.
