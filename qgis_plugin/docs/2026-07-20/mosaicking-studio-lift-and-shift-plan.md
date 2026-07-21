# Mosaicking Studio Lift-and-Shift Design and Implementation Plan

- Date: 2026-07-20
- Scope: `qgis_plugin/**` only
- Requirements: `mosaicking-studio-requirements.md`
- Traceability: `mosaicking-studio-rtm.csv`

## Problem Statement

The standalone `Mosaicker_v2` engine cannot currently be launched from Image Mate.
Users must leave QGIS, assemble command-line paths, run the tool, and manually add
the result. The MVP shall expose the existing engine through a guided QGIS workflow
without redesigning its seam, cloud, or radiometric algorithms.

## Existing Reusable Components

- `ImageMateMainDock._project_raster_layer_options()` enumerates project rasters.
- `ImageMatePlugin._resolve_local_raster_source_path()` resolves QGIS providers to
  local files.
- `ImageMatePlugin._add_layer_to_image_mate_group()` adds generated rasters.
- `QgsTask` provides background execution outside the GUI thread.
- `Mosaicker_v2/src/mosaicker/seamless_mosaic.py` is the source algorithm.

## Proposed Backend Changes

1. Vendor the MIT-licensed engine under
   `image_mate_qgis_plugin/vendor/mosaicker/` with its license.
2. Add `MosaickingService` to validate paths, lazy-load optional dependencies,
   translate the studio request to the existing CLI contract, and verify outputs.
3. Run the service through `QgsTask`; add a valid output through the existing
   Image Mate project-layer helper.

## UI Wiring Changes (Minimal)

Add a `Mosaicking Studio` button to Geoprocessing. The button opens a wizard with
an input-layer page and output-file page. The dock emits the accepted request;
all path resolution, processing, and project mutation remain in the plugin/service
layer.

## Implementation Steps

1. Copy the standalone engine and license without algorithm changes.
2. Implement and unit-test the service adapter.
3. Add the wizard and dock signal/button.
4. Wire background execution and output-layer loading in `plugin.py`.
5. Update user-facing documentation and run terminal quality gates.

## Terminal-Only Test Plan

- Compile all changed Python modules with `py -3 -m compileall -q`.
- Run a service smoke test with an injected fake engine, temporary inputs, and a
  temporary output.
- Run a static wiring smoke test for the Geoprocessing button, signal, handler,
  background task, and output-layer loading.
- Run `mosaicking_engine_smoke.py` against the exact vendored engine.
- Run QGIS scope and documentation coverage scripts.

## Risks and Rollback

- Risk: QGIS Python may not provide Rasterio, SciPy, OpenCV, Shapely, or Affine.
  Mitigation: lazy-load the engine only when requested and show an actionable
  dependency error without preventing plugin startup.
- Risk: large mosaics take significant time. Mitigation: use `QgsTask` and keep
  filesystem processing off the GUI thread.
- Risk: project raster providers may be remote or virtual. Mitigation: resolve and
  validate local paths before starting; report each unsupported layer.
- Rollback: remove the button/signal/handler, service, and vendored package. No
  project or data migration is required.

## Deferred Scope

- Cutline creation and editing.
- Interactive seam ownership editing.
- User-controlled feathering and cloud-mask parameters.
- Per-input priorities and external cloud-mask assignment.
- Persistent/reopenable studio projects.

## Implementation Summary

- Vendored the package engine and MIT license without algorithm changes; source
  and destination SHA-256 values both equal
  `CC1C3885684FEF2C37F6F3269A70C53A35F745D0A9A5C737906E4B1E85BFF8D5`.
- Added a lazy service adapter, a three-page wizard, a Geoprocessing button, and
  QGIS background-task/output-layer wiring.
- Added adapter, static wiring, and full synthetic engine smoke tests.
- Added canonical operator guidance in `qgis_plugin/docs/mosaicking-studio.md`.

## Verification Evidence

1. Command: `py -3 qgis_plugin/test/mosaicking_service_smoke.py`
   Expectation: validate inputs/overwrite, preserve engine defaults, invoke an
   injected runner, and reject failed/missing outputs.
   Observed: `mosaicking_service_smoke: ok`.
   Interpretation: Pass.
2. Command: `py -3 qgis_plugin/test/mosaicking_studio_wiring_smoke.py`
   Expectation: verify button/signal/wizard/task/layer-loading contracts and the
   absence of deferred controls.
   Observed: `mosaicking_studio_wiring_smoke: ok`.
   Interpretation: Pass.
3. Command: `py -3 qgis_plugin/test/mosaicking_engine_smoke.py`
   Expectation: run synthetic radiometric balancing, cloud replacement, gap-mask,
   sizing, and tile-memory checks against the vendored engine.
   Observed: `All smoke tests passed.`
   Interpretation: Pass.
4. Command: `py -3 -m compileall -q qgis_plugin/image_mate_qgis_plugin ...`
   Expectation: all plugin, adapter, UI, engine, and smoke-test Python compiles.
   Observed: exit code 0 with no error output.
   Interpretation: Pass.
5. Command: run `MosaickingService.create_mosaic(...)` with the four current
   VISUAL rasters under
   `G:\Shared drives\ChannelDrive-Internal\APAC\Market Materials\City Imagery\Jakarta`,
   including replacement folder `aleph_20260720115524`.
   Expectation: create a readable three-band GeoTIFF and analysis report from all
   four inputs.
   Observed: created
   `Jakarta_ImageMate_mosaic_test_20260720_115732.tif` (405,059,292 bytes) in
   366.7 service seconds. The raster is EPSG:32748, 24,005 x 20,007 pixels,
   three uint8 bands, has overview factors 2/4/8/16/32, and its report status is
   `complete` with four inputs. No work directory remained.
   Interpretation: Pass.

## Real-Data Finding and Remediation

The first acceptance attempt failed after preflight because one Aleph input was
removed while the engine was reading the shared-drive dataset. The user confirmed
the removal was intentional and supplied `aleph_20260720115524` as its replacement.
`MosaickingService` now checks for inputs that became unavailable when the engine
returns a failure and reports the exact missing paths. The adapter smoke test
reproduces and verifies this failure message.

## Follow-ups

- Not run: interactive QGIS wizard/task-manager/layer-add acceptance. The full
  backend service was validated with representative imagery, but the final GUI
  interaction still requires QGIS. Owner: product owner. Target: before release.
- Add cutline editing, manual seam/feather controls, and cloud-mask workflows in
  separately requirement-scoped increments. Owner: product owner. Target: TBD.
