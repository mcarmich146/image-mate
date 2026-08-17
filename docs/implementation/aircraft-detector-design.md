# Local Aircraft Detector — Design Confirmation

**Status:** implementation target
**Date:** 2026-08-14
**Scope:** one high-resolution Satellogic L1D-SR tile, local ONNX inference, Image Mate API/UI, and a Hermes skill.

## Objective

Run an open-source, locally hosted aircraft detector against only the explicitly supplied high-resolution tile. The first model is the repository's existing `yolo11n-obb.onnx` artifact, which is an Ultralytics YOLO11n oriented-object detector trained on DOTAv1. Its embedded metadata identifies `plane` and `helicopter` classes, a 1024x1024 input, OBB task, and AGPL-3.0 licensing. Provider-delivered `analytics_aircraft` remains a separate evidence path.

## Requirements

- **R-001 Input boundary:** accept one concrete image tile or one authenticated Satellogic COG tile request; do not silently search a scene or invoke provider analytics.
- **R-002 L1D boundary:** the Image Mate path and skill default to the Satellogic `l1d-sr` collection and a visual/full-resolution asset.
- **R-003 Local runtime:** run ONNX inference in the Image Mate Python environment, prefer CoreML on Apple Silicon or CUDA on NVIDIA when the installed ONNX Runtime exposes the provider, and fail honestly when no runtime/model is available.
- **R-004 High-resolution handling:** support a tile larger than the model input by overlapping inference windows and merge detections deterministically.
- **R-005 Normalized output:** return confidence, class, axis-aligned and oriented pixel geometry, source dimensions, model/runtime metadata, and warnings.
- **R-006 Geospatial provenance:** when tile bounds or WebMercator z/x/y are supplied, map pixel geometry to WGS84 GeoJSON; otherwise return pixel-only detections with an explicit warning.
- **R-007 API:** expose a dedicated route independent of provider analytics summary routes.
- **R-008 UI:** allow the user to run the detector on the active L1D detail tile, show status/results, and render georeferenced detections on the map.
- **R-009 Skill:** expose a repeatable local CLI/API workflow for a passed image tile and preserve the output artifact path.
- **R-010 Safety:** bound image size, tile dimensions, inference windows, detections, and execution time; never persist credentials or signed URLs in results.
- **R-011 Verification:** test parser, window projection, WebMercator bounds, missing provenance, runtime-unavailable behavior, API validation, and one real CPU inference when the optional ONNX Runtime package is installed. CUDA readiness is separately reported and must not be inferred from model-file presence.

## Design confirmation report

### Confirmed assumptions

- Image Mate is a FastAPI backend with `backend/app/main.py`, Pydantic request models, a vanilla JavaScript/Leaflet frontend, and existing L1D-SR COG tile proxying.
- The current frontend already resolves concrete Satellogic COG sources and renders detail tiles through `/api/raster/cog/tiles/{z}/{x}/{y}`.
- The repository already tracks `yolo11n-obb.onnx` and `yolo11n-obb.pt`; the ONNX metadata was inspected without loading credentials.
- `pyproj`, Pillow, and NumPy are already backend dependencies. ONNX Runtime is optional at application import time and is loaded lazily by the detector.
- The existing QGIS vessel runner contains useful ONNX/letterbox/OBB parsing patterns but cannot be imported as a web-backend service because it is a plugin-specific implementation seam.

### Mismatches and adaptations

- The existing Analytics tab summarizes remote `analytics_*` GeoJSON. It does not run local inference, so the detector uses a new direct route rather than reusing that summary endpoint.
- The existing detail tile UI normally requests 256/512-pixel tiles with a buffer. Detector requests use an explicit buffer-free high-resolution scale so pixel-to-tile bounds remain exact.
- The tracked model is DOTA-domain OBB detection, not a model fine-tuned on Satellogic L1D-SR. Results are therefore model evidence and require threshold/visual review; no accuracy claim is made without labeled L1D validation data.
- GPU execution cannot be proven in the current container because CUDA/`nvidia-smi` is unavailable. The implementation reports the actual ONNX Runtime providers at runtime and keeps CPU fallback explicit.

### Missing considerations recorded

- A production-quality detector still needs a labeled L1D-SR aircraft validation set, calibration, and possibly fine-tuning or a permissively licensed alternative before operational use.
- The current model metadata carries AGPL-3.0 licensing; deployment/distribution obligations must be reviewed before external distribution or hosted use.
- Browser automation cannot verify the private localhost UI in this environment; API and JavaScript checks remain the primary local verification until a host-exposed URL is available.

## Implementation plan

1. Add a backend detector service with lazy ONNX Runtime loading, model metadata handling, sliding-window inference, OBB parsing, NMS, and WGS84 projection helpers.
2. Add settings and request/response schemas, a dedicated `POST /api/detectors/aircraft` route, and safe runtime capability reporting.
3. Add focused unit/API tests and a CLI wrapper for direct local tile inference.
4. Add the Web App control, active L1D tile selection, request handling, GeoJSON rendering, and clear missing-runtime/error states.
5. Add a user-local Hermes skill that calls the CLI or verified API and preserves the JSON/GeoJSON artifact.
6. Run the repository verification ladder and update `docs/implementation/status.md` with exact evidence and remaining limitations.

## Acceptance criteria

- A base64 tile with bounds returns detections plus a GeoJSON `FeatureCollection` whose geometry is inside the supplied bounds.
- A COG z/x/y request uses the existing authenticated COG tile service, not a raw browser URL or remote analytics asset.
- No-bounds input returns pixel detections and an explicit `missing_georeferencing` warning.
- Runtime/model absence returns a safe, actionable 503/CLI error without a fake empty result.
- The UI runs only against an active L1D-SR visual tile, shows the selected tile/model/provider, and renders returned detections.
- CPU inference on a known image fixture completes when ONNX Runtime CPU is installed; GPU provider availability is reported separately.
- Existing tests and unrelated dirty work remain intact.
