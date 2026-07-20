# Asset Intel Add Asset Search Selectors Design and Implementation Plan

- Date: 2026-02-25
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

The `Asset Intel -> Asset Query -> Add Asset` dialog currently uses free-text inputs for profile/taxonomy fields and does not expose dedicated `Sub Domain 1` / `Sub Domain 2` fields. Operators need:

1. `Sub Domain 1` and `Sub Domain 2` in the Add/Modify Asset form.
2. Search/select UX for `Domain`, `Sub Domain 1`, `Sub Domain 2`, `Type`, `Origin`, `Proliferation`, and `Builder`.
3. Ability to type and submit new values when the desired option is not present in facet lists.

## Existing Reusable Components

- `AssetIntelService.list_facets()` already provides facet rows for:
  - `domain_main`, `sub_domain_1`, `sub_domain_2`, `type`, `origin`, `proliferation`, `builder`
- `ImageMateMainDock.set_asset_intel_facets(...)` already receives and stores facet payloads.
- `AssetIntelService._replace_taxonomy(...)` already writes taxonomy rows and token ordering for domain path logic.

## Proposed Backend Changes

- Add reusable normalization helpers in `asset_intel_service.py`:
  - `split_domain_tokens(...)`
  - `normalize_domain_hierarchy(...)`
- Use normalized hierarchy in:
  - `_upsert_asset_profile(...)` to keep `asset_profile.domain` canonical.
  - `_replace_taxonomy(...)` to write ordered domain tokens consistently.
- Extend `get_asset_detail(...)` payload with:
  - `sub_domain_1`
  - `sub_domain_2`
  so the Modify dialog pre-fills new fields.

## UI Wiring Changes (Minimal)

- Keep query filter widgets unchanged.
- Update only Add/Modify Asset editor dialog fields:
  - Replace free-text profile/taxonomy line edits with editable searchable selector combos.
  - Add new `Sub Domain 1` and `Sub Domain 2` selector rows.
  - Keep typed (non-listed) values in payload to support create-new behavior.
- Keep UI thin:
  - UI collects values only.
  - Domain path normalization and persistence remain in service layer.

## Implementation Steps

1. Implement domain hierarchy helper functions in service.
2. Apply helpers in profile/taxonomy persistence paths.
3. Add sub-domain values to detail payload.
4. Add reusable editor selector-combo builders in `main_dock.py`.
5. Update Add/Modify dialog field wiring and payload mapping.
6. Add terminal smoke test for hierarchy normalization.

## Terminal-Only Test Plan

- `py -3 qgis_plugin/test/asset_intel_domain_hierarchy_smoke.py`
  - validates domain token splitting
  - validates explicit domain/sub-domain composition
  - validates fallback and explicit-clear behavior
- `py -3 -m py_compile ...` for changed Python modules.

## Risks and Rollback

- Risk: Existing assets may have legacy comma-joined domain values.
  - Mitigation: service fallback parsing + canonical rewrite on update.
- Risk: Editable combos could unintentionally drop typed values during dependent type-list refresh.
  - Mitigation: preserve current typed value when refreshing type options.
- Rollback:
  - Revert `asset_intel_service.py`, `main_dock.py`, and the new smoke test file.
