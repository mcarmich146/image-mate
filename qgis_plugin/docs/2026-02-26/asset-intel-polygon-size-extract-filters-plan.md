# Asset Intel Polygon Size Extract Filters Design and Implementation Plan

- Date: 2026-02-26
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
- Operators need a one-click way in Asset Query to derive vessel dimensions from a polygon clicked directly on the map canvas.
- Existing manual length/width entry is slow and error-prone.
- Required behavior: compute two perpendicular dimensions (not only longest extent), then apply query filters with +/-5m margins.
- Additional issue observed in current flow: after creating units/systems, detail refresh could still load a different asset when filters changed list selection.

## Existing Reusable Components
- Asset Intel vessel measurement path already uses midpoint-based orthogonal dimensions for OBB detections.
- Asset Intel filter inputs and search re-run path already exist in dock/plugin.
- Central post-mutation refresh path exists (`_refresh_asset_intel_after_mutation`) and can be corrected in one place.

## Proposed Backend Changes
- Add plugin handler to:
  - enter map-click Select Mode
  - capture a canvas click and resolve the clicked polygon feature from visible polygon layers
  - derive oriented bounding box
  - measure two perpendicular centerlines (major/minor) in meters using `QgsDistanceArea`
  - apply +/-5m range to Asset Intel length/width filters
  - trigger Asset Intel search refresh
  - clear the temporary polygon selection and return to pan map mode
- Correct mutation refresh asset-detail selection precedence to always prefer the mutated asset id.

## UI Wiring Changes (Minimal)
- Add Asset Intel query button: `Select Target from Map`.
- While pick mode is active, button text changes to `Select Mode`.
- Keep UI thin: button emits a simple signal; plugin performs geometry extraction and measurement logic.

## Implementation Steps
- Add new dock signal: `asset_intel_polygon_size_from_selection_requested`.
- Add query button and connect it to new signal.
- Connect signal in plugin and implement handler:
  - switch map tool into Select Mode (`QgsMapToolEmitPoint`)
  - on click, identify polygon at clicked map location
  - compute dimensions from oriented bounding box using perpendicular midlines
  - write filter bounds:
    - `length_min = max(0, length - 5)`
    - `length_max = length + 5`
    - `width_min = max(0, width - 5)`
    - `width_max = width + 5`
  - deselect clicked polygon
  - restore pan map mode
  - rerun Asset Intel search and update status text with measured dimensions/angle
- Fix `_refresh_asset_intel_after_mutation` to prefer `selected_asset_id` over currently selected result row id.

## Terminal-Only Test Plan
- `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py qgis_plugin/image_mate_qgis_plugin/plugin.py`
- `py -3 qgis_plugin/test/asset_intel_domain_hierarchy_smoke.py`
- `py -3 qgis_plugin/test/mosaic_preview_resolution_smoke.py`
- `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
- `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback
- Risk: non-rectangular polygons produce unexpected dimensions; mitigated by oriented bounding box normalization before measurement.
- Risk: overlapping polygons under click; mitigated by deterministic first-hit per visible layer order and smallest-area hit within layer.
- Future consideration: off-nadir correction factor for width is intentionally deferred.
- Rollback: revert `main_dock.py` and `plugin.py` hunks for new signal/button/handler and refresh precedence change.
