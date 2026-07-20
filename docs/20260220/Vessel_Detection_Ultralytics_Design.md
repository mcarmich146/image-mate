# Vessel Detection Design (Ultralytics + ONNX) (2026-02-20)

## Objective
Deliver a geoprocessing-first vessel detection capability in the QGIS plugin that:

- Detects a small number of vessels in a selected local raster.
- Estimates vessel length and beam in meters from oriented detections.
- Uses those measurements to filter Vessel DB candidates via existing Asset Intel dimension filters.
- Continuously improves over time through QA labeling, batch retraining, evaluation, and conservative model promotion.

## Locked Decisions
- Integration surface in V1: Geoprocessing action in plugin UI (not workflow-node-first).
- Label geometry for QA/retraining: Oriented bounding boxes (OBB).
- Retraining execution: local CLI pipeline.
- Inference runtime in plugin: ONNX deployment.
- Promotion policy: conservative gate with explicit regression guards.

## Scope

### In Scope
- One-click vessel detection on a selected local georeferenced raster layer.
- Detection output layer with confidence and measured `length_m` and `width_m`.
- Auto-fill and trigger of Asset Intel dimension filters.
- QA workflow for approve/reject/edit/add labels.
- QA export to YOLO OBB dataset format.
- Batch retraining workflow using Ultralytics.
- ONNX export, evaluation, and model registry-based promotion/rollback.

### Out of Scope
- Workflow-node-first detector integration.
- Online or per-label incremental model updates.
- Server-first inference architecture.

## End-to-End Architecture
1. Analyst selects a project raster layer and runs `Vessel Detection` from Geoprocessing.
2. Plugin validates that the layer source is local and georeferenced.
3. `VesselDetectionService` loads ONNX model and performs inference.
4. Service returns OBB detections in pixel and map space, including confidence.
5. Plugin computes `length_m` and `width_m` per detection.
6. Plugin creates/stores a vessel detection vector layer with attributes and styling.
7. Optional: plugin auto-applies Asset Intel filter ranges and triggers Asset Intel search.
8. Analyst performs QA (approve/reject/edit/add) on detection geometry and metadata.
9. QA batch is finalized and exported into YOLO OBB dataset structure.
10. Local CLI retraining pipeline runs Ultralytics training, evaluates holdout, exports ONNX.
11. Promotion script applies conservative gate and updates model registry.
12. Plugin uses promoted model for future inference; rollback remains available.

## Public Interfaces and Type Contracts

### `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
Add signal:

- `vessel_detect_requested = pyqtSignal(dict)`

Dialog payload contract:

```json
{
  "layer_id": "string",
  "model_path": "string",
  "conf_threshold": 0.25,
  "iou_threshold": 0.45,
  "max_detections": 20,
  "autofill_asset_intel_filters": true,
  "output_name_hint": "optional string"
}
```

### `qgis_plugin/image_mate_qgis_plugin/plugin.py`
Add:

- signal wiring from dock to `handle_vessel_detect_request(payload)`.
- helper: `_apply_asset_intel_vessel_size_filters(detection_row)`.

Behavior:
- If no detection is explicitly selected, use highest-confidence detection for auto-filtering.
- If detections are empty, do not mutate Asset Intel filters.

### `qgis_plugin/image_mate_qgis_plugin/services/vessel_detection_service.py` (new)
Core method:

```python
def detect(
    layer_path: str,
    model_path: str,
    conf: float,
    iou: float,
    max_det: int,
) -> list[dict]:
    ...
```

Return shape per detection:

```json
{
  "detection_id": "string",
  "class_id": 0,
  "class_name": "vessel",
  "confidence": 0.91,
  "obb_px": [[x1, y1], [x2, y2], [x3, y3], [x4, y4]],
  "bbox_px": [xmin, ymin, xmax, ymax],
  "source_width_px": 4096,
  "source_height_px": 4096
}
```

### `qgis_plugin/image_mate_qgis_plugin/services/settings_service.py`
Add fields:

