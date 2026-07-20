# Traceability Matrix Guide

## Use This File

Read this file when creating or validating a Requirement Traceability Matrix (RTM).
Apply it to guarantee end-to-end coverage from objective to verification.

## Minimum RTM Columns

| Column | Purpose |
| --- | --- |
| `Objective ID` | Source objective such as `OBJ-001` |
| `Objective Statement` | Concise objective text |
| `Requirement ID` | Child requirement such as `REQ-F-003` |
| `Requirement Type` | Functional, non-functional, or business rule |
| `Requirement Statement` | Atomic requirement text |
| `Acceptance Criteria IDs` | Linked criteria IDs such as `AC-007;AC-008` |
| `Verification ID` | Test case or validation item such as `TC-022` |
| `Verification Method` | Test, inspection, analysis, or demo |
| `Implementation Owner` | Team or role accountable for delivery |
| `Test Owner` | Team or role accountable for validation |
| `Status` | Proposed, approved, implemented, validated |
| `Notes` | Risks, assumptions, or exceptions |

## Traceability Rules

- Map every `OBJ-*` to one or more `REQ-*`.
- Map every `REQ-*` to one or more `AC-*`.
- Map every `REQ-*` to at least one verification item.
- Keep IDs stable across revisions.
- Capture orphan items as explicit gaps, not hidden omissions.

## Coverage Checks

- Forward check: Every objective has requirement coverage.
- Forward check: Every requirement has verification coverage.
- Backward check: Every test maps to a valid requirement.
- Backward check: Every requirement maps to a valid objective.
- Status check: Mark blocked rows with reason and owner.

## Common Failure Modes

- Requirements exist without objective linkage.
- Acceptance criteria are written but not mapped in RTM.
- Tests validate implementation details instead of requirement outcomes.
- IDs change between versions and break historical traceability.
- Non-functional requirements are omitted from verification mapping.

## Change Management Rules

- Add new rows for new requirements, do not overwrite history silently.
- Update status fields instead of deleting rows.
- If a requirement is retired, keep row and mark `Status=retired`.
- Track impacted tests whenever requirement text changes.
