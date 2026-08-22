# image-mate

`image-mate` is a new private-ready geospatial platform built from `spotlite` + `spotlite-example`, updated for Satellogic API v2 and focused on the STAC `l1d-sr` collection with `visual` assets.

## What it includes

- Updated `spotlite` auth flow (OAuth token + contract header support)
- Archive search for small AOIs (e.g., air bases)
- Contract discovery from account (`/contracts`) with UI dropdown selection
- Tasking workflow support (products/projects/orders + order detail lookup)
- Stack discovery and time-series playback
- GIF animation builder from STAC previews
- Before/after image comparison slider
- Annotation capture and local persistence
- AI GeoAgent report generation (latest frame + historical context + user prompt)
- Five-workspace analyst shell: Explore, Tasking, Monitor, Analyze, and Mosaic
- Analysis Recipes, durable Monitoring Projects, alerts, proposed actions, and Mosaic Projects
- Workflow builder/workbench UX for orchestration and report runs in the top-right Tools drawer
- Standalone HTML user manual at `/manual.html`, available from Tools
- Durable polygon archive watches with deduplicated email alerts and identity-based preview links
- Map-driven AOI search (draw rectangle on map) with parameterized filters:
  - date range
  - cloud cover
  - satellite name
  - NewSat Mark IV / Mark V generation
- GSD min/max

## Analyst workflow APIs

The new analyst-facing persistence layer is available through the versioned local API:

- `GET/POST/PATCH /api/analysis/recipes`
- `GET/POST/PATCH /api/monitoring/projects`
- `GET /api/monitoring/projects/{id}/alerts`
- `GET /api/monitoring/projects/{id}/activity`
- `POST /api/alerts/{id}/disposition`
- `GET /api/proposed-actions`
- `POST /api/proposed-actions/{id}/approve` and `/reject`
- `GET/POST/PATCH /api/mosaics/projects`

Existing archive-watch, recollection-monitor, schedule, workflow, run, tasking, and mosaic-job routes remain available during migration. Provider-signed URLs are not persisted; integrations use item-identity proxy routes.

## Repo hygiene

- `.env` is ignored in `.gitignore`
- `.env-template` is included and sanitized for commit

## Quick start

1. Create `.env` from template:

```bash
cp .env-template .env
```

2. Fill `.env` with real credentials:

- `SATELLOGIC_AUTH_MODE` (default `oauth_client_credentials`)
- `SATELLOGIC_KEY_ID`
- `SATELLOGIC_KEY_SECRET`
- `SATELLOGIC_CONTRACT_ID`
- Optional if using bearer mode:
  - `SATELLOGIC_BEARER_TOKEN`
- Optional for Merlin Sentinel-2 source:
  - `MERLIN_S2_ENABLED=true`
  - `CDSE_CLIENT_ID`
  - `CDSE_CLIENT_SECRET`
  - Optional for step-2 product/asset extraction on OData-style URLs:
    - `CDSE_DOWNLOAD_CLIENT_ID` (default `cdse-public`)
    - `CDSE_DOWNLOAD_USERNAME`
    - `CDSE_DOWNLOAD_PASSWORD`
    - `CDSE_DOWNLOAD_TOTP` (only if your CDSE account enforces TOTP)
- `OPENAI_API_KEY` (for GeoAgent)
- `.env-template` now contains the minimum required keys; optional advanced overrides are documented in `backend/app/config.py`.

### Copernicus/CDSE setup (step-by-step)

Use this if you want Sentinel-2 browse (WMTS) and Sentinel STAC search in image-mate.

1. Create/sign in to your CDSE account:
- Go to `https://shapps.dataspace.copernicus.eu/`.

2. Create a Sentinel Hub configuration instance:
- Open `Configuration Utility`.
- Click `New configuration`.
- Give it a name (for example `wmts`) and save.
- In the left settings panel, keep `Disable OGC requests` turned OFF.
- Optional: turn `Show logo` OFF to avoid watermark overlays on tiles.

3. Add WMTS layers in that instance:
- In the layer list, add at least one natural color layer (for example `Natural color (true color)` with layer ID `NATURAL-COLOR`).
- Optional: add analytic styles like `NDVI` and `FALSE-COLOR`.
- Save after adding/updating layers.

4. Copy the WMTS Instance ID:
- In the same configuration page, look at `Service endpoints`.
- Keep endpoint type set to `ID`.
- Copy the long UUID-like value.
- Set `.env`:
  - `CDSE_WMTS_INSTANCE_ID=<that ID>`

5. Pick the default WMTS layer ID:
- In the layers table, copy the `Id` value of the layer you want as default.
- Set `.env`:
  - `CDSE_WMTS_LAYER_ID=<your configured layer id>` (template default is `TRUE-COLOR`)

