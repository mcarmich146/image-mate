# Point Target Revisit Analysis — Functional Requirements and Implementation Plan

## Summary
Define and implement a new `Point Target Revisit` simulation scenario in the existing QGIS Simulation tab, using the current Skyfield-based propagation stack and current async worker architecture.  
This MVP is locked to:
1. Single target point.
2. Target input via map click + editable lat/lon fields.
3. One collection event per pass.
4. Pass separation debounce = `2 × time_step_sec`.
5. Core revisit metrics only (no percentile pack in MVP).
6. Requirements doc location: `docs/20260220/Poin_Target_Revisit_Analysis.md`.

## Functional Requirements

### FR-1 Scenario Availability
1. The Simulation scenario selector shall expose:
- `Coverage Analysis` (existing).
- `Point Target Revisit` (new, enabled).
2. Scenario default remains `Coverage Analysis`.

### FR-2 Target Input (Point Revisit Scenario)
1. User shall provide one point target through:
- map click picker, and
- editable coordinate fields (`lat`, `lon` in WGS84).
2. Map click shall populate coordinate fields in WGS84.
3. Coordinate edits shall be accepted without requiring map click.

### FR-3 Validation
1. `start_utc < end_utc`.
2. `off_nadir_deg ∈ (0, 60]`.
3. At least one selected satellite with valid TLE.
4. Target coordinates must satisfy:
- `lat ∈ [-90, 90]`
- `lon ∈ [-180, 180]`
5. Guardrail: reject runs where `satellite_count * sample_count > 3,000,000`.

### FR-4 Access/Event Semantics (Point Revisit)
1. Use Skyfield propagation for all satellites at timestep resolution.
2. For each sample, compute sub-satellite point and altitude.
3. Compute steerable ground reach:
- `reach_m = height_km * tan(off_nadir_rad) * 1000`.
4. Sample has target access if distance(target, subpoint) `<= reach_m`.
5. Group access samples into passes using gap threshold:
- new pass if gap `> 2 * time_step_sec`.
6. Each pass contributes exactly one collection event.
7. Event timestamp = sample timestamp in pass with minimum target distance (closest approach).
8. Events from different satellites are independent and all counted.

### FR-5 Revisit Metric Definitions
1. `total_collection_events`: count of all pass-level events.
2. `first_access_utc`: earliest event timestamp, else `null`.
3. `last_access_utc`: latest event timestamp, else `null`.
4. `revisit_intervals_min`: intervals between consecutive events sorted by time.
5. `min_revisit_min`, `mean_revisit_min`, `max_revisit_min` computed from intervals; `null` if <2 events.
6. `longest_gap_min` computed over full window including boundaries:
- `start -> first_event`
- consecutive event intervals
- `last_event -> end`
- if no events, equals full simulation duration in minutes.
7. Daily buckets by UTC date:
- `event_count`
- `cumulative_event_count`.

### FR-6 UI Results Behavior
1. On completion, UI auto-switches to `Simulation Results` sub-tab (existing behavior retained).
2. Point Revisit results shall show:
- total events
- first/last access
- min/mean/max revisit
- longest gap
- selected target coordinates
3. Show event timeline list/table with:
- event UTC
- satellite ID
- pass start UTC
- pass end UTC
- closest-approach distance (km)
- closest off-nadir (deg)
4. Coverage-only widgets (day area navigation/cards) shall be hidden or disabled when scenario is Point Revisit.
5. Map shall render target point layer:
- `Image Mate Simulation - Revisit Target`.

### FR-7 Logging and Status
1. Start log must include scenario ID and target coordinates.
2. Progress updates must remain granular at sample level (existing behavior baseline).
3. Completion log must include total events and key revisit stats.
4. Failure logs must include actionable validation/runtime message.

### FR-8 Non-Functional Constraints
1. No custom orbital physics; continue using `skyfield==1.54`.
2. Keep UI responsive via background worker thread.
3. Preserve coverage scenario behavior and payload contract compatibility.

## Public API / Interface / Type Changes

### `ui/main_dock.py`
1. Scenario selector item:
- enable `Point Target Revisit` with ID `point_revisit_analysis`.
2. New signals:
- `simulation_pick_target_requested()`
3. New methods:
- `set_simulation_target_point(lat, lon, source)`
- `set_simulation_revisit_summary(payload)`
- `set_simulation_revisit_events(rows)`
- `set_simulation_result_mode(scenario_id)` (toggle coverage-vs-revisit result widgets)
4. Request payload additions for start:
- `target_lat_deg`
- `target_lon_deg`
- `target_source` (`map_click` or `manual`)
- `target_label` (optional)

