# Startup Latency Diagnosis And Responsive Loading Design and Implementation Plan

- Date: 2026-07-20
- Scope: `qgis_plugin/**` only
- Status: P0 startup network decoupling and mosaicking interaction cleanup implemented
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

The QGIS plugin package initializes quickly, but the first call to
`ImageMatePlugin.show_dock()` blocks the QGIS UI thread while it constructs every tab and
loads unrelated remote and local data. Operators experience this as a 15-30 second plugin
startup even when they only need one feature.

Recent logs provide the following evidence. The logs do not record entry into `show_dock()`,
so `Plugin initialized` to `Dock opened` is an upper bound when the operator clicks later.
The recent plugin-reloader sessions below opened the dock immediately and consistently show
the reported delay:

| Log UTC | Plugin reload | Initialized to monitoring result | Monitoring result to dock open | Initialized to dock open |
| --- | ---: | ---: | ---: | ---: |
| 2026-07-21 05:47:17 | 0.350 s | 19.366 s | 2.877 s | 22.243 s |
| 2026-07-21 05:24:45 | 1.829 s | 15.104 s | 3.409 s | 18.513 s |
| 2026-07-21 03:53:22 | 0.483 s | 13.515 s | 2.882 s | 16.397 s |
| 2026-07-20 21:40:28 | 0.760 s | 12.323 s | 2.902 s | 15.225 s |

Interpretation: QGIS/plugin import is not the main problem. First-open work is. All of the
work described below executes synchronously on the GUI thread before `dock.show()` at
`plugin.py:401`.

## Current Startup Sequence

1. `ImageMatePlugin.__init__()` loads settings, creates all services, creates or scans
   campaign storage, validates and synchronizes the Asset Intel database, and starts the
   local tile proxy.
2. `initGui()` registers the action and logging. Recent reload logs show this overall phase
   normally completes in less than two seconds.
3. On first open, `show_dock()` constructs `ImageMateMainDock`.
4. `ImageMateMainDock.__init__()` eagerly constructs all ten tabs, including workflows,
   tasking, monitoring, simulation, Asset Intel, geoprocessing, and integrations.
5. `_bind_dock_data()` invokes `_on_source_changed()`.
6. `_on_source_changed()` synchronously performs unrelated refresh work:
   - STAC collection listing;
   - tasking product/order refresh;
   - local mosaic project refresh;
   - backend health check and monitoring feed refresh.
7. `show_dock()` then loads simulation state, revalidates/synchronizes Asset Intel twice,
   loads facets and initial search results, and snapshots the QGIS project layer tree.
8. The layer-tree snapshot is repeated once more before the dock is shown.

## Bottlenecks and Risk Ranking

### P0: remote requests are coupled to source binding

`SearchStreamingMixin._on_source_changed()` is a UI selection handler, but it also calls
`handle_tasking_refresh_request()` and `handle_monitoring_refresh_request()`. This makes
Collection Requests and Watch & Alerts network availability a prerequisite for opening the
entire plugin.

The request fan-out is potentially large:

- `SatellogicClient.list_collections()` performs a blocking request with a 60-second timeout.
- The first Satellogic request may also perform OAuth token acquisition with a 30-second
  timeout.
- Tasking startup requests up to 500 orders. `_collect_tasking_orders()` can follow up to six
  pages, with a 60-second timeout for each page.
- Monitoring first performs a blocking 1.5-second health check. If healthy, it then performs
  three sequential API calls, each with a default 20-second timeout.

These are worst-case timeout ceilings, not the measured duration of every run, but they show
why startup latency varies with API/network state and can greatly exceed 30 seconds.

### P1: all feature UIs and local datasets are loaded eagerly

- `ImageMateMainDock.__init__()` builds all ten tabs before the shell can be displayed.
- Asset Intel validation performs schema synchronization and commits changes. It runs once
  during plugin construction, again in `_refresh_asset_intel_data()`, and a third time when
  that method invokes the initial search handler.
- Asset Intel facets and initial search results are loaded even if the operator never opens
  that tab.
- Campaign discovery reads every campaign manifest before the dock is visible.
- The complete QGIS layer-tree snapshot is built twice during the first open.

### Not a primary bottleneck

The local tile proxy starts a loopback `ThreadingHTTPServer` and immediately moves serving to
a daemon thread. Client constructors do not acquire tokens until request methods are called.
Neither explains the consistent first-open delay in the available evidence.

## Existing Reusable Components

- QGIS already provides `QgsTask` for background work and main-thread result delivery.
- The plugin already uses `QThread`/workers for simulation and workflow execution.
- `SourceService` already owns provider access and contains a contracts cache; the same
  ownership can be extended to collection and order caches.
