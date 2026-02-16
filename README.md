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
