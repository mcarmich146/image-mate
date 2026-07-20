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
- Run the imported engine's parser/help path without importing QGIS.
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