- Existing dock status setters can represent loading, cached, ready, and error states without
  moving business logic into the UI.
- Existing explicit refresh signals for tasking, monitoring, mosaic projects, and side-by-side
  layers are appropriate boundaries for on-demand refresh.

## Implementation Summary

Implemented on 2026-07-20:

- `SourceService.default_collections()` now supplies deterministic local collection choices
  without authentication or network access.
- `SearchStreamingMixin._on_source_changed()` uses those local choices and no longer invokes
  collection listing, tasking refresh, monitoring refresh, or mosaic project refresh.
- Tasking and monitoring API access remains available through their existing explicit Refresh
  actions.
- Mosaicking Studio now opens modelessly with `show()` instead of `exec_()`. The main Image
  Mate dock therefore remains enabled while the background mosaic task and results window are
  active.
- The Mosaicking Studio log-drain timer is stopped, scheduled for deletion, and detached on
  every terminal success/failure/submission path.
- No global cursor restoration was added. Image Mate does not set an override cursor, so
  popping Qt's application cursor stack could incorrectly remove a cursor owned by QGIS.

## Proposed Backend Changes

Create a backend-owned startup/load coordinator under `services/` that exposes independent,
cancellable load operations and immutable result payloads. The coordinator should:

1. Return static source definitions and last-known cached collections immediately.
2. Run collection refresh off the GUI thread only when Collection Search becomes active or
   the operator requests refresh.
3. Run tasking order refresh only when Collection Requests becomes active. Fetch the first
   page (for example 50 rows) first and paginate on demand instead of downloading up to 500
   orders during startup.
4. Run monitoring health/feed refresh only when Watch & Alerts becomes active. Fetch its three
   datasets concurrently where safe, with bounded timeouts and independent error results.
5. Cache successful results with fetched-at timestamps. Present stale data immediately and
   refresh in the background (stale-while-revalidate).
6. Use a request generation/token so a source switch cancels or ignores stale results.
7. Move Asset Intel schema preparation to one idempotent initialization per configured DB
   path. Load facets/results only when Asset Intel becomes active.
8. Add structured timing events for shell construction and each loader so regressions are
   attributable in terminal-readable logs.

## UI Wiring Changes (Minimal)

1. Construct and show a lightweight dock shell first, with the default Campaigns or Collection
   Search tab usable immediately.
2. Lazily construct feature tabs on first activation, or construct their visual skeletons but
   defer all data loading.
3. Replace `_on_source_changed()` with local UI-state updates plus one coordinator request for
   the active feature only. Do not refresh tasking, mosaics, or monitoring from this handler.
4. Show per-tab states such as `Not loaded`, `Loading...`, `Cached as of ...`, `Ready`, and
   `Refresh failed`; a failure in one feature must not disable or delay other tabs.
5. Keep existing Refresh buttons as explicit retry paths.

Target user experience:

- Plugin/package initialization remains under 2 seconds.
- The dock shell is painted within 500 ms of the click on a representative project.
- No network request is required before the shell is visible and interactive.
- Slow/unavailable APIs affect only the tab that consumes them.

## Implementation Steps

1. Completed: add a terminal smoke contract that rejects network calls from dock/source
   binding.
2. Completed: remove tasking, monitoring, mosaic project, and remote collection refresh calls
   from `_on_source_changed()`.
3. Completed: make Mosaicking Studio modeless and dispose its terminal log timer.
4. Deferred: add monotonic timing instrumentation around `ImageMatePlugin.__init__()`, `initGui()`,
   `show_dock()`, dock construction, each binding stage, and each external/local loader.
5. Deferred: introduce the backend load coordinator and worker/task adapter if automatic
   per-tab refresh is desired later.
6. Deferred: add collection/order/monitoring caches with timestamps and bounded retention.
7. Deferred: deduplicate Asset Intel initialization and layer-tree snapshotting.
8. Deferred: evaluate lazy tab construction after measuring the network-free startup. Keep it only if measured
   shell construction still misses the 500 ms target.

The P0 change should be delivered first because it removes network latency from the critical
path with the smallest behavioral surface. Lazy construction can follow based on measured
evidence.

## Terminal-Only Test Plan

1. `startup_no_network_smoke.py`
   - Replace provider/backend request seams with functions that fail if called.
   - Open the dock through a fake/minimal QGIS interface.
   - Assert the shell reaches its visible state and zero network seams were invoked.
