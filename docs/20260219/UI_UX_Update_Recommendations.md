# UI/UX Update Recommendations (QGIS Plugin)

Date: 2026-02-20  
Author: Codex UI/UX review (no code changes)

## 1. Scope

This review covers operator-facing copy and structure for the QGIS dock UI, with focus on moving from vendor/product-centric wording to C5ISR mission-centric wording.
It now includes a campaign-centric design proposal using `Collection Campaigns` as the mission container.
It also includes campaign-managed filesystem design so the plugin controls storage paths under a configured base directory.

Reviewed sources:
- `qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`
- `qgis_plugin/image_mate_qgis_plugin/ui/main_dock_workflow.py`
- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/monitoring_store.py`
- `backend/tests/test_tasking_api.py`

## 2. Executive Findings

## 2.1 High impact findings

1. Vendor terms are prominent in operator workflows.
- Examples: `Satellogic`, `Merlin / CDSE`, `Contract ID`, `Product (SKU)`.
- Impact: operator mental model stays tied to provider internals instead of mission actions.

2. Mission functions are split by technical implementation language.
- Examples: `Tasking Order`, `Monitoring Subscription`, `Cue`.
- Impact: users must translate backend concepts into mission intent.

3. Operator and admin concerns are mixed in the same primary surface.
- Examples: `Debug Log`, auth mode raw values (`oauth_client_credentials`), backend URLs.
- Impact: higher cognitive load for analysts and avoidable training burden.

4. Users are still asked to manage output paths in multiple flows.
- Examples: output path prompts for VRT/sharpen utilities and workflow outputs.
- Impact: inconsistent filing, increased training burden, and higher operator error risk.

## 2.2 Medium impact findings

1. Some labels are engineering-centric.
- Examples: `Filters JSON`, `Workflow JSON`, `Reload Functions`.

2. Status language is not lifecycle-oriented for operations.
- Backend statuses like `accepted`, `programming`, `open`, `acked`, `queued_review` need operator-readable mapping.

3. One typo in settings.
- `Remote Existing Layers` should be `Remove Existing Layers`.

## 3. Recommended Information Architecture

Campaign-centric tabs (recommended):

1. `Campaigns` (new)
2. `Collection Search` (current: `Explore`)
3. `Collection Requests` (current: `Tasking`)
4. `Watch & Alerts` (current: `Monitoring`)
5. `Exploitation` (current: `Workflows`)
6. `Geoprocessing` (current: `Utilities`)
7. `Ops Health` (current: `Status`)
8. `Integrations` (current: `Settings`)

Short variant:

1. `Campaigns`
2. `Search`
3. `Requests`
4. `Watch`
5. `Exploit`
6. `Tools`
7. `Ops`
8. `Admin`

### 3.1 Campaign workspace structure

Each campaign should be the operational parent for all collection and monitoring activity.  
Recommended campaign sections:

1. `Overview`
2. `Collection Plan`
3. `Watch & Alerts`
4. `Requests`
5. `Exploitation`
6. `Timeline`
7. `Outputs`

### 3.2 Campaign data model (MVP)

| Field | Purpose |
|---|---|
| `campaign_id` | Stable primary identifier |
| `name` | Human-readable campaign name |
| `mission` | Mission/operation identifier |
| `aoi_geometry` | Campaign area of interest |
| `start_utc` / `end_utc` | Campaign operating window |
| `priority` | Operational urgency (`low`/`medium`/`high`/`urgent`) |
| `status` | Campaign lifecycle state |
| `owner` | Owning analyst/team |
| `tags` | Fast filtering and grouping |

MVP linkage strategy:

1. Add optional `campaign_id` on tasking requests/orders.
2. Add optional `campaign_id` on monitoring subscriptions/events.
3. Add optional `campaign_id` on cues.
4. Add optional `campaign_id` on workflow runs/artifacts.

### 3.3 Campaign lifecycle

Recommended lifecycle states:

1. `Draft`
2. `Active`
3. `Paused`
4. `Completed`
5. `Archived`

### 3.4 Campaign-managed filesystem (base directory model)

Design goal:
- Eliminate routine user path/file entry in mission workflows.
- Persist all campaign artifacts in deterministic, campaign-scoped folders.
- Make campaign handoff and audit reproducible from one root folder.

Base directory:
- One global setting in plugin config, e.g. `Campaign Base Directory`.
- All campaign storage lives under this base path.

Recommended structure:

```text
<base_path>/
  campaigns/
    <campaign_uid>/
      campaign/
        campaign.qgs
        campaign_manifest.json
      imagery/
        raw/<source_id>/<collection_id>/
        browse/<source_id>/<collection_id>/
        derived/
      requests/
        submissions/
        responses/
      watch/
        subscriptions/
        alerts/
        cues/
      exploitation/
        runs/<run_id>/
          inputs/
          intermediate/
          outputs/
          logs/
      geoprocessing/
        outputs/
      exports/
      logs/
