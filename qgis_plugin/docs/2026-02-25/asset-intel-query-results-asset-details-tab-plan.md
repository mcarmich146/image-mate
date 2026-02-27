# Asset Intel Query Results Asset Details Tab Design and Implementation Plan

- Date: 2026-02-25
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- The `Query Results` page was visually overloaded because the asset list and full detail UI were stacked in one page.
- Operators need faster triage in list view and deliberate transition to full detail inspection.

## Existing Reusable Components
- Existing container tab: `self.asset_intel_query_results_tabs` with `Asset Query` and `Query Results`.
- Existing detail stack: `detail_tabs` (`Overview`, `Systems`, `Analyst Notes`, `Raw`, `Sources`).
- Existing selection wiring: `asset_intel_results_list.currentItemChanged -> _emit_asset_intel_asset_selected`.

## Proposed Backend Changes
- No backend/service changes.
- Pure UI layout and event wiring change in `main_dock.py`.

## UI Wiring Changes (Minimal)
- Add a third top-level tab under Asset Intel: `Asset Details`.
- Keep `Query Results` tab focused on results list only.
- Move all previous `Query Results` detail content into `Asset Details`:
  - status label
  - modify/delete action row
  - detail tabs (`Overview/Systems/Notes/Raw/Sources`)
- Add list double-click behavior:
  - double-clicking any result row triggers detail load and switches to `Asset Details`.

## Implementation Steps
- Introduce helper handlers:
  - `_open_asset_intel_details_tab`
  - `_on_asset_intel_result_double_clicked`
- Connect `asset_intel_results_list.itemDoubleClicked` to the new handler.
- Refactor `_build_asset_intel_tab` so tab contents are:
  - `Asset Query`: query controls + add asset
  - `Query Results`: results list only
  - `Asset Details`: status/actions/details stack
- Replace hard-coded search jump tab index with `indexOf(self.asset_intel_results_tab)`.

## Terminal-Only Test Plan
- `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
- `py -3 qgis_plugin/test/asset_intel_domain_hierarchy_smoke.py`
- `py -3 qgis_plugin/test/mosaic_preview_resolution_smoke.py`
- `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`

## Risks and Rollback
- Risk: Users may not discover `Asset Details`; mitigated by explicit tab title and double-click shortcut.
- Rollback: revert `main_dock.py` tab layout and double-click handler changes.
