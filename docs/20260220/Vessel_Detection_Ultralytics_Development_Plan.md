# Vessel Detection Development Plan (2026-02-20)

## Delivery Objective
Implement the vessel detection design defined in:

- `docs/20260220/Vessel_Detection_Ultralytics_Design.md`

This plan is execution-ready and decision-complete for a geoprocessing-first rollout with ONNX inference, Ultralytics retraining, and conservative model promotion.

## Assumptions and Defaults (Locked)
- V1 integration surface is Geoprocessing action, not workflow node.
- Label geometry is OBB-compatible QA geometry.
- Retraining runs via local CLI pipeline.
- Inference runtime is ONNX deployment.
- Promotion policy is conservative.
- Default inference params: `conf=0.25`, `iou=0.45`, `max_det=20`.
- Default filter uncertainty: length `+-20%`, width `+-25%`.
- Default chip export: `1024` px with `128` px padding.
- Default split: train/val/test = `70/15/15` by scene key.

## Public API / Interface / Type Changes
The following code surfaces are planned:

1. `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
   - Add `vessel_detect_requested` signal.
   - Add Geoprocessing dialog and payload emitter for vessel detection.
2. `qgis_plugin/image_mate_qgis_plugin/plugin.py`
   - Wire signal and implement `handle_vessel_detect_request(payload)`.
   - Add helper for Asset Intel auto-filter application and search trigger.
3. `qgis_plugin/image_mate_qgis_plugin/services/vessel_detection_service.py` (new)
   - Implement ONNX-based inference interface:
     - `detect(layer_path, model_path, conf, iou, max_det) -> detection list`
4. `qgis_plugin/image_mate_qgis_plugin/services/settings_service.py`
   - Add vessel model path and default inference parameters.
5. `qgis_plugin/image_mate_qgis_plugin/ui/settings_dialog.py`
   - Add Vessel Detection settings controls.
6. `qgis_plugin/image_mate_qgis_plugin/services/campaign_storage_service.py`
   - Add campaign vessel ML directory/path helpers.
7. `qgis_plugin/scripts/vessel_training/*.py` (new)
   - Add CLI contracts for `export`, `train`, `evaluate`, `promote`.

## Phase Plan

## Phase 0 - Foundations
### Goal
Prepare config, storage, and registry scaffolding without inference logic yet.

### Tasks
- Extend `ProviderSettings` and `SettingsService` with vessel model/inference defaults.
- Extend settings UI with Vessel Detection configuration group.
- Add campaign storage methods for vessel ML paths.
- Initialize model registry path and JSON schema loader/writer helper.
- Add shared dataclass/types for detection result row and QA row payload.

### Deliverables
- Settings keys and UI fields wired and persisted.
- Campaign-relative vessel directories resolved deterministically.
- Registry helper with schema validation and safe write behavior.

### Acceptance Gate
- Fresh plugin startup works with missing vessel settings (backward compatible defaults).
- Settings save/load round-trips new fields with no regression in existing settings.

## Phase 1 - Inference + UI (Geoprocessing-First)
### Goal
Allow analyst to run vessel detection from Geoprocessing on selected local raster.

### Tasks
- Add new Geoprocessing section/card: `Vessel Detection`.
- Add request dialog:
  - input raster layer
  - model path (optional override)
  - confidence threshold
  - IoU threshold
  - max detections
  - auto-filter toggle
- Add plugin signal wiring and request handler.
- Implement `VesselDetectionService.detect(...)` ONNX inference path.
- Validate local file-backed and georeferenced raster before inference.
- Create output detection vector layer with required attributes and style.

### Deliverables
- End-to-end inference action from UI to output layer creation.
- Clear operator-facing status and error messages for invalid inputs.

### Acceptance Gate
- Successful run on local GeoTIFF produces non-empty detection layer attributes when targets exist.
- Invalid source/layer preconditions fail with explicit guidance.

## Phase 2 - Dimension Extraction + Asset Intel Integration
### Goal
Compute robust metric dimensions and drive Vessel DB filtering.

### Tasks
- Implement OBB axis extraction and pixel-to-map endpoint conversion.
- Implement projected and geographic CRS meter-distance paths.
- Implement fallback approximation with warning attribute.
- Add helper to auto-fill:
  - `length_min_m`, `length_max_m`, `width_min_m`, `width_max_m`
- Trigger Asset Intel search after auto-fill when enabled.

### Deliverables
- Detection attributes include `length_m` and `width_m`.
- Asset Intel filtering can be driven from selected/highest-confidence detection.

### Acceptance Gate
- Verified dimension conversion in projected CRS.
- Verified geographic CRS transform path and fallback warning behavior.
- Verified search payload updates and filtered results return.

## Phase 3 - QA Workflow
### Goal
Capture analyst feedback and prepare trusted labels for retraining.

### Tasks
- Define QA layer schema with fields from design doc.
- Implement actions:
  - Approve detection
  - Reject detection
  - Edit geometry/attributes
  - Add manual OBB label
- Implement `Finalize QA Batch` command:
  - validate approved count > 0
  - export QA snapshot for dataset pipeline
  - write QA batch manifest

### Deliverables
- Analyst QA workflow with status transitions and metadata persistence.
- Batch export command that produces deterministic output bundle.

### Acceptance Gate
- Approved-only export behavior verified.
- Rejected and pending labels excluded from training export.

## Phase 4 - Retraining Pipeline (Local CLI)
### Goal
Train improved models from QA batches and evaluate candidate quality.

### Tasks
- Add `qgis_plugin/scripts/vessel_training/export.py`:
  - convert approved QA labels to YOLO OBB structure
  - deterministic split by scene key
  - write dataset manifest
- Add `train.py`:
  - run Ultralytics training from dataset manifest
  - emit run artifacts and training summary
- Add `evaluate.py`:
  - compute holdout metrics (`mAP50`, `mAP50-95`)
  - compute size errors (`length_MAE`, `width_MAE`)
  - compute sanity pass rate
- Add ONNX export step and output validation.
- Add `promote.py`:
  - load production + candidate metrics
  - apply conservative gate
  - update registry safely

### Deliverables
- Repeatable local CLI retraining/evaluation/promotion workflow.
- ONNX artifacts registered as candidates or production.

### Acceptance Gate
- Candidate run generates expected model and metrics artifacts.
- Promotion gate blocks regression candidates and accepts qualifying ones.

## Phase 5 - Promotion + Rollback Operations
### Goal
Operationalize model selection, rollback, and auditability.

### Tasks
- Add model selection helper for plugin runtime (production model resolution).
- Add rollback command (registry status swap and active model update).
- Add runbook for failed candidate handling and rollback procedure.
- Ensure promotion/rollback actions are logged with timestamp and actor identifier.

### Deliverables
- Registry-backed production model resolution.
- Reliable rollback path with explicit audit trail.

### Acceptance Gate
- Rollback switches active model correctly and preserves historical entries.

## Phase 6 - Workflow Node Extension (Deferred)
### Goal
Document future extension to workflow engine after geoprocessing path is stable.

### Tasks
- Define future workflow function spec (`vessel_detect`) and payload schema.
- Define adapter compatibility and output artifact contract.
- Define validation rules in workflow engine service.

### Deliverables
- Deferred extension spec only; no implementation in this phase.

### Acceptance Gate
- N/A (documentation-only deferred roadmap).

## Milestones and Acceptance Gates
- **M0 Foundation Complete**: settings + paths + registry helpers stable.
- **M1 Inference Action Complete**: analyst can run detection from Geoprocessing.
- **M2 Measurement + Filtering Complete**: dimensions computed and Asset Intel auto-filter works.
- **M3 QA Complete**: QA lifecycle and approved-label export operational.
- **M4 Retraining Complete**: CLI training/eval/ONNX/promotion pipeline operational.
- **M5 Ops Complete**: promotion and rollback runbook-backed operations validated.
- **M6 Deferred Node Spec Complete**: workflow-node extension documented.

## Test Cases and Scenarios
1. Detect vessels on valid local GeoTIFF and produce detection layer with non-empty attributes.
2. Reject non-local or non-georeferenced layers with explicit operator guidance.
3. Verify dimension conversion in projected CRS and geographic CRS transformation path.
4. Verify auto-fill of Asset Intel size filters and resulting filtered query execution.
5. Verify QA approve/reject/edit/add workflow and exported YOLO OBB label integrity.
6. Verify retraining script writes metrics and ONNX artifact with expected filenames.
7. Verify conservative promotion gate blocks regressing model and allows qualifying model.
8. Verify rollback switches active production model and logs registry update.
9. Verify empty-detection and empty-approved-label scenarios fail gracefully without crash.

## Test Strategy
- Unit tests:
  - geometry conversion and meter-distance routines
  - registry read/write and promotion gate logic
  - payload validation and uncertainty window calculations
- Integration tests:
  - UI request -> inference service -> vector layer output
  - detection -> Asset Intel autofill/search flow
  - QA finalize -> dataset export outputs
- CLI smoke tests:
  - export -> train -> evaluate -> promote sequence on sample dataset

## Risk Log and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| `onnxruntime` unavailable in analyst QGIS Python env | Inference blocked | Preflight dependency check and explicit install guidance in UI error. |
| CRS transform failures on edge datasets | Incorrect dimensions | Multi-path conversion strategy with warning flag and fallback approximation. |
| QA label noise | Model quality drift | Approved-only export, review checklist, conservative promotion gate. |
| Model drift across environments | Regression in production | Holdout and sanity metrics required for promotion; rollback supported. |
| Local CLI retraining inconsistency | Non-repeatable results | Manifest-driven datasets, pinned training config, artifact metadata logging. |

## Rollout Strategy
1. Canary rollout on one campaign and one analyst cohort.
2. Validate runtime and QA throughput for at least one full retraining cycle.
3. Promote first candidate only if conservative gate passes.
4. Expand to default-enabled for all campaigns after stable metrics across two cycles.

## Operational Metrics
Track and trend:
- Detection runtime per scene (`seconds`).
- Detection count per run.
- Mean confidence per run.
- QA approval ratio (`approved / reviewed`).
- QA rejection ratio (`rejected / reviewed`).
- Retraining cadence (days between training runs).
- Promotion rate (`promoted / candidates`).
- Post-promotion holdout `mAP50`, `mAP50-95`.
- Post-promotion `length_MAE_m` and `width_MAE_m`.
- Sanity set pass rate over time.

## Definition of Done
Work is complete when:

1. Geoprocessing-first vessel detection is usable end-to-end in plugin.
2. Metric dimensions are computed and usable for Asset Intel filtering.
3. QA workflow reliably produces approved labels for retraining.
4. Local CLI pipeline can train/evaluate/export/promote with registry updates.
5. Promotion/rollback operations are documented, tested, and auditable.