```

Minimum deterministic paths:

1. QGIS project: `<base_path>/campaigns/<campaign_uid>/campaign/campaign.qgs`
2. Workflow run outputs: `<base_path>/campaigns/<campaign_uid>/exploitation/runs/<run_id>/outputs/...`
3. Geoprocessing outputs (VRT/sharpen): `<base_path>/campaigns/<campaign_uid>/geoprocessing/outputs/...`
4. Downloaded/cached imagery: `<base_path>/campaigns/<campaign_uid>/imagery/...`

Campaign manifest (`campaign_manifest.json`) should track:

1. Campaign metadata (`campaign_id`, name, mission, status, AOI, time window)
2. Relative paths for key artifacts (project, logs, outputs)
3. Optional source provenance hashes/checksums
4. Plugin version + schema version for migration safety

Proposed storage service contract:

1. `set_base_dir(path)`
2. `ensure_campaign_tree(campaign_id)`
3. `project_path(campaign_id) -> Path`
4. `new_artifact_path(campaign_id, domain, suffix, hint, run_id=None) -> Path`
5. `register_artifact(campaign_id, artifact_meta)`
6. `list_campaign_artifacts(campaign_id, filters)`

Operational behavior:

1. Selecting/creating a campaign automatically resolves/creates `campaign.qgs`.
2. Utilities/workflows write outputs to campaign-managed folders automatically.
3. UI asks for semantic intent (e.g., `Output Name` optional), not filesystem path.
4. Optional explicit `Export` action copies artifacts to analyst-chosen external location.

## 4. UI Copy Dictionary (Current -> Recommended)

Note: this list is intended as the copy baseline for the current dock UI. It includes tabs, visible fields, buttons, major options, placeholders, and key user prompts.

## 4.1 Global Header and Tabs

| Current | Recommended (C5ISR) | Notes |
|---|---|---|
| `Image Mate` | `ISR Mission Workbench` | Operator framing vs product name |
| `Phase 1 implementation baseline` | `Operational Prototype` | Remove engineering phase language |
| `N/A (new)` | `Campaigns` | New top-level mission container |
| `Explore` | `Collection Search` | Mission verb |
| `Tasking` | `Collection Requests` | User intent, not backend noun |
| `Monitoring` | `Watch & Alerts` | Clear watch lifecycle |
| `Workflows` | `Exploitation` | Intelligence workflow framing |
| `Utilities` | `Geoprocessing` | GIS operator vocabulary |
| `Status` | `Ops Health` | Operational state framing |
| `Settings` | `Integrations` | Configuration + providers |
| `N/A (new)` | `Current Campaign` | Persistent campaign context chip/label |

## 4.2 Explore / Collection Search

| Current | Recommended (C5ISR) | Notes |
|---|---|---|
| `Source` | `Sensor Feed` | Provider-neutral |
| `Collection` | `Product Layer` | STAC detail hidden |
| `Contract ID` | `Access Profile` | Mission-access framing |
| `Start date` | `Start Date (UTC)` | Explicit timezone |
| `End date` | `End Date (UTC)` | Explicit timezone |
| `Cloud cover <=` | `Max Cloud (%)` | Simpler threshold wording |
| `Min GSD (m)` | `Min Resolution (m/px)` | Keep metric, reduce jargon |
| `Max GSD (m)` | `Max Resolution (m/px)` | Keep metric, reduce jargon |
| `Limit` | `Max Results` | Clear effect |
| `Satellite name` | `Platform` | ISR-familiar term |
| `Jump To Location` | `Go To AOI` | AOI-centric |
| `Go` | `Center` | Clear map action |
| `Search Map Extent` | `Search Current AOI` | Mission context |
| `Results` | `Candidate Captures` | Analyst intent |
| `Search Log` | `Activity Log` | General operator wording |
| `Debug Log` | `System Log` | Reserve debug for admin |
| `Select a result row to load imagery. Check rows to build a stack for workflow sources.` | `Select a capture to load imagery. Check multiple captures to build a time stack.` | Operator action clarity |
| `Search output will appear here.` | `Search activity appears here.` | Neutral |
| `Debug output will appear here.` | `System diagnostics appear here.` | Advanced framing |
| `city/address or lat, lon (e.g. -34.6037, -58.3816)` | `Place name or lat, lon (example: 34.6037, -58.3816)` | Cleaner operator hint |
| `Copy Outcome ID` | `Copy Capture Group ID` | Avoid internal term where possible |
| `Copy Item ID` | `Copy Capture ID` | Align with capture nomenclature |

## 4.3 Collection Requests (Tasking)

| Current | Recommended (C5ISR) | Notes |
|---|---|---|
| `Tasking status: idle` | `Request status: idle` | Operator lifecycle |
| `Create Tasking Order` | `Create Collection Request` | Mission verb |
| `Target Type` | `Target Mode` | Simpler |
| `Point Target` | `Point Target` | Keep |
| `Area Target` | `Area Target` | Keep |
| `Geometry Source` | `Target Geometry Source` | Specific |
| `Map Center` | `Map Center Point` | Explicit |
| `Selected Result Centroid` | `Selected Capture Centroid` | Consistent naming |
| `Current Map Extent` | `Current AOI Extent` | AOI framing |
| `Selected Result Footprint` | `Selected Capture Footprint` | Consistent naming |
| `Order Name` | `Request Name` | Backend-agnostic |
| `Project Name` | `Mission / Operation` | C5ISR term |
| `Product (SKU)` | `Collection Package` | Hide SKU unless advanced |
| `Start (UTC)` | `Collection Window Start (UTC)` | Operational meaning |
| `End (UTC)` | `Collection Window End (UTC)` | Operational meaning |
| `Revisit Period` | `Revisit Cadence` | Operational cadence |
| `Remapping Period` | `Refresh Cadence` | More intuitive for area refresh |
| `Refresh Orders` | `Refresh Requests` | Consistency |
| `Submit Tasking Order` | `Submit Request` | Simpler |
| `No tasking orders loaded.` | `No requests loaded.` | Neutral |
| `Select an order to view detail and refresh order status.` | `Select a request to view details and refresh status.` | Consistency |
| `Select a tasking order to view details.` | `Select a request to view details.` | Consistency |
| `required` (placeholder) | `Required` | Minor polish |
| `optional (e.g. P15D)` (cadence) | `Optional (example: P15D)` | Minor polish |
| `No tasking products available` | `No collection packages available` | Mission language |
| `Tasking uses the Explore tab contract id. For area targets, select current map extent or selected result footprint.` | `Requests use the Search tab access profile. For area targets, use current AOI extent or selected capture footprint.` | Remove product naming |

## 4.4 Watch & Alerts (Monitoring)

| Current | Recommended (C5ISR) | Notes |
|---|---|---|
| `Monitoring status: idle` | `Watch status: idle` | Mission lifecycle |
| `Create Monitoring Subscription` | `Create Watch` | Short and operator-friendly |
| `Source` | `Sensor Feed` | Consistency |
| `Name` | `Watch Name` | Specific |
| `Collection IDs` | `Product Layers` | Hide raw id terminology |
| `Geometry Source` | `Watch Area Source` | Specific |
| `Filters JSON` | `Filter Rules (JSON)` | Keep technical hint but clearer |
| `Enabled` | `Active` | Lifecycle state |
| `Create Subscription` | `Create Watch` | Consistency |
| `Refresh Feed` | `Refresh Alerts` | Mission language |
| `Event Status` | `Alert Status` | Mission language |
| `All Statuses` | `All` | Simpler |
| `Open` | `New` | Analyst meaning |
| `Acked` | `Reviewed` | Action meaning |
| `Queued Review` | `Queued for Review` | Grammar + clarity |
| `Ack Selected Event` | `Mark Alert Reviewed` | Actionable |
| `Cue Priority` | `Request Priority` | User intent |
| `Cue Geometry` | `Request Geometry` | User intent |
| `Create Cue From Event` | `Create Request From Alert` | Direct operator action |
| `Low` / `Medium` / `High` / `Urgent` | Keep | Standard priority labels |
| `Event Geometry` | `Alert Geometry` | Consistency |
| `Subscriptions` | `Watches` | Mission noun |
| `Events` | `Alerts` | Mission noun |
| `Cues` | `Pending Requests` | Meaning over internal term |
| `Select a monitoring row to inspect details.` | `Select a watch, alert, or request to inspect details.` | Clarify |
| `optional subscription name` | `Optional watch name` | Minor polish |
| `optional csv, e.g. l1d-sr` | `Optional CSV (example: l1d-sr)` | Minor polish |
| `{}` (filters placeholder) | `{"key":"value"}` | More explicit input example |

## 4.5 Exploitation (Workflows)

| Current | Recommended (C5ISR) | Notes |
|---|---|---|
| `Canvas` | `Pipeline Builder` | Function over metaphor |
| `Workflow Log` | `Execution Log` | Clear runtime meaning |
| `Source` | `Input` | Generic workflow term |
| `Single Image` | `Single Capture` | Capture-centric |
| `Temporal Stack` | `Time-Series Stack` | ISR phrasing |
| `Mosaic-Bundle` | `Mosaic Bundle` | Typographic cleanup |
| `Multi-Temporal Stacks` | `Multi-Time-Series Stacks` | Clarity |
| `Add Source` | `Add Input` | Workflow semantics |
| `Function` | `Analytic` | Mission language |
| `Reload Functions` | `Refresh Analytics` | User intent |
| `Add Function Node` | `Add Analytic Step` | Less technical |
| `Connect Nodes` | `Link Steps` | Simpler |
| `Delete Selected` | `Remove Selected` | Consistency |
| `Save Workflow JSON` | `Export Pipeline JSON` | Explicit direction |
| `Load Workflow JSON` | `Import Pipeline JSON` | Explicit direction |
| `Execute Workflow` | `Run Pipeline` | Action-oriented |
| `Workflow execution log will appear here.` | `Pipeline execution log appears here.` | Consistency |
| `No search results available` | `No captures available from current search` | Context clarity |
| `No checked results available` | `No checked captures available` | Consistency |
| `No function plugins found` | `No analytics available` | User-facing terminology |
| `Supported tokens:` | `Supported filename tokens:` | Precision |
| `Select output file path...` | `Select output file path` | Minor polish |
| `Browse...` | `Browse` | Minor polish |
| `Select Source Image` | `Select Input Capture` | Consistency |
| `Search Results` (dialog label) | `Search Captures` | Consistency |
| `Select Source Stack` | `Select Input Stack` | Consistency |
| `Select one or more images from current search results.` | `Select one or more captures from current search results.` | Consistency |
| `Select All` | Keep | Standard action |
| `Clear All` | Keep | Standard action |
| `No Sources Selected` | `No Inputs Selected` | Consistency |
| `Workflow Source Selection` | `Input Selection` | Simpler |
| `Source Type` | `Input Type` | Simpler |
| `Image Stack` | `Capture Stack` | Consistency |
| `Stack Status` | `Stack Summary` | Better meaning |
| `Add Source Node to Canvas` | `Add Input Node` | Simpler |
| `Checked results: 0` | `Checked captures: 0` | Consistency |
| `In Explore > Results, check multiple rows to build a stack.` | `In Collection Search > Candidate Captures, check multiple captures to build a stack.` | New tab naming |
| `Use 'Single Image' for one item or 'Stack' for all checked items.` | `Use 'Single Capture' for one capture or 'Time-Series Stack' for checked captures.` | Consistency |

## 4.6 Geoprocessing (Utilities)

| Current | Recommended (C5ISR) | Notes |
|---|---|---|
| `Virtual Raster` | `Virtual Mosaic` | More familiar to operators |
| `Create VRT` | `Build Virtual Mosaic` | Action + outcome |
| `Image Enhancement` | `Enhancement` | Simpler |
| `Sharpen Image` | `Sharpen Raster` | GIS specificity |
| `Run lightweight raster utilities on layers currently loaded in this project.` | `Run raster utilities on layers currently loaded in this project.` | Shorter |
| `Create a VRT from one or more project raster layers.` | `Build a virtual mosaic from one or more project raster layers.` | Terminology shift |
| `Sharpen a project raster layer using an unsharp mask factor.` | `Sharpen a project raster layer using unsharp masking.` | Cleaner |
| `Create VRT` (dialog title) | `Build Virtual Mosaic` | Consistency |
| `Select raster layers to include in the VRT and choose an output file.` | `Select raster layers for the virtual mosaic and choose an output file.` | Consistency |
| `Output VRT path` | `Output virtual mosaic path` | Clarity |
| `Sharpen Image` (dialog title) | `Sharpen Raster` | Consistency |
| `Input Layer` | Keep | Good |
| `Sharpening Factor` | `Sharpening Strength` | User-friendly |
| `Output Image` | `Output Raster` | GIS specificity |
| `Output GeoTIFF path` | Keep | Good |

## 4.7 Ops Health (Status)

| Current | Recommended (C5ISR) | Notes |
|---|---|---|
| `Stream Status:` | `Tile Stream:` | Specific subsystem |
| `Stream status: idle` | `Tile stream: idle` | Consistency |
| `Runtime Summary:` | `Integration Summary:` | Operator/admin bridge |
| `Runtime summary unavailable.` | `Integration summary unavailable.` | Consistency |

## 4.8 Integrations (Settings)

| Current | Recommended (C5ISR) | Notes |
|---|---|---|
| `Backend Streaming` | `Service Endpoint` | Simpler |
| `Backend API base URL` | `API Endpoint URL` | Clear |
| `N/A (new)` | `Campaign Base Directory` | Global root for managed storage |
| `N/A (new)` | `Managed Campaign Storage` | Default ON; plugin owns file paths |
| `Satellogic` | `High-Res Provider (Satellogic)` | Keep vendor in parentheses |
| `Merlin / CDSE` | `Medium-Res Provider (Merlin / CDSE)` | Same pattern |
| `Auth mode` | `Authentication Method` | User-friendly |
| `Contract ID` | `Access Profile` | Mission framing |
| `STAC URL` | `Catalog URL (STAC)` | Clarify acronym |
| `Auth config ID` | `QGIS Credential Profile` | Less internal |
| `Enable Merlin (Sentinel-2)` | `Enable Medium-Res Feed (Sentinel-2)` | Mission framing |
| `WMTS base URL` | Keep | Technical and precise |
| `WMTS instance ID` | Keep | Technical and precise |
| `WMTS layer ID` | `Default WMTS Layer` | Better action |
| `Remote Existing Layers` | `Remove Existing Layers` | Typo fix |
| `Create New Layer Per Selection` | `Keep Previous Layers on New Selection` | Behavior clarity |
| `Save Settings` | `Save Configuration` | Neutral |
| `Validate Setup` | `Validate Connectivity` | Action + outcome |
| `N/A (new)` | `Open Campaign Folder` | Convenience navigation action |
| `N/A (new)` | `Export Artifacts...` | Explicit external copy action |
| `QGIS auth config id` (placeholder) | `QGIS credential profile id` | Minor polish |
| `http://localhost:8000` (placeholder) | Keep | Useful default |

