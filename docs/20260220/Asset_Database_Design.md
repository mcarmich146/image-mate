# Asset Intel Database Design (2026-02-20)

## Goal
Expose Vessel DB content in QGIS for operational analysis with two distinct system scopes:

- Onboard systems for each vessel/class record.
- Fielded units identified by pennant number (higher-priority workflow).

## Current Snapshot (Reparse-First Baseline)

### Parse run (completed)
- Command:
  - `py -3 qgis_plugin\test\playground\parse_vessel_db_prototype.py --max-pages 100 --force`
- Output DB:
  - `qgis_plugin/test/playground/asset_intel_prototype.sqlite`
- Summary:
  - `unique_page_count=100`
  - `asset_count=37`
  - `section_count=395`
  - `system_count=187`
  - `system_attribute_count=1029`

### Design implication
- We will use a reparse-first approach and evolve parser output/schema directly.
- No legacy DB migration path is required for this phase.

## Scope Definitions

### Onboard System
- Technical capability installed on a vessel/class.
- Examples: propulsion, radar, sonar, fire control, onboard aviation.
- Source of truth: parsed sections + attributes.

### Fielded Unit (Pennant-Centric)
- Real-world unit/ship instance with one or more identifiers.
- Primary identifier is usually pennant number.
- This is the primary analyst workflow for "individual systems out there."

## UX Design

### Asset Intel Layout
1. Query panel:
- Free-text query.
- Facets: Domain, Type, Origin, Proliferation, Builder.
- Result limit and Search/Reset.

2. Asset CRUD controls:
- Add Asset, Modify Asset, Delete Asset.

3. Result list:
- Asset identity rows; selection drives detail pane.

4. Detail tabs (ordered):
- Overview.
- Systems.
- Analyst Notes.
- Raw.
- Sources.

### Systems Tab (Dual Scope)
- Replace single systems table with two sub-tabs:
  - `Fielded Units (Pennants)` (default tab).
  - `Onboard Systems`.

### Fielded Units (Pennants) UX (Primary)
- Top filter row:
  - Exact/contains search for pennant.
  - Optional identifier-type filter.
  - Optional status filter.
- Main table columns:
  - Primary ID, Unit Name, Parent Asset, Type, Origin, Linked Systems, Notes.
- Detail pane:
  - Full identifier list.
  - Linked onboard systems and fit/status.
  - Unit-scoped note timeline.

### Onboard Systems UX (Secondary)
- Keep current systems table behavior:
  - Name, category, summary, pages, note count.
- Attribute table remains as technical detail view.
- Add linkage indicator to show whether selected fielded unit carries each system.

### Analyst Notes UX
- Note target options:
  - Asset.
  - Onboard system.
  - Fielded unit (pennant entity).

## Data Model

### Existing Foundation (keep)
- `asset`
- `asset_taxonomy`
- `section_instance`
- `asset_attribute_value`
- `asset_text_block`
- `asset_source_link`
- `import_batch`
- `asset_profile`
- `asset_dimension`
- `asset_system`
- `asset_system_attribute`
- `analyst_note`

### New Core Tables (parser-populated, no migration path required)
- `fleet_unit`
  - One row per fielded unit under an `asset_id`.
  - Suggested columns: `id`, `asset_id`, `display_name`, `status`, `source`, `created_utc`, `updated_utc`.

- `fleet_unit_identifier`
  - One-to-many identifiers per `fleet_unit`.
  - Suggested columns:
    - `id`, `unit_id`
    - `identifier_type` (`pennant`, `hull`, `imo`, `mmsi`, `callsign`, `other`)
    - `identifier_raw`, `identifier_norm`
    - `is_primary`, `confidence`
    - timestamps
  - Indexes:
    - unique: (`identifier_type`, `identifier_norm`)
    - lookup: (`unit_id`)

- `fleet_unit_system_fit`
  - Links fielded unit to onboard systems.
  - Suggested columns:
    - `id`, `unit_id`, `system_id`
    - `fit_status` (`installed`, `planned`, `removed`, `unknown`)
    - `quantity`, `effective_from`, `effective_to`
    - `source`, timestamps
  - Indexes:
    - unique: (`unit_id`, `system_id`)

### Analyst Note Target Expansion
- Extend `analyst_note` with nullable `fleet_unit_id`.
- Validation rule:
  - At least one of `asset_id`, `system_id`, `fleet_unit_id` is present.
- Search should include note text/tags across all three scopes.

## Parsing and Normalization Rules

### Onboard Systems
- Keep existing section-based extraction into `asset_system` and `asset_system_attribute`.

### Fielded Units
- During parse/sync, detect identifier keys in attributes:
  - Primary examples: `Pennant Number`.
  - Normalize common typo/alias: `Pendent` -> `pennant`.
- Normalize identifier text for search keys:
  - trim, uppercase, collapse spaces, preserve `-` and `/`.
- Create/update `fleet_unit` + `fleet_unit_identifier`.

### Unit-System Linking
- Initial linkage policy:
  - If explicit fit data exists, create specific `fleet_unit_system_fit`.
  - If not explicit, either:
    - leave unlinked, or
    - link to class onboard systems as `unknown`.
- Recommendation:
  - Default to explicit-only links in first implementation to avoid false precision.

## Query and Service Design

### Search
- Keep asset search.
- Add pennant-first unit search path:
  - exact normalized match first.
  - fallback to contains.

### Detail Payload
- Asset detail should include:
  - `onboard_systems` (existing shape).
  - `fielded_units` (new).
  - optional `unit_system_fit` entries.

### Filters/Facets
- Add optional unit-level facets:
  - identifier type.
  - unit status.
  - has linked systems.

## Plugin Architecture Touchpoints

### Service Layer
`qgis_plugin/image_mate_qgis_plugin/services/asset_intel_service.py`

- Schema ensure for new unit tables.
- Parser-sync methods for unit extraction and linking.
- Unit search/detail queries and note CRUD validation.

### UI Layer
`qgis_plugin/image_mate_qgis_plugin/ui/main_dock.py`

- Systems tab split into `Fielded Units (Pennants)` and `Onboard Systems`.
- Pennant-first table, detail pane, and note target integration.

### Plugin Wiring
`qgis_plugin/image_mate_qgis_plugin/plugin.py`

- Signal handlers for unit search/select and unit-scoped note actions.

## Completion Criteria
- Analysts can review both onboard systems and pennant-tracked fielded units.
- Pennant lookup is first-class and fast (exact + contains).
- Notes can be attached to asset, onboard system, or fielded unit.
- Reparse produces a complete DB with new unit tables from source PDF (no migration dependency).
