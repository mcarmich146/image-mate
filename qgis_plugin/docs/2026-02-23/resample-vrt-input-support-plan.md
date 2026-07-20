# Resample Vrt Input Support Design and Implementation Plan

- Date: 2026-02-23
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement
Resample-to-10m rejects some VRT-backed raster layers with:
`Resample requires a local raster file layer (not remote stream).`
even when the selected layer is local. We need deterministic local-path
resolution that accepts local `.vrt` URI variants while still rejecting
remote stream layers.

## Existing Reusable Components
- Existing resample handler and geoprocessing flow in:
  - `image_mate_qgis_plugin/plugin.py::handle_resample_image_10m_request`
- Existing local raster source gate used by sharpen/vessel flows:
  - `image_mate_qgis_plugin/plugin.py::_resolve_local_raster_source_path`
- Existing processing runtime bootstrap:
  - `image_mate_qgis_plugin/services/processing_runtime.py`

## Proposed Backend Changes
- Add a reusable backend service:
  - `image_mate_qgis_plugin/services/local_raster_path_resolver.py`
  - Responsibility: map QGIS-style layer source strings to an existing local
    filesystem path.
- Resolver behavior:
  - Accept plain local paths (`.vrt`, `.tif`, etc.).
  - Accept `file://` URIs.
  - Strip provider suffixes (`|...`) from source strings.
  - Resolve relative paths against project base dirs.
  - Reject remote stream URIs (`http(s)`, `type=xyz`, `type=wms`, etc.).
- Update plugin local raster resolver to use service and include both:
  - `layer.source()`
  - `layer.dataProvider().dataSourceUri()`
- Improve failed-resample diagnostics with provider/source/URI details in debug log.

## UI Wiring Changes (Minimal)
None. Existing resample dialog/button remain unchanged.

## Implementation Steps
1. Implement `local_raster_path_resolver` service with source parsing + local path checks.
2. Wire `plugin.py::_resolve_local_raster_source_path` to use the service.
3. Update resample failure branch to emit detailed debug diagnostics and clarify message.
4. Add terminal smoke check for resolver edge cases.

## Terminal-Only Test Plan
- Compile checks:
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/services/local_raster_path_resolver.py`
  - `py -3 -m py_compile qgis_plugin/image_mate_qgis_plugin/plugin.py`
- Resolver smoke check:
  - `py -3 qgis_plugin/test/local_raster_path_resolver_smoke.py`
  - Asserts direct path, file URI, pipe-suffixed path, relative path, and remote URI rejection.

## Risks and Rollback
- Risk: URI parsing may incorrectly accept unsupported remote-like inputs.
  - Mitigation: explicit remote-prefix rejection + existing-path checks before acceptance.
- Risk: project-relative path assumptions may vary by environment.
  - Mitigation: resolve against both project absolute path and project home path.
- Rollback:
  - Revert resolver service wiring in `plugin.py` and remove new service file.