## 4.9 Collection Campaigns (New UX Surface)

Recommended campaign-level labels:

| Proposed UI Label | Purpose |
|---|---|
| `Campaigns` | Top-level campaign list |
| `Create Campaign` | New campaign action |
| `Campaign Name` | Human-readable campaign title |
| `Mission / Operation` | Mission association |
| `Campaign AOI` | Shared geometry scope |
| `Campaign Window (UTC)` | Shared date/time bounds |
| `Campaign Priority` | Operational urgency |
| `Campaign Status` | Lifecycle state |
| `Current Campaign` | Active campaign context banner/chip |
| `Add to Campaign` | Attach captures/alerts/requests to selected campaign |
| `Campaign Timeline` | Unified chronology across search, requests, alerts, and outputs |
| `Campaign Outputs` | Artifacts and exports |

Recommended campaign sections (inside selected campaign):

1. `Overview`
2. `Collection Plan`
3. `Watch & Alerts`
4. `Requests`
5. `Exploitation`
6. `Timeline`
7. `Outputs`

Campaign-aware phrasing updates:

| Current style | Recommended style |
|---|---|
| `Loaded 12 tasking orders.` | `Loaded 12 requests in campaign.` |
| `No monitoring rows.` | `No watch activity in campaign.` |
| `Workflow execution requested.` | `Pipeline run requested for campaign.` |

