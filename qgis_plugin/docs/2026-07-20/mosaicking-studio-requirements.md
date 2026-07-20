# Mosaicking Studio MVP Requirements

## 1. Objective Summary

- Objective: `OBJ-001` — create a saved raster mosaic from QGIS project layers
  without leaving Image Mate.
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

## 5. Verification Plan

| Verification ID | Requirement IDs | Method | Evidence | Test Owner |
| --- | --- | --- | --- | --- |
| TC-001 | REQ-F-002;REQ-F-003;REQ-F-004;REQ-F-006;REQ-NF-002 | Automated test | `mosaicking_service_smoke.py` output | QGIS plugin |
| TC-002 | REQ-F-001;REQ-F-005;REQ-NF-001;REQ-BR-001 | Static contract test | `mosaicking_studio_wiring_smoke.py` output | QGIS plugin |
| TC-003 | REQ-F-004 | Automated inspection | Vendored parser/help invocation | QGIS plugin |
| TC-004 | All | Demonstration | Interactive QGIS acceptance run with two local rasters | Product owner |

## 6. Coverage Gaps and Risks

- `TC-004` requires a QGIS GUI and representative local imagery and is therefore
  not terminal-automated.
- The engine's own synthetic end-to-end test is dependency-heavy; the adapter
  smoke test isolates integration behavior for low-bandwidth verification.
