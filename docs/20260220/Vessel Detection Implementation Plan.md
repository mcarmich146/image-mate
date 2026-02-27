# Ultralytics Vessel Detection Documentation + Development Plan (docs/20260220)

## Summary
Create two markdown documents in `docs/20260220` that fully specify a geoprocessing-first vessel detection capability in the QGIS plugin, with continuous model improvement from QA using Ultralytics training and ONNX deployment inference. The documents will be decision-complete and implementation-ready.

## Files To Create
1. `docs/20260220/Vessel_Detection_Ultralytics_Design.md`  
Purpose: system design, architecture, interfaces, data contracts, and QA-to-retraining loop.
2. `docs/20260220/Vessel_Detection_Ultralytics_Development_Plan.md`  
Purpose: phased execution plan, task breakdown, dependencies, testing, rollout, and acceptance gates.

## Design Doc Content Spec
1. Title and context  
Use title `Vessel Detection Design (Ultralytics + ONNX) (2026-02-20)` and state objective: detect a few vessels in selected raster, estimate length/beam in meters, and filter Vessel DB by dimensions.
2. Explicit decisions  
State locked choices: geoprocessing action first, OBB labels, local CLI retraining, conservative promotion gate, ONNX inference runtime.
3. Scope  
In scope: one-click detect on selected raster layer, detection layer output, auto-fill Asset Intel length/width filters, QA capture and export, batch retraining pipeline, model registry/promotion.  
Out of scope: workflow-node-first integration, online per-label training, server inference-first architecture.
4. End-to-end architecture  
Define flow: selected local georeferenced raster -> ONNX vessel inference -> OBB to metric dimensions -> detection vector layer + confidence -> optional auto-filter into Asset Intel -> QA approve/reject/edit/add -> dataset export -> Ultralytics retrain -> ONNX export -> evaluation -> promotion.
5. Measurement method  
Define exact conversion: use raster geotransform to map OBB major/minor axis endpoints from pixel to CRS coordinates; compute length/width in meters in projected CRS; for geographic CRS, transform endpoints to local metric CRS before distance calculation; fallback to latitude-based approximation only with warning.
6. Auto-filter strategy for Vessel DB  
Define default uncertainty window: length range = measured length ±20%; width range = measured width ±25%; clamp minimum at 0; push values into existing Asset Intel payload fields and trigger search.
7. QA data model  
Define QA vector feature fields: `run_id`, `scene_id`, `source_layer_id`, `detection_id`, `qa_status`, `label_source`, `confidence`, `length_m`, `width_m`, `timestamp_utc`, `model_version`.  
Define statuses: `pending`, `approved`, `rejected`.  
Define label sources: `model`, `manual`.
8. Dataset/export format  
Define YOLO OBB export: one image chip + one label txt per chip, normalized OBB coords.  
Define chip defaults: `1024x1024` with `128` px context padding.  
Define train/val/test split by scene key: `70/15/15`.
9. Model lifecycle and registry  
Define registry file `models/registry/models.json` with fields: `model_id`, `created_utc`, `train_dataset_id`, `metrics`, `onnx_path`, `status`, `promoted_from`, `notes`.  
Define status values: `candidate`, `production`, `archived`.
10. Promotion policy (conservative)  
Define gate: candidate promotes only if holdout `mAP50` is not worse than production by more than `0.01`, `mAP50-95` is not lower, length MAE does not increase by more than `0.5m`, width MAE does not increase by more than `0.3m`, and sanity set pass rate is unchanged or better.
11. Storage paths  
Define campaign-relative paths: `ml/vessel/datasets/`, `ml/vessel/runs/`, `ml/vessel/models/`, `ml/vessel/qa_exports/`, `ml/vessel/eval/`.
12. Failure modes and operator behavior  
Document required behavior for missing ONNX runtime, non-local raster, non-georeferenced raster, invalid CRS transform, empty detections, and QA export with zero approved labels.
13. Security and performance notes  
Document local-only processing defaults, no credential expansion, expected runtime targets on CPU, and optional GPU usage only for retraining CLI.
14. Completion criteria  
Define done state: operator can run detection, see metric dimensions, filter Asset Intel results, capture QA labels, retrain model batch, and promote model with registry update.