## 4.10 Path-Free UX (Managed Filing)

Recommended behavior changes:

1. Remove routine file path fields from operator flows.
2. Auto-generate output paths under campaign folders.
3. Keep only optional display names or artifact tags in forms.
4. Provide separate `Export` action for off-campaign copy.

UI copy mapping for path removal:

| Current | Recommended |
|---|---|
| `Output VRT path` | `Output Name (optional)` |
| `Output GeoTIFF path` | `Output Name (optional)` |
| `Select output file path` | `Output label (optional)` |
| `Browse...` (for internal output selection) | Remove for managed mode |
| `Save Workflow JSON` | `Export Pipeline Definition` (campaign autosave handled internally) |

Operator message examples:

| Current style | Recommended style |
|---|---|
| `Choose an output image file path.` | `Output will be saved in campaign storage automatically.` |
| `Failed to save workflow JSON` | `Failed to export pipeline definition` |
| `Workflow saved: C:\...` | `Pipeline definition saved to campaign records.` |

## 5. Lifecycle Status Translation (Backend -> Operator UI)

## 5.1 Collection Requests (Tasking)

| Backend Status | UI Status | Badge Tone |
|---|---|---|
| `accepted` | `Received` | Info |
| `programming` | `Scheduled` | Info |
| `planned` | `Planned` | Info |
| `collected` | `Collected` | Success |
| `failed` | `Failed` | Error |
| `cancelled` | `Cancelled` | Neutral |
| unknown/other | `Unknown` | Neutral |

