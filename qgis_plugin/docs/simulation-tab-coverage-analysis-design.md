# Simulation Tab Design (Coverage Analysis Phase 1)

## Goal
Add a **Simulation** tab to the QGIS plugin to estimate constellation collection capacity over a user AOI and time window, starting with **coverage analysis**.

This design maps directly to your requested capabilities:
1. Constellation TLE configuration saved in plugin config.
2. User control for how many satellites are included.
3. Scenario selector (coverage first, revisit later).
4. User parameters (off-nadir, start/end).
5. Start simulation action.
6. Coverage computation over time.
7. Day-by-day navigation with cumulative stats.
8. Period summary totals.
9. Re-collection rule: if AOI is already fully covered, continue imaging inside AOI so capacity still contributes to total imaged area.

## Confirmed Design Decisions
These decisions are fixed for MVP:
- AOI selection in MVP supports both:
  - current map extent
  - selected polygon layer
- No duty-cycle/capture-rate throttling in MVP.
- Satellites are assumed able to keep collecting over the AOI whenever geometry allows.
- AOIs are expected to be moderate (typically up to country scale), so simplified logic is acceptable for phase 1.
- A pass counts as a collection if and only if the pass footprint intersects any part of AOI.
- Per-pass imaged area is exactly `intersection(pass_footprint, AOI)`.

