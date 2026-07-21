# Mosaicking Studio Tabbed Progress Design and Implementation Plan

- Date: 2026-07-20
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

The current `QWizard` closes when Finish is clicked. QGIS continues processing in
the task manager, but the user loses the studio context and receives no visible
in-dialog progress or engine log. The step transitions also read as separate
wizard pages rather than a persistent studio workspace.

## Existing Reusable Components

- `MosaickingStudioDialog` already owns input/output/review controls.
- `MosaickingService` already isolates the unchanged engine invocation.
- The engine emits phase and tile progress through Python logging.
- `QgsTask.setProgress()` and PyQt queued signals can safely bridge worker state
  to the GUI thread.

## Proposed Backend Changes

1. Add a pure log-message-to-progress parser in `mosaicking_service.py`.
2. Add optional progress and log callbacks around the engine runner.
3. Attach a temporary logging handler only for the duration of each run and
   always remove it in `finally`.
4. Keep the vendored algorithm unchanged.

## UI Wiring Changes (Minimal)

- Replace `QWizard` with one `QDialog` containing a four-tab `QTabWidget`:
  `1. Inputs`, `2. Output`, `3. Review`, and `4. Processing Results`.
- Back/Next switch tabs inside the same window. Future tabs remain disabled until
  reached through validation.
- Finish switches to Processing Results, disables input navigation, shows a
  progress bar and read-only log, and emits the request without closing.
- The dialog cannot close while processing. Completion/failure enables Close.

## Implementation Steps

1. Extend requirements and RTM with stable progress-UX IDs.
2. Implement/test progress parsing and runner callbacks.
3. Replace the wizard UI with the tabbed dialog state machine.
4. Connect task progress/log/completion/failure to dialog slots.
5. Update canonical operator documentation and run quality gates.

## Terminal-Only Test Plan

- Unit-test representative planning, tile, overview, and completion log mappings.
- Unit-test callback delivery and handler cleanup with an injected runner/logger.
- Statically assert the four tabs, navigation, progress bar, text log, persistent
  Finish behavior, task signal bridge, and terminal-state Close behavior.
- Run existing mosaicking adapter/engine and adjacent geoprocessing smoke tests.
- Compile all changed Python and run scope/documentation checks.

## Risks and Rollback

- Risk: log text changes can reduce progress precision. Mitigation: phase fallback
  values and indeterminate-safe status text; completion still comes from task
  result.
- Risk: worker callbacks touching widgets can violate Qt thread rules. Mitigation:
  emit queued PyQt signals and update widgets only in dialog slots.
- Risk: closing a live dialog can orphan feedback. Mitigation: reject close events
  while processing.
- Rollback: revert the dialog to the prior wizard and remove optional callbacks;
  the engine and output contract remain unchanged.

## Implementation Summary

- Replaced the three-page wizard with a persistent four-tab dialog and explicit
  Back, Next, Finish, and Close state transitions.
- Added a Processing Results progress bar, timestamped read-only log, and guarded
  close behavior while the background task is active.
- Added optional service callbacks and a pure parser that translates existing
  planning, source-analysis, seam, tile, overview, and completion logs into
  monotonic progress.
- Connected the QGIS task to the dialog through queued PyQt signals and report
  validation, execution, loading, and success outcomes in the results tab.
- Added an optional `Include debug information` control and detailed lifecycle
  messages around task submission, worker entry, dependency loading, engine
  invocation, output verification, and completion callbacks.
- Replaced direct worker-to-dialog log signal calls with a thread-safe backend
  buffer drained every 75 ms by the GUI event loop.
- Added a `taskTerminated` fallback that reports the wrapper's stored exception
  and releases the dialog when the normal completion callback is not observed.
- Removed developer-specific home paths from tracked and ignored plugin text;
  runtime probes now resolve the repository from `__file__` and examples use
  `%USERPROFILE%` or relative links.
- Left the vendored mosaicking algorithm and its defaults unchanged.

## Decisions

- Engine log parsing remains in the backend adapter so the dialog does not need
  to know engine message formats.
- The service temporarily enables `INFO` on the engine logger and restores its
  prior level and handlers after every run, including failures.
- Configuration tabs are disabled once processing starts. The dialog stays open
  until a terminal result enables Close.
- Normal logs remain concise. Detailed messages use a visible `DEBUG:` prefix and
  are emitted only when the troubleshooting checkbox is enabled.
- QGIS task workers publish only to a pure-Python thread-safe queue. GUI objects
  are touched only by the main-thread timer drain.

## Verification Evidence

- `mosaicking_service_smoke.py`: passed; covers callback delivery, monotonic
  phase/tile mapping, logger restoration, and handler cleanup.
- `mosaicking_studio_wiring_smoke.py`: passed; covers tab structure, persistent
  submission, task bridges, results controls, and terminal-state wiring.
- `mosaicking_engine_smoke.py`: passed with the synthetic end-to-end engine.
- Adjacent raster resolver, resampling, and time-lapse service smoke tests: passed.
- Python compilation, diff whitespace, and `qgis_plugin/**` scope checks: passed.
- Interactive QGIS acceptance remains pending because it requires the QGIS GUI.

## Live Stall Diagnostic Evidence

- `Command:` sample the running `qgis-bin` process CPU and working set over two
  seconds with PowerShell `Get-Process`.
  `Expectation:` an active mosaicker consumes CPU or changes working memory.
  `Observed:` CPU delta was `0` seconds and working-set delta was `0 MB`.
  `Interpretation:` the observed run was idle rather than performing slow mosaic
  computation.
- `Command:` import the vendored engine with
  `C:\OSGeo4W\bin\python-qgis.bat` on the main thread and a Python worker thread.
  `Expectation:` dependencies load without hanging in the QGIS runtime.
  `Observed:` imports completed in 1.766 seconds and 0.703 seconds respectively.
  `Interpretation:` dependency availability and worker-thread import are not a
  general blocker in this installation.
- `Command:` submit a minimal `QgsTask.fromFunction` through a headless
  `QgsApplication` in the OSGeo4W runtime.
  `Expectation:` the task starts and returns `42`.
  `Observed:` task id `1` completed with `exception=None` and result `42`.
  `Interpretation:` the QGIS task manager works generally; the exact live-run
  boundary could not be recovered from the former two-line log.
- `Command:` inspect the 2026-07-20 14:41 interactive debug transcript.
  `Expectation:` Running is followed by worker-entry and engine messages.
  `Observed:` QGIS reported `Running (2)` and immediately `Terminated (4)` before
  the first worker message.
  `Interpretation:` the failure is at the worker-to-GUI diagnostic boundary;
  direct dialog signal emission was removed from the worker path.
- `Command:`
  `C:\OSGeo4W\bin\python-qgis.bat qgis_plugin/test/mosaicking_qgstask_bridge_smoke.py`.
  `Expectation:` a real QGIS task transfers diagnostics through the buffer and
  creates a synthetic output.
  `Observed:` `mosaicking_qgstask_bridge_smoke: ok`.
  `Interpretation:` the replacement bridge completes in the target QGIS runtime.
- `Command:` `py -3 qgis_plugin/test/user_path_portability_smoke.py`.
  `Expectation:` tracked and ignored plugin text contains no workstation username.
  `Observed:` `user_path_portability_smoke: ok`.
  `Interpretation:` the portability cleanup is complete and regression guarded.

## Follow-up

- Owner: plugin operator. After deploying/reloading this revision, rerun once
  with `Include debug information` enabled and retain the last lifecycle message
  if execution stops. Target: next interactive QGIS acceptance run.
