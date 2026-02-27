# Documentation Update Matrix

Use this matrix to map code changes to required documentation updates.

## Quick Procedure

1. Collect changed files with `git diff --name-only`.
2. Run `git diff --name-only | py -3 .codex/skills/documentation-engineer/scripts/derive_doc_updates.py`.
3. Apply the matrix below.
4. Confirm coverage before finishing the task.

## Matrix

| Change Type | Required Documentation Updates | Typical Targets |
| --- | --- | --- |
| New feature or major behavior change | Dated note + canonical feature docs | `docs/YYYYMMDD/*`, `README.md`, relevant `docs/*.md` |
| Bug fix with behavioral impact | Dated note + affected module docs | `docs/YYYYMMDD/*`, module-specific docs |
| API request/response/contract change | Dated note + API contract docs | API docs, endpoint examples, schema docs |
| Data model or migration change | Dated note + schema/migration docs | Schema references, migration notes |
| Infrastructure/dependency/config change | Dated note + setup/runbook docs | Setup guides, deployment docs, ops runbooks |
| Test-only change with unchanged behavior | Dated note if non-trivial; update testing docs if process changes | `docs/YYYYMMDD/*`, testing guidance docs |
| QGIS plugin change | Plugin dated note + plugin-specific docs | `qgis_plugin/docs/YYYY-MM-DD/*` |
| Skill change under `.codex/skills/` | Update SKILL workflow and references | `.codex/skills/<skill>/SKILL.md`, references |

## Coverage Rules

1. If non-doc files changed, at least one documentation file must also change.
2. If behavior changed, update canonical docs in the same change set.
3. If docs are intentionally deferred, record owner and due date in the dated note.
