# Mosaicking Studio MVP Requirements

## 1. Objective Summary

- Objective: `OBJ-001` — create a saved raster mosaic from QGIS project layers
  without leaving Image Mate.
- Objective: `OBJ-002` — keep the studio visible and communicate processing
  progress/status from submission through terminal completion.
- Objective: `OBJ-003` - keep plugin artifacts portable across developer and
  operator home directories.
- Target users: Image Mate QGIS analysts.
- In scope: guided launch, local raster selection, output selection, existing
  engine execution, progress notification, and loading the result into QGIS.
- Out of scope: cutline editing/creation, manual feather/cloud controls, external
  mask authoring, engine redesign, and remote output destinations.
- Constraint: all repository changes remain in `qgis_plugin/**`.
- Success metric: a user can select two or more local raster layers, choose a
  `.tif` output, start processing, and receive a valid project raster layer.

## 2. Assumptions and Open Questions

| ID | Assumption | Impact | Owner |
| --- | --- | --- | --- |
| ASM-001 | Selected rasters have compatible physical band semantics. | The ported engine validates structural incompatibilities but cannot infer semantic mismatches. | Product owner |
| ASM-002 | Required Python geospatial packages can be installed in the QGIS Python environment. | Missing packages block only mosaic execution, not plugin loading. | Plugin operator |
| ASM-003 | The existing engine defaults are acceptable for the MVP. | Advanced editing and tuning are deferred. | Product owner |
| ASM-004 | Engine log messages remain the available source of phase/tile progress. | Percentages are derived from stable phase/tile patterns and completion remains task-result driven. | QGIS plugin |

| ID | Question | Blocking? | Owner |
| --- | --- | --- | --- |
| Q-001 | Which cutline editing model should the next studio iteration use? | No | Product owner |
| Q-002 | Should advanced cloud/feather settings persist per project? | No | Product owner |

## 3. Requirements