- `vessel_model_default_path: str = ""`
- `vessel_conf_threshold_default: float = 0.25`
- `vessel_iou_threshold_default: float = 0.45`
- `vessel_max_detections_default: int = 20`

Persist in `QSettings` under:

- `vessel/model_default_path`
- `vessel/conf_threshold`
- `vessel/iou_threshold`
- `vessel/max_detections`

### `qgis_plugin/image_mate_qgis_plugin/ui/settings_dialog.py`
Add a `Vessel Detection` group for:

- ONNX model path.
- default confidence threshold.
- default IoU threshold.
- default max detections.

### `qgis_plugin/image_mate_qgis_plugin/services/campaign_storage_service.py`
Add methods:

- `campaign_vessel_ml_root(campaign_uid) -> Path`
- `campaign_vessel_dataset_dir(campaign_uid, dataset_id) -> Path`
- `campaign_vessel_runs_dir(campaign_uid) -> Path`
- `campaign_vessel_models_dir(campaign_uid) -> Path`
- `campaign_vessel_qa_export_dir(campaign_uid, batch_id) -> Path`
- `campaign_vessel_eval_dir(campaign_uid) -> Path`

### `qgis_plugin/scripts/vessel_training/*.py` (new)
Required CLIs and contracts:

- `export.py`: reads approved QA labels, writes YOLO OBB dataset + manifest.
- `train.py`: trains Ultralytics model from exported dataset.
- `evaluate.py`: computes holdout metrics and dimension MAE.
- `promote.py`: applies promotion gate and updates registry.

## Measurement Method

### Input Requirements
- Raster must be local file-backed (`.tif`, `.tiff`, `.jp2`).
- Raster must have valid geotransform and CRS.

### OBB to Length/Width in Pixels
For corners `p0..p3` in clockwise order:
- Compute edge lengths:
  - `e01 = dist(p0, p1)`
  - `e12 = dist(p1, p2)`
  - `e23 = dist(p2, p3)`
  - `e30 = dist(p3, p0)`
- Major axis pixel length = mean of longer opposite edges.
- Minor axis pixel length = mean of shorter opposite edges.
- Major and minor endpoints are midpoints of opposite edges.

### Pixel to Map Coordinates
Use GDAL geotransform:
- `X = GT0 + px * GT1 + py * GT2`
- `Y = GT3 + px * GT4 + py * GT5`

Transform major/minor endpoint pairs to map coordinates.

### Distance in Meters
- If CRS is projected with meter units: Euclidean distance in map coordinates.
- If CRS is geographic (`EPSG:4326` style):
  - Transform endpoints to a local metric CRS centered on detection centroid (preferred: local UTM zone).
  - Compute Euclidean distances in transformed coordinates.
- Fallback if CRS transform fails:
  - Use latitude-aware degree-to-meter approximation with warning flag.
  - Mark detection attribute `measurement_warning` with transform failure detail.

### Output Attributes
- `length_m` and `width_m` rounded to 2 decimals.
- Guarantee `length_m >= width_m` via axis normalization.

## Auto-Filter Strategy for Vessel DB
From chosen detection:

- `length_min_m = max(0, length_m * 0.80)`
- `length_max_m = max(0, length_m * 1.20)`
- `width_min_m = max(0, width_m * 0.75)`
- `width_max_m = max(0, width_m * 1.25)`

Apply these values to existing Asset Intel payload keys:
- `length_min_m`
- `length_max_m`
- `width_min_m`
- `width_max_m`

Then trigger existing Asset Intel search flow.

## QA Data Model

### Required Fields
- `run_id`
- `scene_id`
- `source_layer_id`
- `detection_id`
- `qa_status`
- `label_source`
- `confidence`
- `length_m`
- `width_m`
- `timestamp_utc`
- `model_version`

### Enumerations
- `qa_status`: `pending`, `approved`, `rejected`
- `label_source`: `model`, `manual`

### Default Rules
- New model detections: `qa_status=pending`, `label_source=model`.
- Manual additions: `qa_status=pending`, `label_source=manual`.
- Edited features remain `pending` until explicit approval.
- Export includes approved labels only.

