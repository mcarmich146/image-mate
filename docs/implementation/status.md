# image-mate + Satellogic Web Integration — Implementation Status

## Goal

Provide a browser-served image-mate application for Satellogic archive/tasking and Sentinel-2 browse, while preserving safe tasking confirmation, read-only planning, lifecycle verification, and the project `.env` credential boundary.

## Current phase

Local release candidate verified against the backend test suite, syntax checks, and a strengthened live local HTTP smoke test. The browser adapter rejected the private `127.0.0.1` URL before navigation, so browser rendering/console verification remains explicitly unverified. No new live Satellogic tasking order, cancellation, opportunity analysis, archive download, or analytics download was executed by this detector work; the Bamako run consumed a visual GeoTIFF downloaded previously.

## Design confirmation

### Confirmed assumptions

- image-mate already has a FastAPI backend, Leaflet SPA, `SatellogicClient`, `SourceManager`, and SQLite monitoring persistence.
- The v3 grid package's geometry/planning/status modules can be reused without embedding its standalone SQLAlchemy/Jinja application.
- Tasking writes must remain explicit and verifiable; grid cells are individual GeoJSON `Feature` orders.
- Archive footprints, order state, captures, and deliverables are separate evidence streams.

### Mismatches corrected

- The previous status said grid planning and public routes were not wired; current code exposes and tests `/api/tasking/grid/plan`, plan list/detail, and confirmed grid submission.
- The previous status said cancellation and opportunity flow were absent; current code exposes confirmation-gated cancellation and read-only asynchronous opportunity-analysis routes, with mocked regression coverage.
- FastAPI `on_event` lifecycle hooks produced deprecation warnings; the app now uses a lifespan context.
- The old monitoring refresh reported linked orders as permanently unverified; refresh now checks the linked order lifecycle when configured and keeps tasking, capture, and deliverable statuses separate.

### Remaining architectural boundary

The deeper copied grid campaign services still reference the standalone package's ORM and client modules. They are intentionally not used by the public image-mate API. The verified public adapter is the pure geometry/planning/status layer plus `GridPlanStore`, `SatellogicClient`, and FastAPI routes. Persistent campaign synchronization, retask, extension, and remaining-AOI actions require a separate adapter increment before exposure.

## Completed implementation

### Backend

- Satellogic and Sentinel-2 source management through `SourceManager`.
- Read-only individual tasking preview with geometry/SKU validation.
- Typed individual order confirmation, exact-name/product/geometry verification, and ambiguous timeout/5xx reconciliation without blind replay.
- Read-only opportunity analysis create/status routes:
  - `POST /api/tasking/opportunities`
  - `GET /api/tasking/opportunities/{analysis_id}`
- Confirmation-gated cancellation route:
  - `POST /api/tasking/orders/{order_id}/cancel`
  - Follow-up GET status verification; `requested` is distinct from `verified`.
- Order lifecycle inspection across order, events, captures, and deliverables.
- Grid plan persistence and read-only planning with per-cell payloads.
- Confirmed per-cell grid submission with exact-name reconciliation, follow-up verification, and partial-failure reporting.
- Analytics deliverable inspection and GeoJSON category/class/confidence summaries.
- Recollection monitoring create/list/get/update/delete/refresh with outcome deduplication and signed-URL-free persistence.
- Linked monitor lifecycle enrichment with separate tasking/capture/deliverable states.
- STAC pagination and collection-aware item lookup improvements.
- Proxy host allowlist, DNS/private-address rejection, filename escaping, and asset/bundle limits.
- FastAPI lifespan startup/shutdown handling.

### Frontend

- Explore, Tasking, Grid Tasking, Analytics, and Monitoring tabs.
- Grid viewport planning and exact campaign confirmation.
- Opportunity feasibility control before task submission with bounded status polling.
- Tasking lifecycle cards and typed cancellation prompt.
- Monitoring list, refresh, linked lifecycle status cards, and separate capture status.
- HTML escaping strengthened for text and attribute contexts.