6. Create OAuth client credentials (for Catalog/Process APIs):
- In CDSE dashboard, create an OAuth client/application and generate client credentials.
- Set `.env`:
  - `CDSE_CLIENT_ID=<oauth client id>`
  - `CDSE_CLIENT_SECRET=<oauth client secret>`

7. Configure download credentials (for full-resolution Sentinel asset extraction):
- Keep `CDSE_DOWNLOAD_CLIENT_ID=cdse-public` unless you were explicitly given a different download client.
- Set your CDSE account login for ZIPPER/OData download endpoints:
  - `CDSE_DOWNLOAD_USERNAME=<your CDSE username/email>`
  - `CDSE_DOWNLOAD_PASSWORD=<your CDSE password>`
- If your account enforces TOTP, also set:
  - `CDSE_DOWNLOAD_TOTP=<current otp code>`

8. Verify from image-mate:
- Start backend and open:
  - `GET /api/layers/sentinel/wmts`
- Confirm response includes:
  - `available: true`
  - your expected `instance_id`
  - your expected `layer_id`
  - `available_layers` containing your configured styles.

9. Final `.env` checklist for Sentinel:
- `MERLIN_S2_ENABLED=true`
- `CDSE_CLIENT_ID`
- `CDSE_CLIENT_SECRET`
- `CDSE_DOWNLOAD_CLIENT_ID`
- `CDSE_DOWNLOAD_USERNAME`
- `CDSE_DOWNLOAD_PASSWORD`
- `CDSE_WMTS_INSTANCE_ID`
- `CDSE_WMTS_LAYER_ID`

10. Common setup issues:
- Duplicate keys in `.env` (for example two `CDSE_WMTS_INSTANCE_ID` lines): only the last one is used.
- `Disable OGC requests` enabled in CDSE config: WMTS calls fail.
- Wrong layer ID casing: layer IDs are exact (`TRUE-COLOR` is not the same as `true-color`).
- Missing download credentials: thumbnails may work but full-resolution asset fetches can fail with `401/403`.

3. Setup Python 3.12 environment (from workspace root):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r image-mate/backend/requirements.txt
```

4. Run backend:

```bash
cd image-mate/backend
./run.sh
```

Persistent logs are written per run to:

- `backend/output/logs/backend_YYYYMMDD_HHMMSS.log`
- `backend/output/logs/backend_latest.log` (symlink to the most recent run)

5. Open UI:

- http://localhost:8000/

For a stable browser session, use `IMAGE_MATE_DEV_RELOAD=false` when starting `backend/run.sh`. The user-local Hermes skill `image-mate-backend` can start or reuse the service, verify `/api/health`, `/`, `/api/runtime`, and `/api/sources`, run a browser smoke check, and return the verified URL without printing credentials.

## Local L1D-SR aircraft detection

Image Mate has a separate local-inference path for one high-resolution Satellogic `l1d-sr` visual tile. It does **not** call or summarize provider-delivered `analytics_aircraft`. The initial model is the tracked `yolo11n-obb.onnx` Ultralytics YOLO11n oriented detector trained on DOTAv1; its classes include `plane` and `helicopter`. The model metadata identifies an AGPL-3.0 license, so review that license before external distribution or hosted deployment.

The API resolves the selected `item_id` server-side, obtains its provider `visual` asset, requests one buffer-free WebMercator tile, and returns pixel detections plus WGS84 GeoJSON when tile provenance is available:

```text
GET  /api/detectors/aircraft
POST /api/detectors/aircraft
```

The Web App exposes this as **Analytics → Aircraft Detector**. The control is separate from provider analytics, requires an active Satellogic L1D-SR visual frame, and reports the exact tile `z/x/y`, scale, and `buffer=0` used for inference.

### Runtime setup

The base backend requirements include CPU `onnxruntime` for local verification. For NVIDIA CUDA inference, install the mutually exclusive GPU package in the project environment:

```bash
./.venv/bin/python -m pip uninstall -y onnxruntime
./.venv/bin/python -m pip install -r backend/requirements-aircraft-gpu.txt
```

On an Apple Silicon host, use a macOS ONNX Runtime build that exposes `CoreMLExecutionProvider`; the Linux Docker execution environment used by Hermes cannot access the laptop's Metal/CoreML device. Verify the actual host provider list:

```bash
./.venv/bin/python -c 'import onnxruntime as ort; print(ort.get_available_providers())'
```

Set `IMAGE_MATE_AIRCRAFT_PROVIDER=coreml` to require Apple CoreML, `cuda` to require NVIDIA CUDA, or leave it as `auto` to prefer CoreML, then CUDA, and otherwise CPU. The backend `/api/detectors/aircraft` capability endpoint reports the installed providers; the presence of an ONNX file alone is not GPU verification.

For a passed local tile, the Hermes skill/CLI uses:

```bash
./.venv/bin/python backend/scripts/detect_aircraft.py \\
  --image /path/to/l1d_tile.png \\
  --bounds=-122.5,37.6,-122.4,37.7 \\
  --provider auto \\
  --output /path/to/detections.json
