# Simulation Tab Implementation Plan (Coverage MVP)

## Objective
Implement the Simulation tab for coverage analysis in the QGIS plugin, aligned with the approved design in `qgis_plugin/docs/simulation-tab-coverage-analysis-design.md`.

## Locked Semantics
- A pass is counted as a collection when pass footprint intersects AOI.
- Per-pass imaged area is `intersection(pass_footprint, AOI)`.
- `total_unique_area_covered` is the union area of all pass-imaged AOI geometries.
- `total_area_imaged` is the sum of all per-pass imaged areas (overlap counted repeatedly).
- No duty-cycle or `km2/min` rate model in MVP.

## Scope (MVP)
In scope:
- Constellation config management (TLE CRUD + import/export).
- AOI source support for current extent and selected polygon layer.
- Coverage simulation worker with per-day outputs.
- Day navigation and metric reporting in UI.
- Basic map layer visualization for daily and cumulative outputs.

Out of scope:
- Point-target revisit scenario.
- Advanced attitude/slew constraints.
- Throughput throttling models.

## Technical Approach
- Keep simulation local to plugin (no backend API dependency).
- Follow existing plugin async pattern (`QThread` + QObject worker signals).
- Use equal-area CRS for area metrics (`EPSG:6933`).
- Compute pass geometry from TLE propagation + off-nadir reach envelopes.

## Work Breakdown

## Phase 0: Foundations and Decisions
### Tasks
1. Finalize propagation dependency strategy.
- Preferred: `sgp4` runtime dependency if available.
- Fallback: package a plugin-local vendor copy if deployment environment does not include it.

2. Define serialization contract for simulation results.
- JSON-serializable structure for summary + per-day geometries + per-pass diagnostics.

### Deliverables
- Dependency decision recorded in docs.
- Result schema frozen for UI and worker integration.

## Phase 1: Configuration and Storage
### Files
- `qgis_plugin/image_mate_qgis_plugin/services/simulation_config_service.py` (new)
- `qgis_plugin/image_mate_qgis_plugin/services/__init__.py` (update export if needed)

### Tasks
1. Implement load/save of constellation config at profile path.
2. Validate TLE shape and required fields.
3. Add import/export helpers for JSON files.
4. Add schema version handling for forward migration.

### Acceptance Criteria
- Config persists across QGIS restarts.
- Invalid config is rejected with actionable errors.
- Import/export round-trip preserves content.

## Phase 2: Simulation Engine (Core Geometry)
### Files
- `qgis_plugin/image_mate_qgis_plugin/simulation/__init__.py` (new)
- `qgis_plugin/image_mate_qgis_plugin/simulation/coverage_worker.py` (new)
- `qgis_plugin/image_mate_qgis_plugin/mixins/simulation_execution.py` (new)

### Tasks
1. Implement AOI normalization.
- Accept AOI geojson from map extent or selected polygon layer.
- Reproject AOI to EPSG:6933 for area operations.

2. Implement orbit sample loop.
- Propagate each selected satellite at fixed timestep in `[start, end]`.
- Derive sub-satellite point and approximate ground reach from off-nadir.

3. Implement pass extraction.
- Group consecutive valid access samples into pass windows.
- Build per-pass footprint as union of sampled reach circles.

4. Apply locked pass semantics.
- Count pass if footprint intersects AOI.
- Compute `pass_imaged_geom = intersection(pass_footprint, AOI)`.
- Accumulate unique and total metrics.

5. Aggregate day outputs.
- Daily imaged geometry and area.
- Daily cumulative unique/total metrics.

6. Emit worker progress + final payload.

### Acceptance Criteria
- Engine returns deterministic outputs for fixed inputs.
- Unique area is monotonic non-decreasing.
- Total area is monotonic non-decreasing and can exceed AOI area.
- If all passes overlap same AOI region, unique plateaus while total continues increasing.

## Phase 3: UI Integration (Simulation Tab)
### Files
- `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py` (update)
- `qgis_plugin/image_mate_qgis_plugin/plugin.py` (update)

### Tasks
1. Add Simulation tab UI sections.
- Config list/editor controls.
- AOI source control (extent + polygon layer).
- Scenario selector (coverage enabled, revisit disabled).
- Parameters (off-nadir, start, end, timestep).

2. Add new dock signals and event handlers.
- Start simulation.
- Cancel simulation.
- Day navigation (left/right).

3. Add simulation status + summary widgets.
- Progress state.
- Whole-period totals.
- Per-day values.

4. Wire plugin handlers to simulation mixin methods.

### Acceptance Criteria
- User can configure satellites and run simulation without leaving dock.
- Cancellation works without hanging UI.
- Day navigation updates metrics and selected day state correctly.

## Phase 4: Map Visualization
### Files
- `qgis_plugin/image_mate_qgis_plugin/mixins/simulation_execution.py` (update)
- optionally `qgis_plugin/image_mate_qgis_plugin/mixins/search_streaming.py` helpers reuse

### Tasks
1. Create/update simulation layers.
- Cumulative unique layer for selected day.
- Daily imaged layer for selected day.

2. Ensure layer lifecycle follows existing Image Mate naming/grouping conventions.

### Acceptance Criteria
- Day changes refresh rendered simulation geometries.
- Layers remain stable across repeated simulation runs.

## Phase 5: Validation, Testing, and Hardening
### Files
- `qgis_plugin/test/` (add simulation-focused tests)
- `qgis_plugin/docs/` (update operator notes)

### Tasks
1. Unit tests for config service.
2. Unit tests for geometry accumulation logic.
3. Smoke tests for start/cancel/day-navigation flow.
4. Performance test for country-scale AOI and selected satellite counts.

### Acceptance Criteria
- No unhandled exceptions in normal operator path.
- Runtime is acceptable for expected AOI sizes and constellation subset usage.

## Sequence and Milestones
1. Milestone A: Config service + schema finalized.
2. Milestone B: Engine returns JSON payload from synthetic AOI.
3. Milestone C: UI tab wired to engine with live progress.
4. Milestone D: Day visualization and summary complete.
5. Milestone E: Test pass and documentation complete.

## Risks and Mitigations
- Risk: TLE propagation dependency missing in deployment runtime.
- Mitigation: decide early on packaging strategy and smoke-test in target QGIS environment.

- Risk: geometry unions are slow for very dense sampling.
- Mitigation: simplify geometries during accumulation and use bounded timestep defaults.

- Risk: invalid AOI polygon layers.
- Mitigation: validate geometry upfront and provide clear UI error messages.

## Implementation Readiness Checklist
- Design doc approved.
- Dependency strategy approved.
- Result schema approved.
- AOI source behavior approved.
- Metrics semantics approved.
