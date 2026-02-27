# Point Target Revisit Analysis

## Summary
This document defines the functional requirements and implementation plan for the `Point Target Revisit` simulation scenario in the QGIS Simulation tab.

MVP scope is locked to:
1. Single target point.
2. Target input from map click and editable WGS84 lat/lon fields.
3. One collection event per pass.
4. Pass separation debounce of `2 * time_step_sec`.
5. Core revisit metrics only.
6. Existing Skyfield propagation stack and async worker architecture.

## Functional Requirements

### FR-1 Scenario Availability
1. The scenario selector exposes:
- `Coverage Analysis`.
- `Point Target Revisit`.
2. Default scenario remains `Coverage Analysis`.

### FR-2 Target Input
1. User provides one target point through:
- map click picker, and
- editable `lat` / `lon` fields in EPSG:4326.
2. Map click updates lat/lon fields.
3. Manual coordinate edits work without map click.

### FR-3 Validation
1. `start_utc < end_utc`.
2. `off_nadir_deg` is in `(0, 60]`.
3. At least one selected satellite has valid TLE lines.
4. Target coordinate ranges:
- `lat` in `[-90, 90]`.
- `lon` in `[-180, 180]`.
5. Guardrail blocks runs where `satellite_count * sample_count > 3_000_000`.

### FR-4 Access and Event Semantics
1. Use Skyfield propagation for each selected satellite and timestep sample.
2. For each sample:
- compute sub-satellite point and altitude,
- compute reach `reach_m = height_km * tan(off_nadir_rad) * 1000`.
3. Sample has access when `distance(target, subpoint) <= reach_m`.
4. Group access samples into passes; a new pass starts when sample gap `> 2 * time_step_sec`.
5. Each pass contributes exactly one event.
6. Event timestamp is the sample timestamp with minimum target distance in that pass.
7. Events are independent across satellites and all count.

### FR-5 Revisit Metrics
1. `total_collection_events`: count of pass-level events.
2. `first_access_utc`: earliest event timestamp, else `null`.
3. `last_access_utc`: latest event timestamp, else `null`.
4. `revisit_intervals_min`: intervals between consecutive events in sorted order.
5. `min_revisit_min`, `mean_revisit_min`, `max_revisit_min` from intervals; `null` when fewer than 2 events.
6. `longest_gap_min` over full window including boundaries:
- start to first event,
- between consecutive events,
- last event to end.
If there are no events, this equals full simulation duration in minutes.
7. Daily buckets (UTC date):
- `event_count`,
- `cumulative_event_count`.

### FR-6 UI Results Behavior
1. On completion, auto-switch to `Simulation Results` sub-tab.
2. Revisit summary shows:
- total events,
- first and last access,
- min, mean, max revisit,
- longest gap,
- target coordinates.
3. Event timeline table shows:
- event UTC,
- satellite ID,
- pass start UTC,
- pass end UTC,
- closest distance (km),
- closest off-nadir (deg).
4. Coverage-only result widgets are hidden when scenario is revisit.
5. Map renders target point layer `Image Mate Simulation - Revisit Target`.

### FR-7 Logging and Status
1. Start log includes scenario ID and target coordinates.
2. Progress updates remain sample-level and granular.
3. Completion log includes total events and key revisit stats.
4. Failure logs include actionable validation/runtime messages.

### FR-8 Non-Functional Constraints
1. No custom orbital propagator. Keep `skyfield==1.54`.
2. UI remains responsive via worker thread.
3. Coverage analysis behavior remains unchanged.

## Request Payload Schema Example

```json
{
  "scenario_id": "point_revisit_analysis",
  "selection_mode": "top_n",
  "satellite_count": 1,
  "selected_satellite_ids": [],
  "off_nadir_deg": 30.0,
  "start_utc": "2026-02-21T00:00:00Z",
  "end_utc": "2026-02-22T00:00:00Z",
  "time_step_sec": 60,
  "target_lat_deg": -34.603722,
  "target_lon_deg": -58.381592,
  "target_source": "map_click",
  "target_label": "Buenos Aires",
  "constellation_config": {
    "schema_version": 1,
    "constellation_name": "default",
    "satellites": []
  }
}
```

## Result Payload Schema Example

```json
{
  "scenario": "point_revisit_analysis",
  "start_utc": "2026-02-21T00:00:00Z",
  "end_utc": "2026-02-22T00:00:00Z",
  "satellite_count": 1,
  "target": {
    "lat": -34.603722,
    "lon": -58.381592,
    "source": "map_click",
    "label": "Buenos Aires"
  },
  "total_collection_events": 3,
  "first_access_utc": "2026-02-21T03:12:00Z",
  "last_access_utc": "2026-02-21T21:41:00Z",
  "revisit_intervals_min": [221.0, 388.0],
  "min_revisit_min": 221.0,
  "mean_revisit_min": 304.5,
  "max_revisit_min": 388.0,
  "longest_gap_min": 402.0,
  "events": [
    {
      "event_utc": "2026-02-21T03:12:00Z",
      "satellite_id": "SIM-SSO-475",
      "pass_start_utc": "2026-02-21T03:06:00Z",
      "pass_end_utc": "2026-02-21T03:16:00Z",
      "closest_distance_km": 17.3,
      "closest_off_nadir_deg": 2.1
    }
  ],
  "days": [
    {
      "date": "2026-02-21",
      "event_count": 3,
      "cumulative_event_count": 3
    }
  ]
}
```

## Implementation Plan

### Phase 1 - Requirements Artifact
1. Create this requirements document at `docs/20260220/Poin_Target_Revisit_Analysis.md`.
2. Keep payload definitions and semantics in sync with code.

### Phase 2 - UI and Interaction
1. Enable `point_revisit_analysis` scenario in Simulation Config.
2. Add target controls: lat, lon, optional label, and `Pick from Map`.
3. Add revisit result summary and event table in Simulation Results.
4. Toggle coverage vs revisit result widgets by selected scenario.

### Phase 3 - Map Click Target Picker
1. Use QGIS map tool point picker.
2. Transform clicked map coordinates to EPSG:4326.
3. Populate target fields and return map tool to previous state.
4. Exit pick mode on dock close, scenario change, and plugin unload.

### Phase 4 - Revisit Worker
1. Add `PointRevisitSimulationWorker` using Skyfield.
2. Reuse existing patterns for selection, validation, progress, and cancel.
3. Implement pass grouping and event semantics per FR-4.
4. Compute metrics and daily buckets per FR-5.

### Phase 5 - Orchestration Integration
1. Dispatch by scenario in `SimulationExecutionMixin`.
2. Route revisit payload fields to revisit worker.
3. Render revisit summary, events, and target map layer.
4. Keep coverage code path intact.

### Phase 6 - Validation and Regression
1. Smoke-test map click input, start/cancel, and deterministic event ordering.
2. Verify no-access, single-event, and multi-event metric behavior.
3. Confirm coverage scenario outputs and map layers remain unchanged.
