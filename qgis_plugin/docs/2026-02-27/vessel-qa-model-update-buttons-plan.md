# Vessel Qa Model Update Buttons Design and Implementation Plan

- Date: 2026-02-27
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

The Geoprocessing -> Vessel QA panel supported:
- QA layer creation/status updates
- QA batch finalization

It did not support:
- Quickly opening finalized QA batch folders from the panel
- Triggering model update/fine-tune preparation from finalized QA batches

Requested UX addition:
- Add a button to open batch folder
- Add a button to fine-tune/update the model with batched QA chips

## Existing Reusable Components

- `plugin.py::handle_vessel_finalize_qa_batch_request` already exports finalized QA artifacts and writes `qa_batch_manifest.json`.
- `CampaignStorageService` already defines deterministic vessel ML paths:
  - `ml/vessel/qa_exports`
  - `ml/vessel/datasets`
  - `ml/vessel/runs`
- Existing script scaffolds already exist and are reusable:
  - `qgis_plugin/scripts/vessel_training/export.py`
  - `qgis_plugin/scripts/vessel_training/train.py`
- `main_dock.py` already follows signal-driven UI delegation patterns to plugin handlers.

## Proposed Backend Changes

- Add new backend service:
  - `qgis_plugin/image_mate_qgis_plugin/services/vessel_training_service.py`
- Service responsibilities:
  - Resolve QA batch folder by:
    - preferred path, or
    - explicit batch id, or
    - latest finalized batch fallback
  - Validate and parse `qa_batch_manifest.json`
  - Initialize model-update scaffold by invoking existing training scripts:
    - dataset scaffold (`export.py`)
    - training-run scaffold (`train.py`)
  - Return deterministic output metadata (dataset/run manifest paths, batch context)
- Extend plugin wiring in `plugin.py`:
  - Track `self._last_vessel_qa_batch_dir` after finalize/update actions
  - Add handlers:
    - `handle_vessel_open_qa_batch_folder_request`
    - `handle_vessel_model_update_request`
  - Wire new dock signals to handlers
  - Use `QDesktopServices.openUrl` for folder open behavior

## UI Wiring Changes (Minimal)

- Extend dock signals in `main_dock.py`:
  - `vessel_qa_open_batch_folder_requested`
  - `vessel_qa_model_update_requested`
- Add Vessel QA panel buttons:
  - `Open QA Batch Folder`
  - `Update Model from QA Batch`
- Keep UI thin:
  - Open-folder button emits a request
  - Update-model button opens a small form (batch id, dataset id, base weights, epochs, image size) and emits payload
  - No training/path business logic added to UI

## Implementation Steps

1. Created service `VesselTrainingService` and `VesselQABatchContext` dataclass.
2. Implemented batch resolution and manifest validation.
3. Implemented model-update scaffold initialization using existing script entry points.
4. Added two dock signals and two panel buttons.
5. Added plugin signal connections and handlers.
6. Updated QA finalize handler to persist last finalized batch directory in plugin state.
7. Added terminal smoke test:
   - `qgis_plugin/test/vessel_training_service_smoke.py`

## Terminal-Only Test Plan

- Python syntax check:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/vessel_training_service.py qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py qgis_plugin/image_mate_qgis_plugin/plugin.py qgis_plugin/test/vessel_training_service_smoke.py`
- Service smoke test:
  - `py -3 qgis_plugin/test/vessel_training_service_smoke.py`
  - Expected: `vessel_training_service_smoke: ok`
  - Includes negative check for zero-approved QA batches (must raise and abort model update initialization)
- Scope enforcement:
  - `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
  - Expected: all changed files under `qgis_plugin/**`

Observed outcomes on 2026-02-27:
- Syntax check passed.
- `vessel_training_service_smoke.py` passed.
- Scope check passed.

## Risks and Rollback

- Current repository training scripts are scaffold-level (manifest/directory initialization only).
  Effect: "Update Model" currently initializes dataset/run artifacts but does not execute full Ultralytics training/evaluation/promotion.
- If users expect full training in this button, next phase should replace script scaffolds with executable training/eval logic while preserving the same service interface.
- Rollback path:
  - Remove new buttons/signals
  - Remove plugin handlers and service import
  - Keep finalized QA export behavior unchanged
