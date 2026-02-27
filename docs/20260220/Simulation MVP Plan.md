# Simulation Tab Coverage MVP Implementation Plan (Library-First, Decision-Complete)

## Summary
Implement the QGIS Simulation tab for coverage analysis using a free, existing orbit library so we do not build a custom propagator.  
This plan is aligned with your locked semantics:
1. A pass is a collection if the pass footprint intersects AOI.
2. Per-pass imaged area is `intersection(pass_footprint, AOI)`.

## Library Choice (Locked)
1. Use `skyfield==1.54` as the propagation library (MIT license), with its `EarthSatellite` API for TLE+SGP4 propagation.
2. Use Skyfield’s built-in satellite geodesy (`satellite.at(t)`, `wgs84.latlon_of()`, `wgs84.height_of()`); do not implement custom orbital physics.
3. Do not download ephemeris files in simulation flow; only use TLE propagation paths.
4. If Skyfield is missing at runtime, fail fast with a clear UI message and installation hint.

## Scope
1. In scope: constellation TLE config, satellite subset selection, AOI source (`map extent` and `selected polygon layer`), coverage simulation run/cancel, daily navigation, cumulative and daily metrics, map visualization layers.
2. Out of scope: revisit scenario, slew/attitude constraints, throughput/duty-cycle model, backend API dependency.

## Public Interfaces and Types (Exact Additions)

### `ui/main_dock.py`
1. New signals: `simulation_start_requested(dict)`, `simulation_cancel_requested()`, `simulation_prev_day_requested()`, `simulation_next_day_requested()`.
2. New UI builder: `_build_simulation_tab()`.
3. New UI methods: `set_simulation_status(text)`, `set_simulation_progress(current, total, text)`, `set_simulation_summary(payload)`, `set_simulation_day(payload)`, `set_simulation_controls_enabled(enabled)`.

### `plugin.py`
1. Connect new dock signals in `show_dock()`.
2. Add handlers: `handle_simulation_start_request(payload)`, `handle_simulation_cancel_request()`, `handle_simulation_prev_day_request()`, `handle_simulation_next_day_request()`.
3. Add state fields in `__init__`: `_simulation_worker`, `_simulation_thread`, `_simulation_running`, `_simulation_result`, `_simulation_day_index`, `_simulation_day_layer_id`, `_simulation_unique_layer_id`.

### `mixins/__init__.py`
1. Export `SimulationExecutionMixin`.
2. Update plugin inheritance to include it.

### New service: `services/simulation_config_service.py`
1. Methods: `load_config()`, `save_config(cfg)`, `validate_config(cfg)`, `import_config(path)`, `export_config(path, cfg)`.
2. Storage path: `Path(QgsApplication.qgisSettingsDirPath()) / "image_mate" / "simulation_constellation.json"`.

### New worker: `simulation/coverage_worker.py`
1. Signals: `progress(int,int,str)`, `log(str,int)`, `finished(dict)`, `failed(str,str)`, `cancelled()`.
2. Methods: `run()` and `cancel()`.

### Request payload contract (dock -> plugin)
1. Keys: `scenario_id`, `selection_mode`, `satellite_count`, `selected_satellite_ids`, `off_nadir_deg`, `start_utc`, `end_utc`, `time_step_sec`, `aoi_source`, `aoi_layer_id`.

### Result payload contract (worker -> plugin)
1. Keys: `scenario`, `start_utc`, `end_utc`, `satellite_count`, `aoi_area_km2`, `total_unique_area_km2`, `total_area_imaged_km2`, `total_collection_passes`, `days`.
2. `days` item keys: `date`, `day_imaged_km2`, `cumulative_imaged_km2`, `cumulative_unique_km2`, `collection_passes`, `day_geometry_geojson`, `cumulative_unique_geojson`.

## Geometry and Computation Algorithm (Locked)

1. Resolve AOI:
`aoi_source == map_extent` uses existing `_current_extent_geometry_wgs84()`;
`aoi_source == polygon_layer` unions all polygon features from selected layer and transforms to WGS84 GeoJSON.
2. Reproject AOI to `EPSG:6933` for area math.
3. Build Skyfield satellites from selected TLEs.
4. Generate UTC sample timeline from `start_utc` to `end_utc` inclusive, step `time_step_sec`.
5. For each satellite sample:
compute geocentric position with `sat.at(t)`;
get `lat/lon` and `height_km`;
compute ground reach `reach_m = max(0, height_km * tan(off_nadir_rad) * 1000)`;
build circle footprint around subpoint in EPSG:6933 with buffer segments `24`.
6. Mark access samples where sample footprint intersects AOI.
7. Group access samples into passes with `pass_gap_sec = 2 * time_step_sec`.
8. Per pass:
`pass_footprint = union(sample_footprints)` (simplify each footprint with tolerance `250m` before union);
`is_collection = intersects(pass_footprint, AOI)`;
if collection: `pass_imaged_geom = intersection(pass_footprint, AOI)`;
`pass_imaged_area_km2 = area(pass_imaged_geom)/1e6`;
accumulate `total_area_imaged_km2 += pass_imaged_area_km2`;
accumulate `unique_geom = union(unique_geom, pass_imaged_geom)`;
`total_unique_area_km2 = area(unique_geom)/1e6`.
9. Bucket each collection pass by UTC day of pass start for daily metrics.
10. Build `days[]` sorted by date with cumulative metrics.

