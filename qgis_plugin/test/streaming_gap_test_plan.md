# Streaming Gap Repro Test Plan

Goal: Reproduce the L1D SR edge gap with the same URL builder used by the QGIS plugin and capture a report that shows which edge tiles return empty/404.

## Preconditions
- QGIS plugin installed and able to perform a Satellogic search.
- Valid Satellogic credentials in environment or QGIS settings.
- Optional: local tile proxy running in QGIS (default behavior).

## Step 1: Reproduce in QGIS
1) Perform a search for `l1d-sr` in the same area where the gap appears.
2) Select an item and load the streamed layer until the gap is visible.
3) Note the zoom level (or approximate) and the item id shown in the dock.
4) Close QGIS or leave it running; the log is already written to disk.

## Step 2: Extract the QGIS Log Payload
- The plugin writes logs to `%APPDATA%/QGIS/QGIS3/image_mate_logs/`.
- The `streaming_gap_probe.py` tool will auto-select the latest log unless `--log` is provided.

## Step 3: Run the Probe (Apples-to-Apples URL Builder)
### Local proxy path (matches QGIS default when multiple sources are used)
```
python qgis_plugin/test/streaming_gap_probe.py \
  --local-proxy \
  --zoom 15 \
  --item-id <ITEM_ID> \
  --use-item-geometry
```

### Backend proxy path (if QGIS falls back to backend)
```
python qgis_plugin/test/streaming_gap_probe.py \
  --stream-base http://localhost:8000 \
  --zoom 15 \
  --item-id <ITEM_ID> \
  --use-item-geometry
```

### Direct Satellogic API (only if debugging upstream behavior)
```
python qgis_plugin/test/streaming_gap_probe.py \
  --stream-base https://api.satellogic.com \
  --zoom 15 \
  --auth \
  --item-id <ITEM_ID> \
  --use-item-geometry
```

## Step 4: Inspect the Report
- The tool writes `stream_gap_report.json` by default.
- Check `results.missing` for edges with empty tiles.
- Use `tile_template` to confirm the exact URL pattern is identical to QGIS.

## Success Criteria
- The report shows empty tiles on at least one edge that matches the visible gap in QGIS.
- The tile URL template matches the QGIS-generated stream URL (same base, params, and ordering).

## Notes
- Use `--use-item-geometry` to focus on the selected item footprint instead of the search AOI.
- Increase `--max-tiles` for larger extents or to scan full edges.
- If the gap appears only at specific zooms, re-run with several zoom levels.
