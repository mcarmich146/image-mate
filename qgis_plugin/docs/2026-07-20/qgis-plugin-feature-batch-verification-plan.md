# QGIS Plugin Feature Batch Verification Note

- Date: 2026-07-20
- Scope: `qgis_plugin/**` only
- Change set: accumulated plugin work documented under `qgis_plugin/docs/2026-02-26/`
  through `qgis_plugin/docs/2026-05-05/`

## Scope and Context

This note records commit-time verification for the accumulated QGIS plugin feature
batch. The batch covers time-lapse video generation, mosaic tasking and tracking,
side-by-side map comparison, collection search and download behavior, vessel
detection/training, and finite-variable-angle strip planning utilities. It does
not change code outside `qgis_plugin/**`.

## Implementation Summary

Business and integration logic is concentrated in `services/`, `clients/`,
`controllers/`, and `mixins/`. UI changes in `ui/` and `plugin.py` connect those
services to plugin actions and state. Terminal smoke tests under
`qgis_plugin/test/` cover the new service contracts and static wiring. The dated
feature plans in the directories listed above remain the canonical design and API
behavior records for each work item.

Generated replay images under `qgis_plugin/test/_artifacts/` and generated
`qgis_plugin/scripts/utils/tmp_*.geojson` outputs are intentionally excluded from
the commit. The reusable `linear_polygon.geojson` fixture is included.

## Decisions

- Keep the accumulated changes in one commit because the implementations, tests,
  fixture, and dated plans are already interdependent in the current worktree.
- Preserve the tracked vessel prototype SQLite update as part of the vessel
  workflow changes.
- Exclude generated outputs so verification can recreate them without adding
  unstable binary and GeoJSON noise to source control.

## Verification Evidence

1. Command: `py -3 -m compileall -q qgis_plugin/image_mate_qgis_plugin qgis_plugin/scripts qgis_plugin/test`
   Expectation: Every Python source file compiles without a syntax error.
   Observed: Exit code 0 with no error output.
   Interpretation: Pass.
2. Command: run the 17 new deterministic `*_smoke.py` scripts covering
   side-by-side mode, Explore workflows, strip planning, mosaic workflows,
   time-lapse service behavior, and vessel workflows.
   Expectation: Every script exits with code 0 and prints its pass marker.
   Observed: `ALL_PASS count=17`; strip tests reported zero uncovered area.
   Interpretation: Pass.
3. Command: `git diff --name-only | py -3 .codex/skills/qgis-plugin-developer/scripts/check_scope.py`
   Expectation: All tracked changes remain under `qgis_plugin/**`.
   Observed: `[OK] All 72 path(s) are within allowed scope: qgis_plugin` for the
   final staged change set.
   Interpretation: Pass.
4. Command: `git diff --check`
   Expectation: No whitespace errors.
   Observed: Initial whitespace defects were removed; the final staged check
   exited with code 0 and no findings.
   Interpretation: Pass.

## Risks, Mitigations, and Follow-ups

- Risk: QGIS GUI interactions were not exercised by the terminal suite.
  Mitigation: Backend contracts and UI-to-service wiring have deterministic smoke
  coverage. Follow-up owner: repository owner; run an interactive QGIS acceptance
  pass before release, target 2026-07-27.
- Not run: `qgis_plugin/test/time_lapse_video_decode_probe.py` because it requires
  a caller-supplied video file. Follow-up owner: repository owner; run against the
  intended release video fixture before release, target 2026-07-27.
- Not run: `qgis_plugin/test/mosaic_tracking_telluric_replay_debug.py` because it
  is a credentialed replay diagnostic, not a deterministic smoke test. Follow-up
  owner: repository owner; run only when investigating live Telluric parity.