## Dataset and Export Format

### YOLO OBB Labels
One `.txt` per chip, each line:

`<class_id> <x1> <y1> <x2> <y2> <x3> <y3> <x4> <y4>`

- Coordinates normalized to `[0, 1]`.
- Single class for now: `class_id=0` (`vessel`).

### Chip Defaults
- Chip size: `1024x1024`.
- Context padding around feature: `128` pixels.

### Dataset Split
- Deterministic split by scene key:
  - train: `70%`
  - val: `15%`
  - test: `15%`

## Model Lifecycle and Registry
Registry path:

- `models/registry/models.json`

Top-level structure:

```json
{
  "schema_version": 1,
  "active_production_model_id": "vessel_20260220T210000Z",
  "models": [
    {
      "model_id": "vessel_20260220T210000Z",
      "created_utc": "2026-02-20T21:00:00Z",
      "train_dataset_id": "dataset_20260220T180000Z",
      "metrics": {
        "map50": 0.81,
        "map50_95": 0.56,
        "length_mae_m": 1.9,
        "width_mae_m": 0.8,
        "sanity_pass_rate": 0.97
      },
      "onnx_path": "ml/vessel/models/vessel_20260220T210000Z/model.onnx",
      "status": "production",
      "promoted_from": "vessel_20260214T180000Z",
      "notes": "first conservative-gated promotion"
    }
  ]
}
```

Allowed `status` values:
- `candidate`
- `production`
- `archived`

## Promotion Policy (Conservative)
A candidate can be promoted only if all checks pass against current production:

- `mAP50_candidate >= mAP50_production - 0.01`
- `mAP50-95_candidate >= mAP50-95_production`
- `length_MAE_candidate <= length_MAE_production + 0.5`
- `width_MAE_candidate <= width_MAE_production + 0.3`
- `sanity_pass_rate_candidate >= sanity_pass_rate_production`

If any check fails, candidate remains `candidate` and promotion is blocked.

## Storage Paths
Campaign-relative directories:

- `ml/vessel/datasets/`
- `ml/vessel/runs/`
- `ml/vessel/models/`
- `ml/vessel/qa_exports/`
- `ml/vessel/eval/`

Recommended path examples:
- `ml/vessel/datasets/<dataset_id>/`
- `ml/vessel/runs/<train_run_id>/`
- `ml/vessel/models/<model_id>/model.onnx`
- `ml/vessel/qa_exports/<batch_id>/`
- `ml/vessel/eval/<model_id>_<dataset_id>.json`

## Failure Modes and Operator Behavior

| Failure Mode | Required Behavior |
| --- | --- |
| `onnxruntime` not installed | Abort detection; show actionable message with dependency requirement. |
| Non-local raster source | Abort detection; instruct analyst to use a local file-backed raster. |
| Raster not georeferenced | Abort detection; explain that metric dimensions require CRS/geotransform. |
| CRS transform failure during measurement | Keep detections; compute fallback approximation; set warning attribute and warning UI message. |
| Empty detections | Create no layer updates beyond status; notify analyst "no vessels detected". |
| QA export has zero approved labels | Abort export with clear message and no downstream retraining trigger. |

## Security and Performance Notes
- Inference is local-only by default; no additional credential use.
- No hidden outbound network calls in detection path.
- Path handling must use sanitized campaign-aware storage paths.
- Expected CPU runtime target for V1:
  - single 2048x2048 raster: under 15 seconds on analyst laptop class CPU.
- GPU acceleration is optional and only for local CLI retraining pipeline.

## Completion Criteria
The feature is complete when analysts can:

1. Run vessel detection on a selected local georeferenced raster.
2. See per-detection confidence, length, and beam in meters.
3. Auto-apply size filters and query Asset Intel/Vessel DB candidates.
4. Perform QA approve/reject/edit/add with persisted metadata.
5. Export approved QA labels to YOLO OBB dataset.
6. Run batch retraining and ONNX export via local CLI.
7. Promote or rollback model versions through registry-managed operations.