2. `startup_coordinator_smoke.py`
   - Use delayed deterministic fake clients.
   - Assert the shell-ready callback precedes completion of remote loaders.
   - Assert source changes discard stale generations.
3. `startup_cache_smoke.py`
   - Seed a tiny cache fixture.
   - Assert cached data is returned immediately and a refresh is scheduled.
   - Assert an offline refresh preserves cached data and records a per-tab error.
4. `startup_asset_intel_smoke.py`
   - Use a tiny SQLite fixture.
   - Assert schema initialization runs once per DB path and no facet/search query runs before
     Asset Intel activation.
5. Log probe
   - Parse structured timing lines and fail when dock shell readiness exceeds the agreed
     budget in the deterministic harness.

## Risks and Rollback

- Risk: background workers may update destroyed widgets. Mitigation: weak ownership checks,
  cancellation on dock destruction, and generation tokens.
- Risk: cached collections/orders can be stale. Mitigation: show fetched-at time, refresh in
  the background, and keep explicit Refresh actions.
- Risk: QGIS objects are generally main-thread-bound. Mitigation: workers return plain Python
  payloads only; widget and QGIS object mutation remains on the main thread.
- Risk: tab activation can trigger duplicate work. Mitigation: coordinator single-flight keys
  per feature/source and idempotent result application.
- Rollback: retain explicit synchronous refresh handlers behind Refresh actions while removing
  only their automatic startup invocation. The coordinator wiring can be reverted per feature
  without restoring network calls to dock-open.

## Verification Evidence

1. Command: inspected `plugin.py`, `ui/main_dock.py`, `mixins/search_streaming.py`, provider
   clients, services, and recent `image_mate_qgis_*.log` files with `rg` and PowerShell.
   Expectation: identify every first-open action and correlate it with observed latency.
   Observed: all remote refreshes and repeated local loading occur before `dock.show()`;
   recent first-open sequences take 15.225-22.243 seconds while reload takes 0.350-1.829
   seconds.
   Interpretation: pass; first-open binding is the demonstrated latency source.
2. Not run: live endpoint timing. Static request timeouts and existing logs are sufficient to
   establish blocking critical-path behavior without sending authenticated requests.
3. Not run: QGIS GUI profiler. Current logs do not timestamp `show_dock()` entry or individual
   stages; implementation step 1 adds the evidence needed for exact per-stage attribution.
4. Command: `py -3 qgis_plugin/test/startup_no_api_calls_smoke.py`.
   Expectation: dock/source binding contains no collection, tasking, monitoring, backend health,
   or backend JSON API calls and uses local collection defaults.
   Observed: `startup_no_api_calls_smoke: ok`.
   Interpretation: pass.
5. Command: `py -3 qgis_plugin/test/mosaicking_studio_wiring_smoke.py`.
   Expectation: Mosaicking Studio opens modelessly and terminal paths dispose the log timer.
   Observed: `mosaicking_studio_wiring_smoke: ok`.
   Interpretation: pass.
6. Command: `py -3 qgis_plugin/test/mosaicking_service_smoke.py`.
   Expectation: backend mosaicking contracts remain intact.
   Observed: `mosaicking_service_smoke: ok`.
   Interpretation: pass.
7. Command: `py -3 -m py_compile ...` for all changed Python modules and smoke tests.
   Expectation: all changed Python sources compile.
   Observed: exit code 0 with no diagnostics.
   Interpretation: pass.
8. Command: `C:\OSGeo4W\bin\python-qgis.bat qgis_plugin/test/mosaicking_qgstask_bridge_smoke.py`.
   Expectation: the real QGIS task manager still executes the backend mosaic bridge and
   delivers its completion result.
   Observed: `mosaicking_qgstask_bridge_smoke: ok`.
   Interpretation: pass. The system `py -3` interpreter was unsuitable because it does not
   include the QGIS Python modules; rerunning through the installed QGIS interpreter passed.
9. Command: direct `SourceService.default_collections()` probe with an uninitialized manager.
   Expectation: local Satellogic and Sentinel-2 rows are returned without client calls.
   Observed: three Satellogic defaults and one `sentinel-2-l2a` default were returned.
   Interpretation: pass.

## Follow-ups

- Owner: Image Mate engineering. Target: next QGIS manual verification session. Confirm the
  dock opens without authenticated API traffic and remains interactive while/after Mosaicking
  Studio processing.
- Owner: Image Mate engineering. Target: next performance change. Record p50/p95 shell-ready timing over at
  least ten launches after instrumentation.
- Owner: Image Mate engineering. Target: subsequent optimization only if the 500 ms target is
  missed. Implement lazy tab construction and local dataset deferral.
