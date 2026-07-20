---
name: documentation-engineer
description: End-to-end engineering documentation workflow for the image-mate repository. Use when planning, implementing, debugging, refactoring, reviewing, or releasing changes that must be documented with durable records, including design notes, implementation logs, decision records, verification evidence, and operational updates.
---

# Documentation Engineer

Maintain complete, accurate documentation for each engineering change. Treat docs as part of definition-of-done, not a post-hoc summary.

## Enforce Documentation Quality Bar

1. Capture intent, implementation details, decisions, verification, and follow-ups.
2. Keep canonical documentation synchronized with behavior changes in the same change set.
3. Prefer one source of truth per topic; update existing docs before creating new duplicates.
4. Store work-item notes under `docs/YYYYMMDD/` unless a component has stricter conventions.
5. Record assumptions, risks, and unresolved questions explicitly.
6. Use exact file paths, commands, and dates so another engineer can reproduce the work.

## Execute Workflow

1. Discover the full change surface first.
   - Run `git diff --name-only`.
   - Run `git diff --name-only | py -3 .codex/skills/documentation-engineer/scripts/derive_doc_updates.py`.
2. Create or update a dated engineering note.
   - Run `py -3 .codex/skills/documentation-engineer/scripts/new_doc_packet.py --topic "<topic>"`.
   - Use `assets/templates/engineering_note_template.md` as the default structure.
3. Update canonical docs before publishing summary notes.
   - `README.md` and component docs for setup/workflow changes.
   - Architecture/API docs for behavior or contract changes.
   - Runbooks for operational, deployment, and recovery changes.
4. Write documentation to meet quality standards.
   - Apply `references/documentation_standards.md`.
   - Apply `references/doc_update_matrix.md` to map change types to required docs.
5. Verify documentation coverage and accuracy.
   - Ensure each meaningful non-doc file change is reflected by at least one doc update.
   - Ensure documented commands were run or clearly marked unverified.
6. Report documentation status in delivery notes.
   - List updated docs and what each one covers.
   - List deferred documentation with owner and target date.

## Use Bundled Resources

- Read `references/documentation_standards.md` for writing and evidence standards.
- Read `references/doc_update_matrix.md` to decide which docs to update by change type.
- Use `scripts/new_doc_packet.py` to scaffold dated notes quickly.
- Use `scripts/derive_doc_updates.py` to infer documentation work from changed files.
- Use `assets/templates/engineering_note_template.md` for consistent note structure.

## Definition of Done

- At least one dated note exists for each non-trivial work item.
- Canonical docs reflect behavior/API/ops changes.
- Verification commands and outcomes are documented.
- Risks and follow-ups are documented with clear ownership.