Source refs:
- `backend/tests/test_tasking_api.py` (`accepted`, `programming`)
- `backend/app/main.py` tasking normalization and list/detail/create endpoints

## 5.2 Watch and Alert Lifecycle

| Backend Entity/Status | UI Status | Notes |
|---|---|---|
| Subscription `ACTIVE` | `Watch Active` | `monitoring_subscriptions` |
| Subscription `PAUSED` | `Watch Paused` | `monitoring_subscriptions` |
| Event `open` | `New Alert` | Needs analyst action |
| Event `acked` | `Reviewed` | Analyst acknowledged |
| Cue `queued_review` | `Queued for Request Review` | Candidate follow-up |
| Event type `change.candidate` | `Change Candidate` | Human-readable type |

Source refs:
- `backend/app/monitoring_store.py`
- `backend/app/models.py`

## 5.3 Campaign Lifecycle

| Campaign Status | UI Label | Badge Tone |
|---|---|---|
| `draft` | `Draft` | Neutral |
| `active` | `Active` | Info |
| `paused` | `Paused` | Warning |
| `completed` | `Completed` | Success |
| `archived` | `Archived` | Neutral |

Operational rule:
- All requests, watches, alerts, cues, and exploitation runs shown in mission tabs should default to the `Current Campaign` filter.

