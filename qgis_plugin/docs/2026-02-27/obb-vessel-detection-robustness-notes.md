# OBB Vessel Detection Robustness Notes (2026-02-27)

## Problem Observed
- OBB vessel detection was intermittent ("hit-and-miss"), with frequent false negatives.
- Debug artifacts also showed unstable class IDs/confidence behavior across runs/environments.

## Root Causes Confirmed
1. Ambiguous OBB layout detection:
- Parser inferred OBB layout only when an angle column had values outside `[0, 1]`.
- Some valid OBB exports produce angle-like columns within `[0, 1]`, so OBB parsing was skipped.
- Result: output was misread as plain XYWH + class probabilities, causing class/confidence drift.

2. Missing objectness-aware fallback for OBB variants:
- Some OBB exports may include explicit objectness in addition to class scores.
- Prior parsing path could misinterpret this and shift class IDs or confidence semantics.

3. Aspect-ratio distortion during preprocessing:
- Input chips were resized directly to model size (e.g., `1024x1024`) without letterboxing.
- Non-square extents were stretched, reducing geometric fidelity of elongated vessels.

4. No vessel-class preference when model metadata is available:
- Generic detector outputs were not constrained to vessel-like classes when class names were known.
- This increased non-vessel competition in top-ranked detections.

## Implemented Mitigations
- Added metadata-aware parsing hints (`task`, class count, class names) from ONNX model metadata.
- Made OBB parsing resilient when angle columns are numerically ambiguous.
- Added objectness-aware OBB parsing mode and automatic mode selection from class-count hints.
- Switched preprocessing to letterbox + exact unletterbox coordinate restoration.
- Added vessel-class filtering (`ship/boat/vessel/...`) when model class metadata is present.
- Unified behavior between:
  - `qgis_plugin/image_mate_qgis_plugin/services/vessel_inference_runner.py`
  - `qgis_plugin/image_mate_qgis_plugin/services/vessel_detection_service.py`
  - `qgis_plugin/scripts/vessel_inference/infer_onnx.py` (delegates to runner)

## Verification
- Added smoke regression test:
  - `qgis_plugin/test/vessel_obb_parser_smoke.py`
- Covered scenarios:
  - OBB without objectness and ambiguous angle range.
  - OBB with explicit objectness.
  - Letterbox/unletterbox coordinate preservation.

## Remaining Limitation
- Model quality/data coverage still bounds recall.
- If the model itself is underfit for target vessel domains, detection robustness also requires dataset expansion and retraining.
