# Time Lapse Full Frame Decode Probe Script Design and Implementation Plan

- Date: 2026-02-26
- Scope: `qgis_plugin/**` only
- Principles:
  - Backend heavy, frontend dumb
  - Maximize code reuse
  - Terminal-only, low-bandwidth testability

## Problem Statement

Need a deterministic, terminal-only way to verify whether a generated time-lapse video is actually corrupted at decode time by reading every frame end-to-end.

Target reproduction input from operator:

- `%USERPROFILE%\Desktop\test.mp4`

## Existing Reusable Components

- Existing smoke test conventions under `qgis_plugin/test/*.py`.
- Existing ffmpeg/ffprobe runtime assumptions already used by time-lapse generation code.

## Proposed Backend Changes

- Add a standalone probe script:
  - `qgis_plugin/test/time_lapse_video_decode_probe.py`
- Script behavior:
  - Run `ffprobe` for reference metadata (`duration`, `nb_frames`, `nb_read_frames`, fps).
  - Run one or more full decode passes using `ffmpeg` `framehash`.
  - Count every decoded frame and verify expected count.
  - Report decode return code, malformed framehash lines, and pass-to-pass hash determinism.
  - Optionally emit machine-readable JSON report.

## UI Wiring Changes (Minimal)

- None.

## Implementation Steps

1. Add CLI script for ffprobe + multi-pass full-frame decode checks.
2. Run against `Desktop/test.mp4` with 5 passes and expected 25 frames.
3. Capture outcomes and integrate into debugging workflow.

## Terminal-Only Test Plan

- Command:
  - `py -3 qgis_plugin/test/time_lapse_video_decode_probe.py "%USERPROFILE%\Desktop\test.mp4" --passes 5 --expected-frames 25`
- Pass criteria:
  - Exit code `0`.
  - Each pass decodes all expected frames.
  - All pass digests match (deterministic decode).
- Observed result on target file:
  - 5/5 passes decoded `25` frames with identical digest.
  - No decode failures observed.

## Risks and Rollback

- Risk: ffmpeg/ffprobe missing from PATH.
  - Mitigation: explicit fail-fast message with exit code `2`.
- Risk: very large files can produce large framehash output.
  - Mitigation: process output stream line-by-line without storing full frame payloads.
- Rollback:
  - Remove `qgis_plugin/test/time_lapse_video_decode_probe.py` if a different probe strategy supersedes it.
