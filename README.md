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
- Workflow builder/workbench UX for orchestration and report runs
- Map-driven AOI search (draw rectangle on map) with parameterized filters:
  - date range
  - cloud cover
  - satellite name
  - GSD min/max

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

Luna evaluations are append-only review evidence in `luna_evaluations.jsonl`; they never overwrite the human label or silently become training data. The Model Lab tab exposes the same active archive carousel, local detector, review actions, polygon annotation, model catalog, and prepared-bundle status. The `--validation-manifest` option on `train_aircraft.py` creates a scene-held-out validation split; run that command from the macOS host with `--device mps`, not from the Hermes Docker runtime.

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