### Hermes skills

- Updated `image-mate-backend` to start/reuse the service, verify HTTP and browser UI, and return the exact browser URL without exposing credentials.
- Updated `image-mate-tasking` for opportunity analysis, cancellation, and ambiguous-write reconciliation.
- Created user-local dedicated skills:
  - `image-mate-monitoring`
  - `image-mate-analytics`
  - `image-mate-grid-tasking`

## Verification evidence

- `.venv/bin/python -m pytest -q backend/tests -o addopts=''` → **66 passed, 0 warnings**.
- `node --check frontend/app.js` → passed.
- `python3 -m compileall -q backend/app backend/tests` → passed.
- `bash -n backend/run.sh` → passed.
- `git diff --check` → passed.
- Live local HTTP checks passed for the URL, health endpoint, HTML marker, JavaScript, CSS, runtime, and sources. Browser Use rejected the private/internal URL before navigation; provider capability remains environment-dependent.

## Safety boundary

No live Satellogic order creation, cancellation, retask, extension, opportunity-analysis request, or analytics download was made by this implementation work. The Bamako detector run used the previously downloaded visual GeoTIFF; no new archive download was initiated by the detector.

## Known limitations

- Sentinel-2 search/WMTS requires the configured CDSE credentials and instance/layer settings.
- Provider API payloads, signed asset URLs, cancellation timing, and opportunity-analysis response shapes remain environment-dependent until a separate live read-only verification is authorized.
- The copied standalone campaign services remain quarantined from public routes.
- The project contains substantial pre-existing uncommitted implementation diff; no commit, push, or unrelated cleanup was performed.
- Browser automation may require a host-exposed/non-private URL; do not substitute that URL without verifying its routing and access boundary.

## Local Aircraft Detector increment

### Design confirmation

- Separate from provider-delivered `analytics_aircraft` routes.
- Uses the existing tracked `yolo11n-obb.onnx` model, whose embedded metadata identifies YOLO11n-OBB, DOTAv1 training, 1024x1024 input, `plane`/`helicopter` classes, and AGPL-3.0 licensing.
- The initial web contract accepts one base64 tile or one selected `item_id` plus explicit WebMercator `z/x/y`. For COG input, the backend resolves the L1D-SR `visual` asset server-side and requests a buffer-free tile; arbitrary browser-supplied provider URLs are rejected.
- Pixel detections are mapped to WGS84 GeoJSON only when bounds or z/x/y provenance is available. Missing provenance remains an explicit warning.

### Implemented

- `backend/app/aircraft_detector.py`: lazy ONNX Runtime service, provider selection, OBB parsing, overlapping windows, class-aware NMS, normalized pixel output, and GeoJSON projection.
- `backend/app/main.py`: `GET/POST /api/detectors/aircraft`, safe runtime capability reporting, L1D-SR validation, server-side item/visual resolution, and buffer-free COG tile acquisition.
- `backend/app/models.py` and `backend/app/config.py`: request validation and detector/runtime settings.
- `frontend/index.html` and `frontend/app.js`: separate Local Aircraft Detection panel, runtime readiness, active L1D tile selection, inference request, result JSON, and Leaflet GeoJSON overlay.
- `backend/scripts/detect_aircraft.py`: direct local CLI for one saved tile.
- `backend/requirements-aircraft-cpu.txt` and `backend/requirements-aircraft-gpu.txt`: mutually exclusive runtime guidance.
- User-local Hermes skill: `image-mate-local-aircraft-detection`.

### Verification evidence

