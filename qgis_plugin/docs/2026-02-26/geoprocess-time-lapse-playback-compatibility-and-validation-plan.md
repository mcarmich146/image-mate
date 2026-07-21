# Geoprocess Time Lapse Playback Compatibility And Validation Design and Implementation Plan

- Date: 2026-02-26
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

Operator report: geoprocessing `Generate Time Lapse` output appeared to stop at ~10s and restart, even though the scenario was 5 logical frames with hold=5 at 2 fps (expected 25 frames, 12.5s).

Debug evidence from campaign log (`.../campaigns/tma_bluetech_mission/logs/image_mate_qgis_20260227T043159Z.log`) shows:

- Request normalized to `frames=5`, `fps=2`.
- Render step produced 5 logical frames with `hold=5`.
- Completion log reported `sequence_frames=25`.

Direct stream probe of the produced output (`%USERPROFILE%\\Desktop\\test.mp4`) confirms:

- `duration=12.500000`
- `nb_read_frames=25`
- `avg_frame_rate=2/1`

Therefore, the produced file is structurally complete. The most likely compatibility issue is decoder behavior with reordered H.264 timestamps from B-frames at low frame rates.

## Existing Reusable Components

- `services/time_lapse_video_service.py`
  - Existing geoprocessing time-lapse render + ffmpeg encode path.
- `workflow_execution/worker.py`
  - Existing ffprobe sanity-check pattern for video outputs.
- `test/time_lapse_video_service_smoke.py`
  - Existing terminal-only smoke test entrypoint for non-QGIS helper logic.

## Proposed Backend Changes

- Update geoprocessing time-lapse ffmpeg encode options to disable B-frames:
  - Add `-bf 0` to produce monotonic DTS/PTS behavior for broader player compatibility.
- Add explicit encode expectation logging:
  - Log `sequence_frames` and expected duration before encode.
- Add post-encode ffprobe sanity check in `TimeLapseVideoService`:
  - Probe measured duration/frame count.
  - Fail fast when measured stream is materially shorter than expected.
  - Log measured duration/frame count/fps when sanity check passes.
- Add reusable probe payload parser helper:
  - `_parse_video_probe_payload(...)` to keep probe logic testable without ffprobe runtime dependency.

## UI Wiring Changes (Minimal)

- None.
- Keep current dialog/payload flow unchanged.

## Implementation Steps

1. Confirm incident telemetry in campaign debug logs for the reported run.
2. Validate produced MP4 with `ffprobe` to establish observed vs expected duration/frame count.
3. Patch `TimeLapseVideoService` encode command and add post-encode probe validation/logging.
4. Extend smoke tests for probe payload parsing and fallback behavior.
5. Run terminal smoke tests and scope checks.

## Terminal-Only Test Plan

- Run:
  - `py -3 qgis_plugin/test/time_lapse_video_service_smoke.py`
- Validate:
  - Frame/fps normalization still passes.
  - Probe payload parsing returns deterministic duration/frame fields.
  - Invalid probe payload returns `None`.
- Manual probe for incident artifact:
  - `ffprobe -count_frames ... test.mp4` to confirm 25 frames and 12.5s duration.

## Risks and Rollback

- Risk: disabling B-frames can increase output size in some scenes.
  - Mitigation: keep the rest of the codec settings unchanged (`libx264`, `yuv420p`, `+faststart`) to limit behavioral drift.
- Risk: ffprobe may be unavailable in some environments.
  - Mitigation: sanity check logs warning and skips strict validation when probing is unavailable.
- Rollback:
  - Remove `-bf 0` and post-encode probe block from `time_lapse_video_service.py` if compatibility regression is reported.
