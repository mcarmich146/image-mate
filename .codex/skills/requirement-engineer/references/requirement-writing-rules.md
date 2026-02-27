# Requirement Writing Rules

## Use This File

Read this file before creating or reviewing requirement statements.
Use it as the quality gate for "testable and implementable" requirements.

## Required Requirement Fields

| Field | Expectation |
| --- | --- |
| `Requirement ID` | Stable unique ID such as `REQ-F-001` |
| `Type` | Functional, non-functional, or business rule |
| `Statement` | One atomic "shall" statement |
| `Source` | Linked objective ID such as `OBJ-001` |
| `Rationale` | Why this requirement exists |
| `Priority` | Must/Should/Could or P1/P2/P3 |
| `Acceptance Criteria` | Measurable pass/fail conditions |
| `Verification Method` | Test, inspection, analysis, or demo |
| `Owner` | Responsible team or role |

## Requirement Statement Pattern

Use this base format:

`The <system/component> shall <do something measurable> [under <condition>] [within <threshold>].`

Write one behavior per statement.
Split combined requirements into separate IDs.

## Acceptance Criteria Pattern

Use measurable criteria and explicit outcomes.
Prefer one of these forms:

- `Given <context>, when <action>, then <observable result>.`
- `<Metric> is <= or >= <threshold> under <condition>.`
- `<Output artifact> is produced with <required properties>.`

## Avoid These Anti-Patterns

- Avoid vague terms: "fast", "easy", "robust", "user-friendly", "etc.".
- Avoid combined logic in one requirement: "and/or" chains.
- Avoid hidden assumptions not written in the requirement package.
- Avoid implementation lock-in unless the user asked for a specific design.
- Avoid requirements without clear verification evidence.

## Quality Gate Checklist

- Is each requirement atomic and uniquely identified?
- Is each statement unambiguous and measurable?
- Is each requirement feasible within stated constraints?
- Does each requirement map to at least one objective?
- Does each requirement include acceptance criteria?
- Does each requirement include a verification method?
- Is ownership clear for implementation and validation?
- Are assumptions and open questions explicitly listed?

## Example Conversion

Objective:
`OBJ-001: Improve user onboarding completion rate.`

Weak requirement:
`REQ-F-001: The onboarding should be simple and quick.`

Improved requirement:
`REQ-F-001: The system shall allow new users to complete onboarding in <= 3 minutes for the default workflow.`

Acceptance criteria:
- `AC-001: Given a new user with default data, when onboarding starts, then all mandatory steps can be completed in <= 3 minutes.`
- `AC-002: Given onboarding completion, when metrics are logged, then completion duration is captured for analytics.`