- `./.venv/bin/python -m pytest -q backend/tests -o addopts=''`: **66 passed**.
- `./.venv/bin/python -m pytest -q backend/tests/test_aircraft_detection.py -o addopts=''`: **10 passed**.
- `node --check frontend/app.js`: passed.
- `./.venv/bin/python -m compileall -q backend/app backend/tests backend/scripts`: passed.
- `git diff --check`: passed.
- Installed CPU `onnxruntime 1.28.0`; available providers were `AzureExecutionProvider` and `CPUExecutionProvider`.
- Real CLI inference on `qgis_plugin/test/_artifacts/telluric_replay/collection_012712_z14_x2585_y5613.png` completed with the tracked model, CPU provider, 512x512 input, and **0 detections**; this fixture is not an aircraft-positive control.
- Real live API smoke test: `/api/health` 200, `/api/detectors/aircraft` 200, `/api/runtime` 200, `/` 200; base64 detector POST returned 200 with CPU provider, zero detections, no signed URL in the response.
- Explicit `--provider cuda` failed closed with `CUDAExecutionProvider is not available in this ONNX Runtime installation`; GPU readiness is not verified in this container.

### Known limitations

- No labeled Satellogic L1D-SR aircraft validation set or fine-tuning has been performed; detection quality is unverified for this domain.
- The current container has no CUDA or CoreML execution provider. The target laptop host must expose `CoreMLExecutionProvider` on Apple Silicon, or the target GPU machine must install compatible CUDA/cuDNN libraries and `onnxruntime-gpu`.
- The UI uses a synchronous first slice; a long-running GPU job queue/persistence layer is deferred.
- Browser automation against private localhost remains unverified; API and JavaScript checks passed.
- The repository had substantial pre-existing uncommitted changes; no reset, commit, push, tasking write, or provider order operation was performed.

## Bamako-Sénou L1D-SR aircraft run

- Source: Satellogic `L1D_SR`, scene `20260604_155525_086_SN40_L1D_SR_MS_355069`, deliverable `deliv.10504203-021b-410f-ab34-276f7e8090d5`.
- Imagery: nominal provider-reported 0.5 m GSD (source pixel scale ~0.597 m), 1.21% catalog cloud coverage, 24.741° off-nadir; downloaded visual GeoTIFF cropped to a 3,349×3,350 high-resolution PNG over Bamako-Sénou Airport.
- Bounds: `[-7.957749366760378, 12.526559065777663, -7.939783930778628, 12.544101484603676]` WGS84.
- Local inference: 16 overlapping 1,024-pixel windows, confidence 0.25, IoU 0.45; **65 detections**: 61 `plane`, 4 `helicopter`; confidence range 0.252805–0.909156.
- Visual review: high-confidence boxes align with multiple visible aircraft on the terminal and lower apron. Dense building/vehicle clusters contain likely false positives or duplicates; the result is not ground truth.
- Provider used: `CPUExecutionProvider`. CUDA and CoreML were unavailable in the Hermes Docker runtime; CoreML provider selection was added for host-side Apple Silicon verification.
- Result JSON: `/Users/mark/.hermes/artifacts/site-intel-agent/russia-sahel-pilot/aircraft-detector/bamako-senou-l1d-obb-cpu.json`.
- Overlay PNG: `/Users/mark/.hermes/artifacts/site-intel-agent/russia-sahel-pilot/aircraft-detector/bamako-senou-l1d-obb-cpu-overlay.png`.
- Run manifest: `/Users/mark/.hermes/artifacts/site-intel-agent/russia-sahel-pilot/aircraft-detector/bamako-senou-l1d-aircraft-run-manifest.json`.

## Aircraft active-learning review increment

### Design confirmation

- The review/fine-tuning workflow is restricted to Satellogic `l1d-sr` / L1D-SR products. QuickView, Sentinel-2, provider analytics, and unreferenced images are not accepted.
- Review manifests require an item ID and valid WGS84 bounds, and preserve `EPSG:4326` plus the top-left pixel-coordinate convention so detections and labels remain map-aligned.
- Telegram is the first transport: `1=plane`, `2=helicopter`, `3=background/no detection`, `0=unsure/skip`.
- The workflow reviews low-threshold detector candidates first, then generates an overlapping grid for missed-object discovery.