## Recommended Architecture
Use a plugin-local worker pattern (same style as workflow execution):
- UI in `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
- Orchestration in a new mixin `qgis_plugin/image_mate_qgis_plugin/mixins/simulation_execution.py`
- Worker in `qgis_plugin/image_mate_qgis_plugin/simulation/coverage_worker.py`
- Config read/write service in `qgis_plugin/image_mate_qgis_plugin/services/simulation_config_service.py`

Reasoning:
- Matches existing plugin architecture (`QThread` + worker signals).
- Keeps simulation UX fully inside QGIS.
- Avoids coupling simulation UX to backend availability.

## UI Design (Simulation Tab)
Add a new tab after Monitoring and before Workflows.

### A. Configuration
- `Constellation` group:
  - Satellite list (id, name, enabled)
  - Buttons: `Add`, `Edit`, `Remove`, `Import TLE`, `Export Config`
- `Selection` group:
  - Mode: `Top N by priority` or `Manual`
  - `Satellites to include (N)` spinbox

### B. Scenario
- Scenario combo:
  - `Coverage Analysis (Phase 1)`
  - `Point Revisit Estimation (planned)` (disabled for now)

### C. Simulation Parameters
- AOI source:
  - `Current map extent` (phase 1 MVP)
  - `Selected polygon layer` (phase 1 MVP)
- `Max off-nadir (deg)`
- `Start UTC` / `End UTC`
- `Time step (sec)` advanced field (default 60)

### D. Actions + Status
- Buttons: `Start Simulation`, `Cancel`
- Status label + progress bar

### E. Results Navigation
- Day navigation row:
  - `<` previous day, day label, `>` next day
- Per-day values:
  - `Unique area covered up to day (km2)`
  - `Total area imaged up to day (km2)`
  - `Imaged today (km2)`

### F. Period Summary
- `Total unique area covered (km2)`
- `Total area imaged (km2)`

## Config File Design
Store mutable constellation config in a user-writable plugin path, not plugin install dir.

Recommended path:
- `%APPDATA%/QGIS/QGIS3/profiles/default/image_mate/simulation_constellation.json`

Schema:
```json
{
  "schema_version": 1,
  "constellation_name": "default",
  "satellites": [
    {
      "satellite_id": "SAT-001",
      "name": "SAT-001",
      "priority": 1,
      "enabled": true,
      "tle": {
        "line1": "1 ...",
        "line2": "2 ..."
      }
    }
  ]
}
```

Notes:
- TLE lines are mandatory.
- No per-satellite collection-rate fields are required in MVP.

## Coverage Analysis Computation Model
Phase 1 is intentionally approximate but operationally useful.

### 1. AOI Preparation
- Resolve AOI geometry (map extent or selected layer).
- Reproject AOI into equal-area CRS (EPSG:6933) for area math.

### 2. Orbit Propagation
For each selected satellite and each timestep in `[start, end]`:
- Propagate from TLE.
- Compute sub-satellite ground point and altitude.
- Compute ground reach from off-nadir:
  - `reach_km = altitude_km * tan(max_off_nadir_rad)` (phase 1 approximation).
- Mark an access sample when AOI is within reach.

### 3. Pass Windowing
- Merge consecutive access samples into pass windows using a max-gap threshold.

### 4. Pass Footprint Per Pass
For each pass:
- Build pass footprint as the union of sampled reach circles during the pass.
- Determine whether it is a collection pass:
  - `is_collection = intersects(pass_reach_union, AOI)`
- Only collection passes contribute metrics.
- For collection passes, clip footprint to AOI:
  - `pass_imaged_geom = intersection(pass_reach_union, AOI)`
  - `pass_imaged_area_km2 = area(pass_imaged_geom)`
- No duty-cycle or km2/min cap is applied in MVP.

Requirement #9 is satisfied by metric definition: even if a pass contributes no new unique area, its `pass_imaged_area_km2` still adds to total imaged area.

### 5. Metrics
Track:
- `total_unique_area_km2`: area of union of all pass-imaged geometries.
- `total_area_imaged_km2`: sum of per-pass imaged areas (overlap counted each time).
- Daily cumulative and daily incremental metrics for slider navigation.

## Day-by-Day Visualization
Create/update map layers on simulation completion:
- `Image Mate Sim Unique (cumulative up to D)`
- `Image Mate Sim Imaged (day D)`

Arrow navigation updates displayed day layers and labels without recomputation.

## Plugin Integration Points

### `ui/main_dock.py`
Add signals:
- `simulation_start_requested = pyqtSignal(dict)`
- `simulation_cancel_requested = pyqtSignal()`
- `simulation_day_changed = pyqtSignal(int)` (optional if day navigation handled in dock only)

Add methods:
- `_build_simulation_tab()`
- `set_simulation_status(text)`
- `set_simulation_progress(current, total, text)`
- `set_simulation_summary(summary_dict)`
- `set_simulation_day(day_payload)`

### `plugin.py`
Wire handlers in `show_dock()`:
- `handle_simulation_start_request(payload)`
- `handle_simulation_cancel_request()`

Reuse geometry helpers from `SearchStreamingMixin`:
- `_current_extent_geometry_wgs84()`
- `_geometry_from_geojson()`

### New worker/mixin
Follow workflow execution pattern:
- start worker on `QThread`
- emit progress/log/day/final
- handle cancel and cleanup safely

## Output Payload Contract
Simulation result object returned by worker:
```json
{
  "scenario": "coverage_analysis",
  "start_utc": "2026-02-01T00:00:00Z",
  "end_utc": "2026-02-07T23:59:59Z",
  "satellite_count": 4,
  "aoi_area_km2": 12345.6,
  "total_unique_area_km2": 9876.5,
  "total_area_imaged_km2": 15678.9,
  "days": [
    {
      "date": "2026-02-01",
      "day_imaged_km2": 1800.0,
      "cumulative_imaged_km2": 1800.0,
      "cumulative_unique_km2": 1700.0,
      "day_geometry_geojson": {"type": "Polygon", "coordinates": []},
      "cumulative_unique_geojson": {"type": "Polygon", "coordinates": []}
    }
  ]
}
```

## Validation Rules
- Start < End.
- At least 1 selected satellite with valid TLE.
- AOI geometry exists and is valid.
- Off-nadir in `(0, 60]` (practical default bound).

## Testing Plan
1. Config service tests:
- load/save schema, migration from missing fields.

2. Coverage engine tests:
- deterministic synthetic pass input.
- requirement #9 behavior (AOI saturated, unique stays flat while total keeps increasing).

3. UI integration tests (manual + smoke):
- start/cancel simulation.
- day navigation updates numbers and layers.
- summary totals match daily cumulative end state.

## Phase Plan
### Phase 1 (coverage MVP)
- Simulation tab UI shell + config CRUD.
- Coverage worker with pass-footprint geometry accumulation.
- Day navigation and summary reporting.

### Phase 1.1
- Export simulation result JSON/GeoPackage.

### Phase 2
- Point target revisit scenario.
- Better pointing constraints and slew/roll limits.