```

Results are model evidence and still require validation against labeled L1D-SR aircraft imagery before operational or identity claims.

## Mosaic Workbench

The Explore carousel now uses one checkbox per archive image. Selecting cards only focuses them; checking cards adds them to the mosaic source stack. Select two or more overlapping NewSat visual images, choose **Mosaic**, then choose:

- **Mosaic whole strips** to use the connected union of the selected footprints.
- **Draw polygon for mosaic** to limit the first pass to a small AOI.

The backend performs a preflight before creating a job. It rejects disconnected selections, invalid AOIs, and output sizes above the configured pixel budget. QuickView can be used to discover and select captures, but it is never used as a mosaic raster. Every source is resolved to L1D-SR Visual tiles using its capture outcome ID. NewSat generation is preserved as explicit metadata; it is never guessed from GSD alone. The current nominal profiles are Mark IV: 0.7 m L1D-SR and Mark V: 0.5 m L1D-SR.

If a selected capture does not yet have complete L1D-SR coverage, the project is saved as **Awaiting L1D-SR Request**. The UI asks for confirmation before creating one Satellogic `ARCIMG-M.NN.NN` order per missing capture with `processing_level: L1D_SR`. After submission, the durable job enters **Awaiting L1D-SR**. A background listener checks the L1D-SR STAC collection every five minutes by default, verifies at least 99.5% AOI coverage for every capture, replaces the discovery inputs with the resulting L1D-SR tile identities, and starts the host worker automatically. Configure this with `IMAGE_MATE_MOSAIC_PRODUCT_POLL_ENABLED` and `IMAGE_MATE_MOSAIC_PRODUCT_POLL_SECONDS`.

Mosaic generation is intentionally host-side. Once all products are available, the backend starts a job-scoped macOS worker. If worker startup fails, the Mosaic Workbench exposes **Start Processing** as a retry. The worker rejects non-L1D-SR downloads, downloads source assets by item identity, optionally clips polygon jobs, and runs the existing color-balanced, cloud-aware, graph-cut/feathered GeoTIFF mosaicker:

```bash
cd /Users/mark/.hermes/projects/image-mate
./.venv/bin/python -m pip install -r backend/requirements-mosaic.txt
./.venv/bin/python backend/scripts/mosaic_worker.py \
  --api http://127.0.0.1:8000 \
  --accelerator auto \
  --once
```

Install optional Apple Silicon/CUDA support with `./.venv/bin/python -m pip install -r backend/requirements-mosaic-gpu.txt`. `auto` prefers PyTorch MPS on Apple Silicon, then CUDA, then OpenCV OpenCL, and finally CPU. GPU acceleration covers array-heavy radiometric and seam-image work; GDAL/Rasterio reprojection and GeoTIFF I/O remain host-side. The worker processes one job and exits; use the UI kickoff or run the command again for the next queued job. `GET /api/mosaics/worker/status` reports active host workers and their selected accelerator. The Mosaic Workbench exposes progress, the source stack, the output report, and identity-based artifact routes. Cloud Edit captures a polygon and persists a reversible repair request; the clear-observation selection, pixel patch, and rebalancing pass are the next worker increment.

### Luna-assisted active learning

For a series of downloaded L1D-SR tiles, keep a same-stem JSON sidecar beside each image with `item_id`, `collection_id: l1d-sr`, and `bounds_wgs84`, then run the batch lane before preparing review chips:

```bash
./.venv/bin/python backend/scripts/detect_aircraft_batch.py \
  --input-dir /path/to/l1d-tiles \
  --outdir /path/to/detections \
  --provider coreml

./.venv/bin/python backend/scripts/aircraft_review.py batch-prepare \
  --image-dir /path/to/l1d-tiles \
  --detections-dir /path/to/detections \
  --outdir /path/to/review-batch
```

Both commands preserve one manifest per scene and a batch manifest, so the review queue can be resumed or split across Telegram sessions.

The repeatable review lane can build a few-shot calibration packet from human-confirmed chips and send pending chips to the Hermes-managed `gpt-5.6-luna` vision route:

```bash
./.venv/bin/python backend/scripts/aircraft_review.py luna-prime \
  --manifest /path/to/scene-a/review_manifest.json \
  --manifest /path/to/scene-b/review_manifest.json \
  --outdir /path/to/luna-prime