## 6. UX Recommendations Beyond Renaming

1. Make campaign context explicit and persistent.
- Show `Current Campaign` at top of mission tabs.
- Default mission views to campaign-filtered data.
- Require explicit user action to switch to cross-campaign/global view.

2. Separate operator defaults from admin details.
- Keep `System Log`, auth method internals, raw JSON in collapsible "Advanced" areas.

3. Use guided actions for request creation.
- Geometry source first, then package, then window, then submit.
- Add inline validation labels next to fields, not only modal warnings.

4. Standardize on one object noun in each tab.
- Search: `capture`.
- Requests: `request`.
- Monitoring: `watch`, `alert`, `pending request`.

5. Add persistent status badges in list rows.
- Requests: `Received/Scheduled/Collected/...`
- Alerts: `New/Reviewed`
- Watches: `Active/Paused`

6. Reserve vendor names for integration/admin contexts.
- Keep vendor in parentheses only where source disambiguation is necessary.

7. Use UTC everywhere in operational tabs.
- All date/time labels should explicitly include `(UTC)` where applicable.

## 7. Suggested Rollout Sequence (Copy-Only First)

1. Add `Campaign Base Directory` setting and storage validation wizard.
2. Implement campaign storage service and deterministic folder tree creation.
3. Add `Campaigns` tab and campaign entity scaffold (create/select/current campaign).
4. Add `campaign_id` linkage to requests, watches/alerts, cues, and exploitation runs.
5. Auto-bind QGIS project path to `<base>/campaigns/<campaign_uid>/campaign/campaign.qgs`.
6. Remove routine output path prompts; switch to managed artifact naming.
7. Apply tab and top-level section renames for campaign-centric IA.
8. Apply field/button renames in `Collection Search`, `Collection Requests`, `Watch & Alerts`.
9. Apply workflow terminology (`Input`, `Analytic`, `Run Pipeline`) and campaign-aware wording.
10. Apply lifecycle status translation badges.
11. Move technical/admin terms to `Integrations` and `Ops Health` advanced sections.

