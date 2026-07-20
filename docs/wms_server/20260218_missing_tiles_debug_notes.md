# 2026-02-18 L1D SR Missing Tiles / Gap Debug Notes

## Scope
This document records the end-to-end debugging and optimization work for the QGIS local tile proxy path that was showing:

- missing first/last row or column,
- occasional mid-tile gaps,
- very high latency and repeated WMS retry timeouts.

It is written so future developers can quickly reconstruct what happened, why certain tradeoffs were made, and how to continue tuning safely.

---

## Environment / Context

- Repo: `image-mate`
- Main code paths:
  - `qgis_plugin/image_mate_qgis_plugin/plugin.py`
  - `qgis_plugin/image_mate_qgis_plugin/services/local_tile_proxy.py`
  - `qgis_plugin/image_mate_qgis_plugin/services/source_service.py`
- Primary test outcome:
  - `435f51fd-8684-414c-be5f-b46d5a7f172d`
- Typical source count for this outcome in coverage mode:
  - 19 strip COG URLs
- Runtime used for local deterministic checks:
  - `C:\Users\jo.man_satellogic\Documents\Personal\dev\image-mate\.venv\Scripts\python.exe`

---

## Problem Statement

### Visual symptoms

- Purple/transparent seams crossing rendered imagery.
- Missing row/column on tile edges.
- In some cases, missing data in the middle of what should be covered.

### Performance symptoms

- Tile loads were very slow.
- QGIS WMS retries were frequent (`repeat tileRequest ... retry N`).
- Max-retry errors appeared while proxy requests were still in progress.

---

## Root Cause Summary

The issue was not one bug; it was a stack of behaviors:

1. `l1d-sr` coverage mode intentionally used many strips, not a single strip.
2. Upstream multi-source mosaic requests often failed for this outcome (`mosaic:403`).
3. Fallback then probed many sources serially per tile.
4. Original fallback behavior was seam-prone (first-success style); then seam-safe compositing fixed visuals but increased latency.
5. Lack of tile-footprint prefilter meant we were probing many strips that could never intersect the tile.
6. Duplicate retries were not coalesced early, so expensive work was repeated under load.

---

## Why One Tile Had Many Sources

This was expected in the current `l1d-sr` coverage strategy:

- `plugin.py` expands selected item to capture/outcome group (`_enrich_l1d_sr_capture_group`).
- In `l1d-sr`, the normal source cap is bypassed:
  - `max_sources = len(urls) if is_l1d_sr_stream else configured_max_sources`
  - debug log: `Bypassed source cap for l1d-sr coverage: using N strips`

References:

- `qgis_plugin/image_mate_qgis_plugin/plugin.py:3011`
- `qgis_plugin/image_mate_qgis_plugin/plugin.py:3019`

This gives better coverage robustness, but raises per-tile fanout unless filtered.

---

## Investigation Timeline (What Was Learned)

### Phase 1: Gap elimination

- Moved away from single-source-first fallback to compositing successful fallback layers.
- Result:
  - gaps/seams mostly resolved,
  - latency increased because many per-source probes were required.

### Phase 2: Instrumentation

Added per-tile structured perf logging and summary logs in local proxy.

Key markers added:

- `tile perf config ...`
- `tile perf zxy=...`
- `tile perf summary ...`

Fields captured:

- total / cache / mosaic / fallback / compose timing,
- source counts,
- probe counts,
- attempt/status breadcrumbs (`mosaic:403`, `budget`, `composed:N`, etc).

Reference:

- `qgis_plugin/image_mate_qgis_plugin/services/local_tile_proxy.py:383`

### Phase 3: Probe minimization (non-spatial)

Added:

- adaptive source ordering based on historical success,
- opaque early-stop while compositing,
- bounded fallback probe caps,
- probe failure cache for repeated failures,
- request coalescing for duplicate in-flight tile requests.

References:

- `_prioritize_sources_for_fallback`: `local_tile_proxy.py:1217`
- `_probe_failure_get`: `local_tile_proxy.py:1148`
- `_acquire_inflight_tile`: `local_tile_proxy.py:1095`
- coalesced response path: `local_tile_proxy.py:609`
- probe caps: `local_tile_proxy.py:325`

### Phase 4: Spatial prefilter (coverage mode)

Implemented requested strategy:

- plugin sends per-source bbox tokens (`source_bbox`) aligned to each `url`,
- proxy computes requested tile bounds (WGS84),
- proxy prefilters fallback candidate sources to only those whose bbox intersects the tile bbox (with buffer-aware padding).

Plugin references:

- `_source_bbox_token_for_item`: `plugin.py:3095`
- `_satellogic_source_bbox_tokens`: `plugin.py:3120`
- URL param injection (`source_bbox`): `plugin.py:3674`

Proxy references:

- parse `source_bbox`: `local_tile_proxy.py:471`
- bbox helpers: `local_tile_proxy.py:222`, `local_tile_proxy.py:245`, `local_tile_proxy.py:273`
- prefilter in fallback path: `local_tile_proxy.py:672`
- marker in attempts: `bbox_prefilter:X/Y`

---

## Quantitative Results

### Important test caveat

`qgis_plugin/test/wms_tester/outcome_gap_check.py` does not currently include `source_bbox` params in requests.  
So its timing is a pessimistic baseline for proxy behavior without spatial prefilter.

### Deterministic visual check (current code)

Command:

```powershell
& 'C:\Users\jo.man_satellogic\Documents\Personal\dev\image-mate\.venv\Scripts\python.exe' `
  qgis_plugin/test/wms_tester/outcome_gap_check.py `
  --outcome-id 435f51fd-8684-414c-be5f-b46d5a7f172d `
  --radius 2 --max-workers 8 --timeout-seconds 180