### Implemented

- `backend/app/aircraft_review.py`: class-agnostic review deduplication, candidate-centered clean chips, marked review chips, L1D-SR/georeferencing validation, append-only labels, YOLO-OBB/classifier export, and full-image discovery grid generation.
- `backend/scripts/aircraft_review.py`: `prepare`, `next`, `label`, `export`, `grid`, and `status` commands for Hermes/Telegram orchestration.
- `backend/tests/test_aircraft_review.py`: seven unit tests covering cross-class duplicate merging, edge geometry, chip/manifest creation, marked review chips, L1D-SR rejection, label idempotency/conflicts, export, and overlapping grid coverage.
- Design record: `docs/implementation/aircraft-active-learning-design.md`.

### Verification evidence

- Targeted review suite: `./.venv/bin/python -m pytest -q backend/tests/test_aircraft_review.py -o addopts=''` → **7 passed**.
- Targeted detector + review suite: `./.venv/bin/python -m pytest -q backend/tests/test_aircraft_review.py backend/tests/test_aircraft_detection.py -o addopts=''` → **17 passed**.
- Full backend suite: `./.venv/bin/python -m pytest -q backend/tests -o addopts=''` → **75 passed**.
- Real Bamako low-threshold CPU inference at confidence `0.05` → **127 raw detections** (120 planes, 7 helicopters).
- Candidate preparation → **121 deduplicated review chips**, each with a clean training chip and marked review chip.
- Full-image discovery grid → **81 overlapping 512-pixel cells** with stride 384.
- The current Docker runtime still exposes only `AzureExecutionProvider` and `CPUExecutionProvider`; no GPU claim is made.

### Known limitations

- Candidate labels alone can improve filtering/subclassification but cannot create detector boxes for aircraft absent from all proposals. Grid positives need a later box-annotation step or a classifier/reranker path.
- No fine-tuning has been run yet; a scene-separated labeled set is required before changing the production model.

### Training bundle and host fine-tune

- Human-corrected helicopter review: **9 helicopters, 1 plane**.
- Combined labeled bundle: **15 plane boxes, 10 helicopter boxes**, all from the Bamako L1D-SR scene.
- Bundle path: `/Users/mark/.hermes/artifacts/site-intel-agent/russia-sahel-pilot/active-learning/bamako-20260815/training/l1d-finetune-experimental/`.
- Training entry point: `backend/scripts/train_aircraft.py`.
- Host-only requirements: `backend/requirements-aircraft-training.txt`.
- The bundle is explicitly experimental: one scene, no background negatives, and too few examples for a generalization claim.
- The actual training command was attempted and stopped before model mutation because this runtime has neither Ultralytics nor PyTorch/MPS/CUDA. The baseline `yolo11n-obb.pt` and `yolo11n-obb.onnx` were not overwritten.

Host-side command, after installing the host-only training requirements in a macOS Python environment with MPS:

```bash
cd /Users/mark/.hermes/projects/image-mate
python backend/scripts/train_aircraft.py \\
  --manifest /Users/mark/.hermes/artifacts/site-intel-agent/russia-sahel-pilot/active-learning/bamako-20260815/candidates/review_manifest.json \\
  --manifest /Users/mark/.hermes/artifacts/site-intel-agent/russia-sahel-pilot/active-learning/bamako-20260815/helicopter-search/review/review_manifest.json \\
  --outdir /Users/mark/.hermes/artifacts/site-intel-agent/russia-sahel-pilot/active-learning/bamako-20260815/training/l1d-finetune-experimental-run \\
  --device mps --epochs 10 --imgsz 1024 --batch 1 --workers 0 \\
  --allow-single-scene --export-onnx
```

## Next recommended action

Add background/hard-negative labels and at least one additional L1D-SR scene before treating any fine-tuned checkpoint as production-ready. The prepared host command may be run as an explicitly experimental Bamako-only update once the macOS MPS environment is available.
