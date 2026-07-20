---
name: software-engineer
description: Implementation workflow for translating requirement-engineer handoffs into production-ready software with clean architecture, strong test coverage, clear traceability, and long-term maintainability. Use when implementing new features from formal requirements, turning acceptance criteria into code and tests, refactoring systems to satisfy updated requirements, or delivering high-confidence changes that must remain easy to evolve.
---

# Software Engineer

Apply this skill to convert requirement-engineer outputs into well-architected, maintainable software without losing requirement intent.

## Enforce Delivery Contract

1. Treat requirement-engineer artifacts as the source of truth.
   Use requirement IDs, acceptance criteria, constraints, and non-functional targets as implementation anchors.
2. Close ambiguity before coding.
   Surface missing assumptions, edge cases, and conflicting criteria early.
3. Preserve requirement-to-code traceability.
   Map each requirement to implementation decisions and tests.
4. Prefer clarity over cleverness.
   Optimize for readable modules, explicit interfaces, and predictable behavior.
5. Keep architecture stable while changing behavior.
   Extend existing seams first; add new abstractions only when reuse and coupling analysis justify them.
6. Build quality in from the first commit.
   Ship tests, observability, and documentation alongside code, not as follow-up work.

## Execute Workflow

1. Build a requirement implementation map.
   Extract goals, in-scope behaviors, out-of-scope boundaries, non-functional requirements, and acceptance criteria.
   Use [handoff-contract.md](references/handoff-contract.md) to check handoff completeness.
2. Design before implementation.
   Define module boundaries, dependency direction, data contracts, failure handling, and migration strategy.
   Record major tradeoffs and keep decisions auditable.
3. Slice work into vertical increments.
   Plan each slice to include code, tests, and rollout safety.
   Prioritize the thinnest end-to-end path that proves value and de-risks architecture.
4. Implement with maintainability standards.
   Keep functions cohesive and side effects explicit.
   Isolate external integrations behind clear adapters.
   Protect invariants with guard clauses and typed/domain-specific structures.
5. Verify behavior and regressions.
   Add or update unit, integration, and contract tests to cover acceptance criteria and critical edge cases.
   Include negative-path tests for failures, retries, validation errors, and data inconsistencies.
6. Prepare operational readiness.
   Add actionable logs, metrics, and health signals where failures matter.
   Document feature flags, backward compatibility choices, and rollback path when applicable.
7. Run final quality gates.
   Use [quality-gate.md](references/quality-gate.md) before completion.
   Do not declare done while any critical gate fails.

## Implementation Standards

- Enforce single responsibility at module/class level.
- Keep dependency flow one-way (entrypoints -> domain/application -> infrastructure).
- Hide framework details at boundaries; keep core logic framework-agnostic where practical.
- Make behavior explicit with stable interfaces and typed contracts.
- Avoid speculative abstractions; introduce patterns only after repeated need.
- Favor composition over deep inheritance.
- Keep naming domain-oriented and intention-revealing.
- Remove dead code and temporary scaffolding before completion.

## Testing and Evidence Rules

- Translate every acceptance criterion into at least one deterministic test or verifiable check.
- Keep the test pyramid balanced: many fast unit tests, targeted integration tests, minimal end-to-end tests.
- Add regression tests for every bug fix.
- Ensure tests are readable and encode business rules, not implementation trivia.
- Report delivery evidence as a compact matrix: requirement ID -> code location -> test coverage.

## Use Bundled References

- Read [handoff-contract.md](references/handoff-contract.md) when receiving or reviewing requirement-engineer outputs.
- Read [quality-gate.md](references/quality-gate.md) before finalizing implementation.

## Definition of Done

- Requirement coverage is complete and traceable.
- Architecture remains coherent and easier to change than before.
- Automated tests pass and meaningfully protect critical behavior.
- Operational signals and failure handling are present for risky paths.
- Documentation reflects final behavior and key design decisions.