## 8. Notes

- This document intentionally does not change functionality.
- It is suitable as a copy spec for implementation tickets.
- If desired, a follow-on can map every string to exact line-level patch targets for `main_dock.py` and `main_dock_workflow.py`.
- Migration recommendation: support legacy/manual-path mode temporarily behind an admin toggle, but default to managed campaign storage.

## 9. Implementation Status (2026-02-20)

Implemented in plugin code:

1. Campaign-managed storage foundation:
- Added persistent settings for managed storage, campaign base directory, campaign UID, and campaign name.
- Added campaign storage service with deterministic campaign tree creation and path allocation.

2. Campaign UI and naming updates:
- Added a top-level `Campaigns` tab with base directory and campaign context controls.
- Updated top-level tab names to mission-oriented labels:
  `Collection Search`, `Collection Requests`, `Watch & Alerts`, `Exploitation`, `Geoprocessing`, `Ops Health`, `Integrations`.
- Applied key C5ISR copy updates in Search/Requests/Watch surfaces.

3. Managed output behavior:
- Utilities (`Create VRT`, `Sharpen Image`) now default to campaign-managed output paths.
- Workflow `clip_to_aoi` and `temporal_stack_to_video` now collect optional output labels instead of filesystem paths.
- Workflow preflight no longer requires explicit output paths for those functions.

4. Campaign file organization:
- Search imagery cache and workflow source cache now resolve to campaign-scoped directories in managed mode.
- Workflow run intermediate/output folders are campaign-scoped.
- QGIS project save target is synchronized to campaign project path in managed mode.
