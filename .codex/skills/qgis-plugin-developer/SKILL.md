---
name: qgis-plugin-developer
description: Backend-first development workflow for the Image Mate QGIS plugin in ./qgis_plugin. Use when implementing, refactoring, debugging, or testing plugin features while keeping UI thin, maximizing reuse, limiting edits to qgis_plugin, documenting plans under ./qgis_plugin/docs/YYYY-MM-DD/, and deriving terminal-only low-bandwidth test cases.
---

# QGIS Plugin Developer

Apply this skill to implement and maintain `./qgis_plugin` with strict backend-first architecture, reuse-first edits, and terminal-first validation.

## Enforce Non-Negotiable Rules

1. Keep backend heavy and frontend dumb.
   Put business logic in backend modules and keep `qgis_plugin/image_mate_qgis_plugin/ui/` as thin orchestration.
2. Maximize code reuse.
   Search and extend existing services, workers, controllers, and helpers before adding new modules.
3. Keep scope inside QGIS plugin only.
   Modify `qgis_plugin/**` only. Do not edit `backend/**`, `frontend/**`, `ml/**`, or other non-QGIS areas.
4. Document design and implementation plans for every meaningful change.
   Store docs in `./qgis_plugin/docs/<YYYY-MM-DD>/`.
5. Derive tests for terminal-only, low-bandwidth operation.
   Validate behavior with CLI probes, deterministic fixtures, logs, and structured outputs. Avoid GUI/image inspection as the primary signal.

## Execute This Workflow

1. Discover reusable code paths first.
   Run `rg` within `qgis_plugin/image_mate_qgis_plugin/` before creating new code.
2. Create a dated design/implementation plan document.
   Run:
   `py -3 .codex/skills/qgis-plugin-developer/scripts/new_design_doc.py --topic "<topic>"`
3. Implement backend-first.
   Prefer these directories for logic:
   - `qgis_plugin/image_mate_qgis_plugin/services/`
   - `qgis_plugin/image_mate_qgis_plugin/simulation/`
   - `qgis_plugin/image_mate_qgis_plugin/workflow_execution/`
   - `qgis_plugin/image_mate_qgis_plugin/workflow_plugins/`
   - `qgis_plugin/image_mate_qgis_plugin/controllers/`
   - `qgis_plugin/image_mate_qgis_plugin/clients/`
4. Keep UI files thin.
   Restrict `qgis_plugin/image_mate_qgis_plugin/ui/` to input gathering, state binding, and rendering.
5. Enforce scope after edits.
   Run:
   `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
6. Derive terminal-first tests from changed files.
   Run:
   `git diff --name-only -- qgis_plugin | py -3 .codex/skills/qgis-plugin-developer/scripts/derive_cli_tests.py`
7. Implement or update CLI checks under `qgis_plugin/test/`.
   Ensure tests run from terminal and emit clear pass/fail exit codes.

## Use Bundled Resources

- Read `references/module_map.md` to map responsibilities and keep UI thin.
- Read `references/terminal_test_patterns.md` to design low-bandwidth checks.
- Use `scripts/new_design_doc.py` to scaffold dated plan docs.
- Use `scripts/check_scope.py` to block out-of-scope edits.
- Use `scripts/derive_cli_tests.py` to generate test checklist candidates from changed files.

## Apply Definition of Done

- Create or update a plan document under `qgis_plugin/docs/<YYYY-MM-DD>/`.
- Keep business logic out of UI modules unless unavoidable, and document any exception.
- Keep all code changes within `qgis_plugin/**`.
- Add or update terminal-only tests for changed behavior.
