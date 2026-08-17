# Image-mate + Satellogic Grid Tasking Integration — Design Revision

**Source package:** `/root/.hermes/attachments/satl_grid_tasking - v3.zip`
**Extracted review copy:** `/tmp/satl-grid-tasking-v3`
**Date:** 2026-08-13

## Source package identity

This attachment is a complete local Grid Tasking Campaign web application, not the earlier `satl` skill bundle. It implements:

- polygon/MultiPolygon AOI normalization and repair;
- UTM metric square-grid planning;
- `TSKARE-M` one-Feature-per-cell order payload generation;
- plan artifacts and map review;
- SQLite campaign/plan/cell/order persistence;
- safe order submission with exact-name reconciliation;
- Order → Capture → Deliverable synchronization;
- manual delivery disposition;
- retask, extension, and remaining-AOI successor orders;
- archive coverage and cumulative coverage projections.

## Reconciliation with image-mate

### Preserve from v3

1. `normalize_aoi`, including FeatureCollection/MultiPolygon support and validation warnings.
2. UTM grid planning with configurable cell size, clip mode, minimum area, ONA, sun elevation, processing level, and remapping parameters.
3. `build_order_feature`: each tasking cell is an individual GeoJSON `Feature`; never submit a multi-cell FeatureCollection.
4. Exact generated order names and cell identity.
5. Submission safety:
   - persist attempt before POST;
   - reconcile by exact order name before retrying;
   - classify ambiguous timeouts/5xx/429 without blind replay;
   - persist each cell result immediately.
6. Status rollup priority across order, event, capture, and deliverable state.
7. Coverage-aware remaining geometry and successor order naming.
8. Audit and security boundaries: no secrets in SQLite, browser, artifacts, or logs.

### Do not copy wholesale

- Standalone SQLAlchemy ORM and Alembic application: image-mate already has an application architecture and SQLite monitoring store.
- Standalone Jinja/HTMX templates: image-mate uses its existing Leaflet SPA/workbench UI.
- The v3 package’s separate credential naming/cache behavior: image-mate must continue using its project `.env` with `SATELLOGIC_KEY_ID`, `SATELLOGIC_KEY_SECRET`, and the selected `SATELLOGIC_CONTRACT_ID`.
- Any persisted attachment URLs or raw credential-bearing responses.

## Revised image-mate architecture

```text
Leaflet / Workbench UI
        |
        +-- archive search + thumbnail footprint monitoring
        |
        +-- grid planning preview (read-only)
        |
        +-- explicit confirmed grid submission
        |
        +-- per-cell lifecycle and recollection health
        v
FastAPI image-mate backend
        |
        +-- existing SourceManager/SatellogicClient
        +-- new grid_tasking service layer (pure geometry/planning/status)
        +-- existing MonitoringStore + new grid campaign tables/state
        v
Satellogic Aleph V2 API
```

## Product behavior

### Monitoring

- A user creates a named AOI monitor from drawn/current geometry or uploaded GeoJSON.
- Refresh searches `quickview-visual-thumb` or another selected archive collection.
- Results are deduplicated by outcome and stored without signed URLs.
- UI reports `archive_observed`, `overdue`, or `no_capture_found` separately from tasking/deliverable verification.

### Grid planning

- User opens Grid Tasking for a monitored AOI or current viewport.
- User configures cell size, clip mode, minimum cell area, tasking window, ONA, sun elevation, processing, remapping, project, and order prefix.
- Plan is computed locally and produces:
  - retained/discarded cell counts and area;
  - UTM EPSG;
  - unsupported geometry warnings;
  - individual order payload preview;
  - GeoJSON grid artifact.
- Planning performs no order API writes.

### Submission

- Submission requires:
  - credentials configured;
  - selected contract;
  - active `TSKARE-M` product;
  - valid AOI and plan;
  - current dates;
  - typed confirmation containing the campaign/plan name.
- Each cell is submitted individually.
- Monitoring refresh never submits or cancels orders.
- Retask, extension, and remaining-AOI tasking create linked successor orders and require a separate explicit confirmation.

### Recollection success

- Archive footprints indicate an observed capture.
- Linked tasking orders expose remote order/capture/deliverable state.
- A cell or AOI is not labeled successfully delivered merely because the order is closed or a nearby archive scene exists.
- The UI shows remote rollup, local workflow disposition, and archive coverage independently.

## Integration increments

1. **Service import cleanup:** make copied v3 pure services importable under `backend/app/grid_tasking/` without the standalone app.
2. **Pure service tests:** geometry, grid, payload, status rollup, coverage subtraction, and safe naming.
3. **Image-mate grid plan API:** create/inspect plans from AOI geometry; persist plans and cell payloads through the existing application storage boundary.
4. **Read-only UI:** grid preview and per-cell status/footprints integrated with the existing Monitoring/Explore surfaces.
5. **Explicit tasking API:** queue safe per-cell submission using existing Satellogic client, confirmation and reconciliation rules.
6. **Lifecycle sync:** connect per-cell remote status to capture/deliverable endpoints and recollection health.
7. **Retask/extension/remaining-AOI actions:** preview first, confirmation second, successor order only.
8. **Full verification and local startup.**

## Acceptance requirements for this integration

- Luxembourg fixture produces 11 cells under the v3 defaults.
- Generated payloads are individual `Feature` objects.
- Grid planning makes no remote order-creation call.
- Archive monitoring and grid planning share the same AOI geometry.
- Status rollup distinguishes delivered, processing, acquired, collecting, failed, canceled, and closed.
- Ambiguous order creation is reconciled by exact order name before retry.
- No tasking API write happens without an explicit confirmed operation.
- No secret/token/header enters UI, persisted state, artifacts, or logs.
- The local UI exposes Monitoring and Grid Tasking with professional map/table/status views.
- The app starts locally and the verified URL is reported only after health and UI smoke checks pass.