| Requirement ID | Type | Statement | Source | Rationale | Priority | Owner |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-F-001 | Functional | The plugin shall expose a `Mosaicking Studio` action under Geoprocessing. | OBJ-001 | Makes the workflow discoverable. | Must | QGIS plugin |
| REQ-F-002 | Functional | The studio shall allow the user to select at least two raster layers currently loaded in the QGIS project. | OBJ-001 | Defines mosaic inputs in project terms. | Must | QGIS plugin |
| REQ-F-003 | Functional | The studio shall require a local `.tif` or `.tiff` output path and shall not replace an existing file unless overwrite is explicitly selected. | OBJ-001 | Prevents ambiguous or destructive output behavior. | Must | QGIS plugin |
| REQ-F-004 | Functional | The plugin shall run the ported `Mosaicker_v2` algorithm with the selected local raster paths and output path. | OBJ-001 | Preserves the requested lift-and-shift algorithm. | Must | QGIS plugin |
| REQ-F-005 | Functional | The plugin shall add a valid completed mosaic to the Image Mate layer group. | OBJ-001 | Completes the QGIS round trip. | Must | QGIS plugin |
| REQ-F-006 | Functional | The plugin shall report actionable validation, dependency, execution, and output-loading failures through QGIS messages and logs. | OBJ-001 | Makes failure recoverable. | Must | QGIS plugin |
| REQ-NF-001 | Non-functional | The plugin shall execute mosaic generation through a QGIS background task rather than on the GUI thread. | OBJ-001 | Large mosaics must not freeze the studio launch path. | Must | QGIS plugin |
| REQ-NF-002 | Non-functional | The plugin shall lazy-load optional mosaicker dependencies so missing packages do not prevent Image Mate startup. | OBJ-001 | Protects unrelated plugin workflows. | Must | QGIS plugin |
| REQ-BR-001 | Business rule | The MVP shall expose engine defaults and shall defer interactive cutline, feather, and cloud controls. | OBJ-001 | Keeps this increment to lift-and-shift scope. | Must | Product owner |
| REQ-F-007 | Functional | The studio shall present Inputs, Output, Review, and Processing Results as tabs in one persistent dialog. | OBJ-002 | Keeps the workflow spatially stable. | Must | QGIS plugin |
| REQ-F-008 | Functional | The studio shall move between validated step tabs through Back and Next controls. | OBJ-002 | Preserves guided navigation without opening new windows. | Must | QGIS plugin |
| REQ-F-009 | Functional | The studio shall switch to Processing Results without closing when Finish submits a valid request. | OBJ-002 | Keeps feedback visible after submission. | Must | QGIS plugin |
| REQ-F-010 | Functional | The Processing Results tab shall display progress from 0 through 100 percent as engine phases and tiles advance. | OBJ-002 | Communicates that work is active and how far it has progressed. | Must | QGIS plugin |
| REQ-F-011 | Functional | The Processing Results tab shall append timestamped engine and plugin status messages while the task runs. | OBJ-002 | Makes current activity and failures diagnosable. | Must | QGIS plugin |
| REQ-BR-002 | Business rule | The studio shall prevent closing during processing and shall enable Close after success or failure. | OBJ-002 | Prevents accidental loss of live feedback. | Must | QGIS plugin |
| REQ-F-012 | Functional | The Output tab shall provide an `Include debug information` checkbox that controls whether detailed diagnostic messages appear in Processing Results. | OBJ-002 | Lets users collect actionable diagnostics without cluttering normal runs. | Must | QGIS plugin |
| REQ-NF-003 | Non-functional | When debug information is enabled, the plugin shall report each request, task submission, worker, dependency-loading, engine, output-verification, and completion boundary. | OBJ-002 | Distinguishes queued, import-blocked, engine-blocked, and completion failures. | Must | QGIS plugin |
| REQ-NF-004 | Non-functional | The plugin shall transfer worker log messages to the studio without invoking dialog signals directly from the QGIS worker thread. | OBJ-002 | Prevents immediate task termination at the GUI thread boundary. | Must | QGIS plugin |
| REQ-F-013 | Functional | The studio shall display the stored task exception when a QGIS task terminates without completing its normal callback. | OBJ-002 | Prevents terminal failures from leaving the studio stuck in a processing state. | Must | QGIS plugin |
| REQ-NF-005 | Non-functional | QGIS plugin text artifacts shall not contain a developer-specific workstation username. | OBJ-003 | Keeps paths portable and avoids leaking workstation identity. | Must | QGIS plugin |

## 4. Acceptance Criteria

| AC ID | Requirement ID | Criterion |
| --- | --- | --- |
| AC-001 | REQ-F-001 | Given the Geoprocessing tab, when it is displayed, then a `Mosaicking Studio` button is present. |
| AC-002 | REQ-F-002 | Given fewer than two selected rasters, when the user attempts to advance, then the studio remains open and explains the minimum. |
| AC-003 | REQ-F-003 | Given a missing/invalid output or an existing output without overwrite, when validation runs, then processing does not start. |
| AC-004 | REQ-F-004 | Given valid local inputs and an injected engine, when processing runs, then all input paths and the requested output are passed to the engine. |
| AC-005 | REQ-F-005 | Given a successful task and valid output, when completion runs, then a `QgsRasterLayer` is added through the Image Mate group helper. |
| AC-006 | REQ-F-006 | Given an unsupported layer or missing dependency, when launch/run is attempted, then an actionable failure is emitted without crashing the plugin. |
| AC-007 | REQ-NF-001 | Given an accepted request, when processing starts, then it is submitted to `QgsApplication.taskManager()` as a `QgsTask`. |
| AC-008 | REQ-NF-002 | Given missing optional packages, when Image Mate imports, then core plugin modules still import and only execution reports the missing packages. |
| AC-009 | REQ-BR-001 | Given the MVP studio, when inspected, then it contains input/output steps and no cutline editor or advanced cloud/feather controls. |
| AC-010 | REQ-F-007 | Given the studio opens, when inspected, then one dialog contains four labeled step tabs. |
| AC-011 | REQ-F-008 | Given a valid current step, when Next or Back is clicked, then the current tab changes inside the same dialog. |
| AC-012 | REQ-F-009 | Given Review is valid, when Finish is clicked, then Processing Results becomes current and the dialog remains open. |
| AC-013 | REQ-F-010 | Given planning/tile/overview/completion log events, when parsed, then progress is monotonic phase-mapped values ending at 100. |
| AC-014 | REQ-F-011 | Given a running task, when engine/plugin messages arrive, then timestamped text is appended to the results log. |
| AC-015 | REQ-BR-002 | Given processing is active, when close is requested, then it is refused; after terminal status Close succeeds. |
| AC-016 | REQ-F-012 | Given debug information is unchecked or checked, when a run starts, then detailed `DEBUG:` messages are respectively hidden or shown in Processing Results. |
| AC-017 | REQ-NF-003 | Given debug information is enabled, when processing advances or fails, then the last displayed lifecycle boundary identifies where execution stopped. |
| AC-018 | REQ-NF-004 | Given a real `QgsTask`, when worker logs are published, then a thread-safe buffer delivers them and the task completes without a GUI-thread exception. |
| AC-019 | REQ-F-013 | Given QGIS emits `taskTerminated` without a reported completion outcome, when the event loop advances, then Processing Results displays the captured exception and enables Close. |
| AC-020 | REQ-NF-005 | Given all plugin text artifacts including ignored diagnostics, when scanned case-insensitively, then the developer-specific username has zero matches. |
| AC-021 | REQ-F-004 | Given the four Jakarta sources, when full-resolution source candidates are prepared, then numeric bounds filtering completes without the Shapely/NumPy native stack overflow. |