## Development Plan Doc Content Spec
1. Title and delivery objective  
Use title `Vessel Detection Development Plan (2026-02-20)` and tie directly to the design doc.
2. Phase 0: Foundations  
Add config and path scaffolding for ML assets and QA exports.  
Add model registry file initialization and campaign path helpers.
3. Phase 1: Inference + UI (geoprocessing-first)  
Add new Geoprocessing section/card and request signal for vessel detection.  
Implement handler and service that run ONNX inference on selected local raster.  
Create output detection vector layer with fields and style.
4. Phase 2: Dimension extraction + Asset Intel integration  
Implement robust pixel->meter conversion and uncertainty windows.  
Auto-fill Asset Intel `length_min_m`, `length_max_m`, `width_min_m`, `width_max_m` and trigger search.
5. Phase 3: QA workflow  
Create QA layer workflow with approve/reject/edit/add behavior.  
Add “Finalize QA Batch” export command for YOLO OBB dataset packaging.
6. Phase 4: Retraining pipeline (local CLI)  
Add scripts for export verification, training, evaluation, ONNX export, and promotion update.  
Define script I/O contracts and artifact outputs.
7. Phase 5: Promotion + rollback operations  
Add model selection and rollback procedure in registry.  
Document runbook for failed candidate model.
8. Phase 6: Workflow-node extension (later)  
Document deferred work to expose detector as workflow function after stable geoprocessing path.
9. Milestones and acceptance gates  
Define milestone checks per phase with objective pass/fail criteria.
10. Risk log and mitigations  
List dependency risks (onnxruntime in QGIS env, model drift, label noise, CRS errors) with mitigations.
11. Rollout strategy  
Define canary usage with one campaign first, then default enable after metrics stabilize.
12. Operational metrics  
Track detection count per run, mean confidence, QA approval ratio, retrain cadence, promotion rate, and post-promotion MAE.

## Public API / Interface / Type Changes To Specify In Docs
1. `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`  
Add signal `vessel_detect_requested` and dialog payload contract.
2. `qgis_plugin/image_mate_qgis_plugin/plugin.py`  
Wire signal and add `handle_vessel_detect_request(payload)` plus helper to apply Asset Intel size filters.
3. `qgis_plugin/image_mate_qgis_plugin/services/vessel_detection_service.py` (new)  
Define `detect(layer_path, model_path, conf, iou, max_det) -> detection list`.
4. `qgis_plugin/image_mate_qgis_plugin/services/settings_service.py`  
Add settings fields for default model path and inference thresholds.
5. `qgis_plugin/image_mate_qgis_plugin/ui/settings_dialog.py`  
Add vessel model/inference settings controls.
6. `qgis_plugin/image_mate_qgis_plugin/services/campaign_storage_service.py`  
Add methods for vessel ML directories under campaign root.
7. `qgis_plugin/scripts/vessel_training/*.py` (new)  
Define CLI contracts for `export`, `train`, `evaluate`, `promote`.

## Test Cases And Scenarios To Include In Development Plan
1. Detect vessels on valid local GeoTIFF and produce detection layer with non-empty attributes.
2. Reject non-local or non-georeferenced layers with explicit operator guidance.
3. Verify dimension conversion in projected CRS and geographic CRS transformation path.
4. Verify auto-fill of Asset Intel size filters and resulting filtered query execution.
5. Verify QA approve/reject/edit/add workflow and exported YOLO OBB label integrity.
6. Verify retraining script writes metrics and ONNX artifact with expected filenames.
7. Verify conservative promotion gate blocks regressing model and allows qualifying model.
8. Verify rollback switches active production model and logs registry update.
9. Verify empty-detection and empty-approved-label scenarios fail gracefully without crash.

## Assumptions And Defaults (Locked)
1. V1 integration surface is Geoprocessing tab action, not workflow node.
2. Label geometry is OBB-compatible QA geometry.
3. Retraining runs via local CLI pipeline, not in-plugin training.
4. Inference runtime is ONNX deployment.
5. Promotion policy is conservative.
6. Default inference params: `conf=0.25`, `iou=0.45`, `max_det=20`.
7. Default filter uncertainty: length ±20%, width ±25%.
8. Default chip export: `1024` px with `128` px padding.
9. Default split: train/val/test = `70/15/15` by scene key.
