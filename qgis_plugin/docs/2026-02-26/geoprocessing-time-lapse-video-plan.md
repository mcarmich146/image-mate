# Geoprocessing Time Lapse Video Design and Implementation Plan

- Date: 2026-02-26
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

Add a new geoprocessing image-processing action that generates a time-lapse video from project raster layers with this operator workflow:

1. Click `Generate Time Lapse`.
2. Select one or more raster layers.
3. Add selections either as a combined frame (`Add As A Frame`) or as per-layer frames (`Add As A Stack`).
4. Review and edit the frame queue.
5. Configure FPS and frame hold count.
6. Configure per-frame overlay text (default to layer name or layer-set name).
7. Generate MP4 to campaign default output location or user-selected path.

## Existing Reusable Components

- `ui/main_dock.py`:
  - Existing geoprocessing tab/button patterns (`Create VRT`, `Sharpen`, `Resample`) for signal wiring and modal payload collection.
  - `_project_raster_layer_options()` for project raster discovery.
- `plugin.py`:
  - Geoprocessing request handlers (`handle_create_vrt_request`, `handle_sharpen_image_request`, resample handlers).
  - `_campaign_geoprocessing_output_path()` for campaign-managed default outputs.
- `workflow_execution/worker.py`:
  - Existing video rendering/overlay approach used by `temporal_stack_to_video` (render via `QgsMapSettings` + ffmpeg).

## Proposed Backend Changes

- Add `services/time_lapse_video_service.py`:
  - `normalize_time_lapse_frames()` for request/frame normalization.
  - `normalize_time_lapse_fps()` for FPS input normalization.
  - `TimeLapseVideoService.render_project_time_lapse()` to:
    - resolve selected raster layers by project ID,
    - render one image per logical frame (combined layers supported),
    - duplicate rendered frames according to hold count,
    - apply per-frame overlay text,
    - encode MP4 with ffmpeg.
- Add plugin-level handler `handle_generate_time_lapse_request()`:
  - validates request via service normalizers,
  - resolves default/campaign output path when custom output path is blank,
  - uses current map canvas extent/CRS when available,
  - delegates rendering to `TimeLapseVideoService`,
  - reports success/failure via message bar and debug logs.

## UI Wiring Changes (Minimal)

- Add new dock signal:
  - `generate_time_lapse_requested = pyqtSignal(dict)`
- Add new geoprocessing button in Image Processing group:
  - `Generate Time Lapse`
- Add dialog in `main_dock.py` to remain UI-thin:
  - project raster selection list (checkable),
  - `Add As A Frame` and `Add As A Stack` actions,
  - frame queue table with editable columns for:
    - frame name,
    - hold frames,
    - overlay text,
  - FPS spinner,
  - optional output label and optional custom output file path.
- Emit payload only; no rendering logic in UI.

## Implementation Steps

1. Add backend service module for normalization + rendering + ffmpeg encoding.
2. Add new geoprocessing signal/button/dialog payload collection in `ui/main_dock.py`.
3. Wire signal in `plugin.py` and implement request handler.
4. Add terminal smoke test for new normalization helpers.
5. Run scope guard and derive CLI test checklist.
6. Execute targeted smoke tests.

## Terminal-Only Test Plan

- New smoke test:
  - `qgis_plugin/test/time_lapse_video_service_smoke.py`
  - verifies:
    - frame normalization (dedupe layer IDs, hold floor, default overlay label),
    - FPS normalization/default behavior,
    - failure path when no valid frame layers are provided.
- Existing smoke regression:
  - `qgis_plugin/test/resample_workflows_smoke.py` to ensure nearby geoprocessing constants/workflows remain stable.
- Scope and checklist tooling:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
  - `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`

## Risks and Rollback

- Runtime dependency risk:
  - ffmpeg not installed in PATH -> explicit runtime error message to operator.
- Render context risk:
  - mixed CRS or empty extent -> fail fast with clear diagnostics.
- UI misuse risk:
  - invalid hold values -> UI validation before request emit.
- Rollback:
  - Revert added signal/button/handler/service if operational issues are discovered.
