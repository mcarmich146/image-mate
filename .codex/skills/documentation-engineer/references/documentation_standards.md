# Documentation Standards

Use this reference to maintain high-signal engineering documentation.

## Core Principles

1. Optimize for reproducibility, not storytelling.
2. Make behavior changes discoverable from canonical docs.
3. Record decisions and tradeoffs, not only outcomes.
4. Keep one source of truth per topic and remove stale duplicates.
5. State uncertainty explicitly with owner and follow-up date.

## Minimum Content for a Dated Engineering Note

1. Scope: exact boundaries of what changed and what did not.
2. Context: why the work matters now.
3. Plan: intended approach before implementation.
4. Implementation summary: what actually changed.
5. Decisions: alternatives considered and rationale.
6. Verification evidence: commands, data, and observed results.
7. Risks and mitigations: failure modes and controls.
8. Follow-ups: concrete action items with owner/date.

## Writing Rules

1. Use precise dates (`YYYY-MM-DD`) and concrete file paths.
2. Prefer active voice and direct statements.
3. Keep sections short and scannable.
4. Replace vague terms ("fixed", "improved") with specific behavior changes.
5. Mark speculative statements with `Assumption:` or `Risk:`.
6. Link related docs instead of repeating full context.

## Verification Evidence Standard

Use this format:

1. `Command:` exact command line used.
2. `Expectation:` what should happen.
3. `Observed:` what actually happened.
4. `Interpretation:` pass/fail and why.

If a command was not executed, write `Not run:` with reason.

## Canonical Docs to Update

1. Update `README.md` when setup, workflow, or user-facing behavior changes.
2. Update component docs when internal architecture or module responsibilities change.
3. Update API contract docs when endpoints, payloads, or semantics change.
4. Update runbooks when deployment, operations, monitoring, or recovery changes.
5. Update migration/schema docs when data structures or assumptions change.

## Review Checklist

- Does every meaningful code/config change map to at least one doc update?
- Can another engineer reproduce the verification steps from docs alone?
- Are key decisions and tradeoffs written down?
- Are risks and follow-ups explicit with owner and target date?
- Are outdated statements removed or corrected?
