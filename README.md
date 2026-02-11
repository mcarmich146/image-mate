# image-mate

`image-mate` is a new private-ready geospatial platform built from `spotlite` + `spotlite-example`, updated for Satellogic API v2 and focused on the STAC `l1d-sr` collection with `visual` assets.

## What it includes

- Updated `spotlite` auth flow (OAuth token + contract header support)
- Archive search for small AOIs (e.g., air bases)
- Contract discovery from account (`/contracts`) with UI dropdown selection
- Stack discovery and time-series playback
- GIF animation builder from STAC previews
- Before/after image comparison slider
- Annotation capture and local persistence
- AI GeoAgent report generation (latest frame + historical context + user prompt)
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

- `SATELLOGIC_KEY_ID`
- `SATELLOGIC_KEY_SECRET`
- `SATELLOGIC_CONTRACT_ID`
- `OPENAI_API_KEY` (for GeoAgent)

3. Setup Python 3.12 environment (from workspace root):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r image-mate/backend/requirements.txt
```

4. Run backend:

```bash
cd image-mate/backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

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