```

Observed:

- `Done: 25 tile(s), seam_issues=0, tiles_with_any_transparency=0`
- `Timing ms: min=2058.4 median=15443.2 max=19936.7`

Again: this script does not pass `source_bbox`.

### Spatial-prefilter validation (custom local-proxy harness with `source_bbox`)

Observed:

- `sources=19`
- `tiles=25 seam_issues=0`
- `probes_avg=1.44 probes_min=1 probes_max=4`
- `prefilter_lines=25/25`

Interpretation:

- Every tested tile used bbox prefilter.
- Probe count dropped drastically from broad fanout to near-single-source behavior.

### Stage-by-stage probe comparison (same outcome family)

- Non-spatial optimized fallback (ordering + early-stop + cap, before `source_bbox` prefilter):
  - `probes_avg=8.88 probes_min=1 probes_max=13`
  - `seam_issues=0` in 25-tile window checks
- Spatial prefilter enabled (`source_bbox`):
  - `probes_avg=1.44 probes_min=1 probes_max=4`
  - `seam_issues=0` in same 25-tile window checks

This is the key win from footprint-based filtering.

### QGIS log trend snapshots (same debugging day)

From disk logs (`%APPDATA%\QGIS\QGIS3\image_mate_logs`) using `tile perf zxy` lines:

- `image_mate_qgis_20260218T160517Z.log`:
  - `avg_total≈6850.7 ms`, `avg_probes≈9.30`
- `image_mate_qgis_20260218T170726Z.log`:
  - `avg_total≈2330.8 ms`, `avg_probes≈2.22`
- `image_mate_qgis_20260218T174352Z.log`:
  - `avg_total≈2761.9 ms`, `avg_probes≈2.72`

Exact values vary by canvas, overlap, retries, and whether requests include `source_bbox`.

### Pan overlap cache reuse test

Scenario:

- render a 5x5 tile window,
- pan by 1 tile in X (20/25 overlap).

Observed:

- Pass 1: `cache={'miss': 25}`, `pass1_ms=12079.7`
- Pass 2: `cache={'hit': 20, 'miss': 5}`, `pass2_ms=3246.7`

Interpretation:

- Not reloading from scratch for overlap areas.
- Tile cache reuse works and materially reduces pan latency.

### Duplicate request coalescing test

Scenario:

- 10 concurrent requests for same tile URL.

Observed:

- `cache_counts={'miss': 1, 'coalesced': 9}`
- `elapsed_ms=6676.9`

Interpretation:

- One leader request does expensive work.
- Followers wait and reuse result, reducing retry amplification.

---

## Current Behavior Model

When a local proxy tile request arrives:

1. Parse `url` list (+ optional aligned `source_bbox` list).
2. Canonicalize source order for cache key stability.
3. Serve cache hit if available.
4. Coalesce if same cache key is already in-flight.
5. Try upstream mosaic once.
6. If mosaic fails:
   - prefilter sources by tile bbox intersection (if bbox hints available),
   - prioritize likely-success sources,
   - probe with failure cache + probe cap + time budget,
   - composite successful layers,
   - early stop if composed tile is fully opaque.
7. Cache response and serve.

---

## Debugging Playbook for Future Incidents

### Read first

Look for these log lines:

- `tile perf config ...`
- `tile perf zxy=...`
- `tile perf summary ...`
- `served empty tile ...`
- WMS `repeat tileRequest` and `max retry`.

### Interpret markers

- `mosaic:403` repeated:
  - upstream multi-source mosaic is rejected; fallback does the work.
- `bbox_prefilter:X/Y`:
  - spatial prefilter is active; candidate sources reduced from `Y` to `X`.
- `probes=N`:
  - how many sources were actually probed for this tile.
- `opaque_stop:N`:
  - fallback stopped early once full opacity was achieved.
- `coalesced_wait:*` / `X-Proxy-Cache: coalesced`:
  - duplicate retries were successfully deduplicated.
- `probe_cap:N`:
  - hit per-tile probe cap before exhausting candidates.

### Quick parsing snippet (PowerShell)

```powershell
$dir = "$env:APPDATA\QGIS\QGIS3\image_mate_logs"
$log = Get-ChildItem $dir -Filter 'image_mate_qgis_*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Select-String -Path $log.FullName -Pattern 'tile perf config|tile perf zxy|tile perf summary|served empty tile|repeat tileRequest|max retry' |
  ForEach-Object { $_.Line }
```

---

## Known Risks / Gaps

1. `source_bbox` quality depends on item geometry/raster metadata quality.
   - Mitigation: if bbox missing/invalid, source is still allowed (safe fallback behavior).

2. Deterministic tester mismatch:
   - `outcome_gap_check.py` currently does not send `source_bbox`.
   - It validates seam correctness but not full plugin-path latency gains.

3. Upstream mosaic failures still occur (`403`) for some outcomes.
   - System now tolerates this better, but mosaic failure remains a direct latency driver.

---

## Suggested Next Steps

1. Update `qgis_plugin/test/wms_tester/outcome_gap_check.py` to optionally include `source_bbox` so test timing matches plugin path.
2. Add a user-visible mode toggle:
   - `Single strip` vs `Coverage`.
3. Persist per-source success/failure stats across plugin session restarts (optional).
4. Add periodic structured perf export (CSV/JSON) for easier trend analysis.

---

## Files Modified During This Debug Effort

- `qgis_plugin/image_mate_qgis_plugin/services/local_tile_proxy.py`
- `qgis_plugin/image_mate_qgis_plugin/plugin.py`

Notable features added:

- perf instrumentation,
- fallback compositing safety,
- adaptive probe ordering,
- opaque early-stop,
- probe failure cache,
- in-flight request coalescing,
- cache key canonicalization for source-order independence,
- tile/footprint prefilter with `source_bbox`.