## UI Behavior (Locked)
1. Simulation tab placement: after `Watch & Alerts`, before `Exploitation`.
2. AOI source controls:
`Current Map Extent` and `Selected Polygon Layer` (with refresh layer list button).
3. Scenario control:
`Coverage Analysis` enabled;
`Point Revisit` visible but disabled with “planned” label.
4. Start button validates inputs, disables editing while running, shows progress.
5. Cancel button sets worker cancel flag and restores controls.
6. Day navigation arrows move current day index and rerender two layers:
`Image Mate Simulation - Day Imaged`
`Image Mate Simulation - Cumulative Unique`.
7. Summary panel always shows:
`Total unique area covered` and `Total area imaged`.

## Validation Rules (Locked)
1. `start_utc < end_utc`.
2. `off_nadir_deg` in `(0, 60]`.
3. At least one selected satellite with valid TLE lines.
4. AOI is valid, polygonal, and non-empty after reprojection.
5. Guardrail: reject runs where `satellite_count * sample_count > 3,000,000` with message to increase timestep or shorten interval.

## Implementation Sequence

1. Add config service and JSON schema support.
Files: `services/simulation_config_service.py`.
Done when: load/save/import/export and validation work with clear errors.

2. Add worker and simulation mixin scaffolding.
Files: `simulation/coverage_worker.py`, `mixins/simulation_execution.py`, `mixins/__init__.py`.
Done when: dummy run can start/cancel/finish with payload plumbing.

3. Add Skyfield-backed propagation and pass computation.
Files: `simulation/coverage_worker.py`.
Done when: worker returns deterministic metrics and day payloads for fixed TLE/AOI/time.

4. Add Simulation tab UI and signal emission.
Files: `ui/main_dock.py`.
Done when: user can configure and submit a valid request payload.

5. Wire plugin handlers and day-navigation rendering.
Files: `plugin.py`, `mixins/simulation_execution.py`.
Done when: start/cancel/day arrows work end-to-end.

6. Add map-layer rendering for daily and cumulative outputs.
Files: `mixins/simulation_execution.py`.
Done when: day changes update map layers correctly without stale layers.

7. Add tests and docs.
Files: `qgis_plugin/test/...`, `qgis_plugin/docs/...`.
Done when: defined tests pass and operator doc is updated.

## Test Cases and Scenarios

1. Config persistence:
save config, restart plugin, verify identical satellite entries.

2. Invalid TLE:
one malformed line; start should be blocked with actionable error.

3. AOI source map extent:
small AOI, one satellite, 1-day window; run completes and outputs non-negative metrics.

4. AOI source polygon layer:
multi-feature polygon layer; AOI union works and simulation runs.

5. Saturation behavior:
repeated overlapping passes over same area; unique plateaus while total increases.

6. No-coverage case:
AOI with no intersecting passes; all metrics remain zero, no crash.

7. Cancel behavior:
cancel mid-run; worker stops and UI returns to idle state.

8. Day navigation:
left/right arrows update numbers and layer geometry deterministically.

9. Guardrail:
very dense request breaches sample threshold; run blocked with guidance.

## Acceptance Criteria
1. No custom orbital physics implementation exists in plugin code.
2. Coverage simulation uses free library propagation (Skyfield/SGP4).
3. Pass semantics exactly match locked behavior.
4. Metrics are monotonic and numerically stable.
5. UI remains responsive during run and cancel.
6. AOI extent and polygon layer both work in MVP.

## Assumptions and Defaults
1. Default scenario: `coverage_analysis`.
2. Default `off_nadir_deg`: `30.0`.
3. Default `time_step_sec`: `60`.
4. Default selection mode: `top_n` by priority with `N=1`.
5. Day bucketing uses UTC date of pass start.
6. Geometry area is computed in EPSG:6933.
7. Existing workspace changes outside simulation scope are untouched.

## Primary Sources for Library Decision
1. Skyfield docs: https://rhodesmill.org/skyfield/api-satellites.html
2. Skyfield Earth satellites usage: https://rhodesmill.org/skyfield/earth-satellites.html
3. Skyfield PyPI (MIT metadata): https://pypi.org/project/skyfield/
4. SGP4 PyPI (MIT metadata): https://pypi.org/project/sgp4/
5. Skyfield GitHub (MIT): https://github.com/skyfielders/python-skyfield
