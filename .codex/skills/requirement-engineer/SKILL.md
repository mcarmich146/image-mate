---
name: requirement-engineer
description: Break high-level product or business objectives into clear, testable, implementable requirements and produce a requirement traceability matrix (RTM). Use when objectives, epics, PRDs, stakeholder asks, or roadmap items are ambiguous and must be translated into requirement IDs, acceptance criteria, verification methods, and coverage mapping from objective to requirement to test.
---

# Requirement Engineer

Convert ambiguous objectives into an actionable requirements package and a complete RTM.

## Execute This Workflow

1. Frame the objective.
Extract business outcome, target users, scope boundaries, constraints, timeline, and success metrics.
Record missing information as explicit assumptions (`ASM-###`) and open questions (`Q-###`).

2. Build a requirement structure.
Decompose into capabilities and assign stable IDs:
- Objectives: `OBJ-###`
- Functional requirements: `REQ-F-###`
- Non-functional requirements: `REQ-NF-###`
- Business rules: `REQ-BR-###`
Keep each requirement atomic and independently testable.

3. Write high-quality requirement statements.
Use one behavior per statement in "The system shall ..." form.
Include actor, condition, and measurable result.
Move detailed criteria into acceptance criteria, not into vague prose.
Read `references/requirement-writing-rules.md` before drafting large sets.

4. Define verification for every requirement.
Attach acceptance criteria (`AC-###`) and at least one verification entry (`TC-###` or inspection, analysis, or demo method).
Specify verification type, owner, and objective evidence.

5. Produce the RTM.
Use `assets/requirement-traceability-matrix-template.csv`.
Ensure each row links `Objective -> Requirement -> Acceptance Criteria -> Verification`.
Read `references/traceability-matrix-guide.md` for required columns and coverage checks.

6. Run the quality gate.
Validate clarity, feasibility, and testability with the checklist in `references/requirement-writing-rules.md`.
Report unresolved gaps, risks, and change impacts.

## Output Package

Return artifacts in this order:

1. Objective summary (scope, outcome, constraints)
2. Assumptions and open questions
3. Requirements list/table with IDs and rationale
4. Acceptance criteria by requirement
5. Requirement traceability matrix
6. Coverage gaps and recommended next actions

## Use Bundled Resources

- `references/requirement-writing-rules.md`: Statement patterns, anti-patterns, and quality checklist.
- `references/traceability-matrix-guide.md`: RTM schema, validation rules, and common failure modes.
- `assets/requirements-package-template.md`: Reusable output template for requirements documents.
- `assets/requirement-traceability-matrix-template.csv`: Reusable RTM starter file.

## Apply Definition Of Done

- Every objective maps to one or more requirements.
- Every requirement has a unique ID, rationale, and measurable acceptance criteria.
- Every requirement maps to at least one verification method.
- RTM contains no orphan objectives, requirements, or tests.
- Assumptions, open questions, and out-of-scope items are explicit.