### `plugin.py`
1. Connect new dock signal:
- `simulation_pick_target_requested -> handle_simulation_pick_target_request`
2. New plugin state fields:
- `_simulation_pick_tool`
- `_simulation_prev_map_tool`
- `_simulation_target_point` (lat/lon cache)
3. New handlers:
- `handle_simulation_pick_target_request()`
- `_on_simulation_canvas_point_picked(point)`
- `_stop_simulation_pick_mode()`

### `mixins/simulation_execution.py`
1. Start handler routes by scenario:
- `coverage_analysis -> CoverageSimulationWorker`
- `point_revisit_analysis -> PointRevisitSimulationWorker`
2. Point target validation and normalization (WGS84).
3. Scenario-specific result rendering methods for revisit summary/event timeline.
4. Add scenario-specific layer lifecycle for revisit target point.

### New worker
1. Add `qgis_plugin/image_mate_qgis_plugin/simulation/revisit_worker.py`.
2. Signals align with existing worker:
- `progress(int,int,str)`, `log(str,int)`, `finished(dict)`, `failed(str,str)`, `cancelled()`.
3. Result payload contract:
- `scenario`, `start_utc`, `end_utc`, `satellite_count`
- `target` `{lat, lon, source, label}`
- `total_collection_events`
- `first_access_utc`, `last_access_utc`
- `min_revisit_min`, `mean_revisit_min`, `max_revisit_min`
- `longest_gap_min`
- `events` (list of event rows)
- `days` (daily event counts + cumulative)

## Implementation Plan

### Phase 1 — Requirements Document Artifact
1. Create `docs/20260220/Poin_Target_Revisit_Analysis.md`.
2. Put the functional requirements and definitions from this spec into that file.
3. Include final payload schema examples for request/result.

### Phase 2 — UI + Interaction Foundations
1. Enable `point_revisit_analysis` in scenario combo.
2. Add target input group (lat/lon fields + `Pick from Map` button) in Simulation Config sub-tab.
3. Add Point Revisit result group + event table in Simulation Results sub-tab.
4. Add mode-switching logic to hide/show coverage vs revisit result widgets.

### Phase 3 — Map Click Target Picker
1. Implement map picker in plugin using QGIS map tool.
2. On click:
- transform canvas CRS to EPSG:4326,
- populate dock target fields,
- restore previous map tool.
3. Ensure pick mode exits on dock close, scenario change, and plugin unload.

### Phase 4 — Revisit Worker
1. Implement `PointRevisitSimulationWorker` using existing Skyfield dependency.
2. Reuse/port stable helper logic:
- datetime parsing
- satellite selection
- progress and cancellation patterns
- guardrail checks.
3. Implement event detection and pass grouping semantics exactly per FR-4.
4. Compute metrics exactly per FR-5.
5. Emit deterministic result payload and logs.

### Phase 5 — Orchestration Integration
1. Add scenario dispatch in `SimulationExecutionMixin`.
2. Feed point-target payload to revisit worker.
3. Bind revisit worker callbacks to UI summary/event rendering.
4. Preserve existing coverage path untouched.

### Phase 6 — Visualization + UX Polish
1. Render `Image Mate Simulation - Revisit Target` point layer.
2. Ensure reruns remove stale revisit layers.
3. Keep progress and status text scenario-specific and operator-readable.

### Phase 7 — Tests and Acceptance
1. Unit tests for revisit metrics:
- zero events
- one event
- multiple events
- boundary gap behavior
- debounce correctness.
2. Integration tests/manual smoke:
- map click fills coords
- start/cancel works
- completion auto-switches to results
- event table deterministic for fixed TLE/time/point.
3. Regression tests:
- coverage scenario outputs unchanged.

## Test Cases and Scenarios

1. `No Access`:
- point never reachable; `total_collection_events=0`, first/last null, longest gap = full duration.
2. `Single Event`:
- one pass reaches point; min/mean/max revisit null, longest gap computed with boundaries.
3. `Multiple Events One Satellite`:
- verify interval math and pass debounce.
4. `Multiple Satellites`:
- interleaved events sorted globally and all counted.
5. `Debounce Validation`:
- synthetic near-contiguous access samples collapse to one event per pass.
6. `Map Click Input`:
- non-WGS84 map canvas click correctly transformed to lat/lon.
7. `Guardrail`:
- dense request blocked with guidance.
8. `Cancel`:
- worker stops quickly and UI resets to idle.
9. `Coverage Regression`:
- coverage results/layers unchanged by revisit feature branch.

## Assumptions and Defaults (Explicit)
1. Document path uses repository convention: `docs/...` (not `doc/...`).
2. Filename remains as requested: `Poin_Target_Revisit_Analysis.md`.
3. Single point target only in MVP.
4. One collection event per pass.
5. Pass gap debounce = `2 * time_step_sec`.
6. Timezone and day bucketing use UTC.
7. No cloud, sun-angle, slew-rate, duty-cycle, or downlink constraints in MVP.
8. Skyfield dependency remains the only propagation engine.