## 5. Verification Plan

| Verification ID | Requirement IDs | Method | Evidence | Test Owner |
| --- | --- | --- | --- | --- |
| TC-001 | REQ-F-002;REQ-F-003;REQ-F-004;REQ-F-006;REQ-NF-002 | Automated test | `mosaicking_service_smoke.py` output | QGIS plugin |
| TC-002 | REQ-F-001;REQ-F-005;REQ-NF-001;REQ-BR-001 | Static contract test | `mosaicking_studio_wiring_smoke.py` output | QGIS plugin |
| TC-003 | REQ-F-004 | Automated test | `mosaicking_engine_smoke.py` synthetic end-to-end output | QGIS plugin |
| TC-004 | All | Demonstration | Interactive QGIS acceptance run with two local rasters | Product owner |
| TC-005 | REQ-F-004;REQ-F-006;REQ-NF-002 | Automated test | Four-source Jakarta `MosaickingService` output and analysis report | QGIS plugin |
| TC-006 | REQ-F-010;REQ-F-011 | Automated test | Progress parser and callback assertions in `mosaicking_service_smoke.py` | QGIS plugin |
| TC-007 | REQ-F-007;REQ-F-008;REQ-F-009;REQ-BR-002 | Static contract test | Tabbed/results-state assertions in `mosaicking_studio_wiring_smoke.py` | QGIS plugin |
| TC-008 | REQ-F-012;REQ-NF-003 | Automated and static test | Debug callback lifecycle assertions in `mosaicking_service_smoke.py` and checkbox/task-boundary assertions in `mosaicking_studio_wiring_smoke.py` | QGIS plugin |
| TC-009 | REQ-NF-004;REQ-F-013 | Automated and static test | Real OSGeo4W `QgsTask` bridge test in `mosaicking_qgstask_bridge_smoke.py` and termination fallback assertions in `mosaicking_studio_wiring_smoke.py` | QGIS plugin |
| TC-010 | REQ-NF-005 | Automated test | Full plugin text scan in `user_path_portability_smoke.py` | QGIS plugin |
| TC-011 | REQ-F-004 | Automated and representative-data test | Bounds-filter regression in `mosaicking_engine_smoke.py` and four-source OSGeo4W reduced-resolution completion run | QGIS plugin |

## 6. Coverage Gaps and Risks

- `TC-004` requires a QGIS GUI and is therefore not terminal-automated. `TC-005`
  validates the full backend with representative imagery.
- The engine's own synthetic end-to-end test is dependency-heavy; the adapter
  smoke test isolates integration behavior for low-bandwidth verification.