./.venv/bin/python backend/scripts/aircraft_review.py luna-evaluate \
  --manifest /path/to/target/review_manifest.json \
  --prime-manifest /path/to/luna-prime/luna_examples.json
```

Luna evaluations are append-only review evidence in `luna_evaluations.jsonl`; they never overwrite the human label or silently become training data. The Model Lab tab exposes the active archive carousel, local detector, polygon/detection annotation, scene-split dataset builder, host training/evaluation jobs, model activation, and model catalog. Labels persist their source tile under `IMAGE_MATE_AIRCRAFT_LAB_DIR`; bundles are written under `IMAGE_MATE_AIRCRAFT_TRAINING_DIR`. Set `IMAGE_MATE_AIRCRAFT_TRAINING_PYTHON` to a host Python environment with `ultralytics` and PyTorch/MPS or CUDA. Evaluation is required before a newly trained ONNX model can be activated, and the active model is never overwritten automatically.

## Archive Watch alerts

The Monitoring tab can create a durable polygon watch for Satellogic or Sentinel-2. Draw a polygon with **Draw Watch Polygon**, or right-click the map and choose **Watch this area for new imagery**. The API polls the selected collection on the configured interval, deduplicates archive identities in `backend/output/monitoring.sqlite3`, and retains failed deliveries as pending items.

Configure delivery in `.env`:

```bash
IMAGE_MATE_ALERT_EMAIL_TO=analyst@example.org
IMAGE_MATE_PUBLIC_BASE_URL=http://your-host:8000
IMAGE_MATE_SMTP_HOST=smtp.example.org
IMAGE_MATE_SMTP_PORT=587
IMAGE_MATE_SMTP_USERNAME=analyst@example.org
IMAGE_MATE_SMTP_PASSWORD=...
IMAGE_MATE_SMTP_FROM=analyst@example.org
IMAGE_MATE_SMTP_USE_TLS=true
IMAGE_MATE_ARCHIVE_WATCH_ENABLED=true
IMAGE_MATE_ARCHIVE_WATCH_INTERVAL_SECONDS=300
```

`IMAGE_MATE_PUBLIC_BASE_URL` must be reachable from the email recipient’s browser. Watch messages link to `/api/archive/preview` by item identity, so provider-signed URLs and credentials are not placed in email or browser URLs. The immediate-check API is:

```text
POST /api/archive-watches/{watch_id}/check
GET  /api/archive-watches/{watch_id}/events
```

Open `/manual.html` from the running service for the operator workflow, configuration checklist, and troubleshooting guide.

## GeoAgent behavior

`/api/geoagent/report` takes:

- AOI geometry
- date range
- user prompt
- optional latest item id

The service samples historical frames, computes frame-to-frame change signals from previews, and asks an OpenAI model to produce an intelligence-style narrative report.

## Notes

- For production deployment, move annotation storage from local JSON to a database.
- If preview asset access is restricted, ensure contract + auth headers are valid.
- Monitoring/cue state now persists in SQLite at `backend/output/monitoring.sqlite3` (Postgres-ready schema planned next).
- Tasking API helper endpoints include:
  - `GET /api/tasking/orders/{order_id}` for single-order detail polling
  - resilient order list/create normalization for both `results` and `FeatureCollection` payload shapes
- Repeatable tasking workflow smoke runner:
  - `./.venv/bin/python backend/tests/tasking_smoke_runner.py --mode mock`
  - live read-only check: `./.venv/bin/python backend/tests/tasking_smoke_runner.py --mode live`
  - live create + poll: `./.venv/bin/python backend/tests/tasking_smoke_runner.py --mode live --create --project-name smoke-project`
- CDSE now prefers the newer Catalog STAC endpoint (`https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0`); older `stac.dataspace.copernicus.eu` examples in blogs may be outdated.
- For Sentinel debugging, inspect raw STAC assets for a specific item via `GET /api/archive/item-assets?item_id=<id>&source_id=merlin-s2&collection_id=sentinel-2-l2a`.
- To test direct Sentinel asset downloads into `/images`, run:
  - `./.venv/bin/python backend/scripts/download_sentinel_asset.py --item-id '<item-id>' --asset-key TCI_10m --source-id merlin-s2 --collection-id sentinel-2-l2a`
  - Full-resolution `TCI_10m` requires CDSE download credentials (`CDSE_DOWNLOAD_USERNAME` / `CDSE_DOWNLOAD_PASSWORD`), otherwise proxy calls may return `401/403`.
- Plugin platform concept draft for extensibility planning:
  - `docs/extensible-plugin-platform-concept.md`
