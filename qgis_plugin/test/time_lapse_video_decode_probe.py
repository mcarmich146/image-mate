#!/usr/bin/env python3
"""Decode every frame from a video and report deterministic integrity signals."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


def _to_int(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower() in {"n/a", "nan"}:
        return None
    try:
        return int(text)
    except Exception:
        return None


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower() in {"n/a", "nan"}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _run_ffprobe(ffprobe_bin: str, video_path: Path) -> dict[str, Any]:
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=duration,nb_frames,nb_read_frames,avg_frame_rate,r_frame_rate,codec_name,profile",
        "-show_entries",
        "format=duration,size,bit_rate",
        "-of",
        "json",
        str(video_path),
    ]
    process = subprocess.run(command, capture_output=True, text=True)
    if int(process.returncode) != 0:
        raise RuntimeError(f"ffprobe failed: {str(process.stderr or '').strip() or 'unknown error'}")
    try:
        payload = json.loads(str(process.stdout or "").strip() or "{}")
    except Exception as exc:
        raise RuntimeError(f"ffprobe output parse failed: {exc}") from exc

    stream = {}
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if isinstance(streams, list) and streams and isinstance(streams[0], dict):
        stream = streams[0]
    fmt = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    if not isinstance(fmt, dict):
        fmt = {}

    duration_s = _to_float(stream.get("duration"))
    if duration_s is None:
        duration_s = _to_float(fmt.get("duration"))

    nb_frames = _to_int(stream.get("nb_frames"))
    nb_read_frames = _to_int(stream.get("nb_read_frames"))

    return {
        "codec_name": str(stream.get("codec_name") or "").strip(),
        "profile": str(stream.get("profile") or "").strip(),
        "avg_frame_rate": str(stream.get("avg_frame_rate") or "").strip(),
        "r_frame_rate": str(stream.get("r_frame_rate") or "").strip(),
        "duration_s": float(duration_s or 0.0),
        "nb_frames": int(nb_frames or 0),
        "nb_read_frames": int(nb_read_frames or 0),
        "file_size_bytes": int(_to_int(fmt.get("size")) or 0),
        "bit_rate": int(_to_int(fmt.get("bit_rate")) or 0),
    }


def _decode_with_framehash(ffmpeg_bin: str, video_path: Path) -> dict[str, Any]:
    command = [
        ffmpeg_bin,
        "-v",
        "error",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-vsync",
        "0",
        "-f",
        "framehash",
        "-hash",
        "sha256",
        "-",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    assert process.stderr is not None

    frame_count = 0
    non_monotonic_pts = 0
    non_monotonic_dts = 0
    missing_dts = 0
    malformed_lines = 0
    last_pts = None
    last_dts = None
    digest = hashlib.sha256()
    first_pts = None
    last_pts_seen = None
    first_hash = ""
    last_hash = ""

    for raw_line in process.stdout:
        line = str(raw_line or "").strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 6:
            malformed_lines += 1
            continue
        dts = _to_int(parts[1])
        pts = _to_int(parts[2])
        frame_hash = str(parts[5] or "").strip()

        frame_count += 1
        if frame_count == 1:
            first_hash = frame_hash
        last_hash = frame_hash
        digest.update((frame_hash + "\n").encode("ascii", errors="ignore"))

        if pts is not None:
            if first_pts is None:
                first_pts = pts
            if last_pts is not None and pts < last_pts:
                non_monotonic_pts += 1
            last_pts = pts
            last_pts_seen = pts

        if dts is None:
            missing_dts += 1
        else:
            if last_dts is not None and dts < last_dts:
                non_monotonic_dts += 1
            last_dts = dts

    stderr_text = process.stderr.read()
    return_code = int(process.wait())
    error_lines = [line.strip() for line in str(stderr_text or "").splitlines() if str(line or "").strip()]

    return {
        "return_code": return_code,
        "frame_count": frame_count,
        "missing_dts": missing_dts,
        "non_monotonic_pts": non_monotonic_pts,
        "non_monotonic_dts": non_monotonic_dts,
        "malformed_lines": malformed_lines,
        "first_pts": first_pts,
        "last_pts": last_pts_seen,
        "first_hash": first_hash,
        "last_hash": last_hash,
        "frame_hash_digest": digest.hexdigest(),
        "error_lines": error_lines,
    }


def _expected_frame_count(probe: dict[str, Any], cli_expected_frames: int) -> int:
    if int(cli_expected_frames or 0) > 0:
        return int(cli_expected_frames)
    counts = [int(probe.get("nb_read_frames") or 0), int(probe.get("nb_frames") or 0)]
    return max(counts)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decode every frame from a video and validate read integrity with ffmpeg framehash."
    )
    parser.add_argument("video_path", help="Path to video file to probe.")
    parser.add_argument(
        "--passes",
        type=int,
        default=3,
        help="How many full decode passes to run (default: 3).",
    )
    parser.add_argument(
        "--expected-frames",
        type=int,
        default=0,
        help="Optional expected frame count. If omitted, script uses ffprobe metadata.",
    )
    parser.add_argument(
        "--strict-timestamps",
        action="store_true",
        help="Fail when DTS/PTS anomalies are detected.",
    )
    parser.add_argument(
        "--report-json",
        default="",
        help="Optional output path for JSON report.",
    )
    args = parser.parse_args()

    video_path = Path(str(args.video_path or "").strip()).expanduser().resolve()
    if not video_path.exists() or not video_path.is_file():
        print(f"[FAIL] video file not found: {video_path}")
        return 2

    ffmpeg_bin = shutil.which("ffmpeg")
    ffprobe_bin = shutil.which("ffprobe")
    if not ffmpeg_bin or not ffprobe_bin:
        print("[FAIL] ffmpeg/ffprobe are required in PATH.")
        return 2

    try:
        probe = _run_ffprobe(ffprobe_bin, video_path)
    except Exception as exc:
        print(f"[FAIL] {exc}")
        return 2

    passes = max(1, int(args.passes or 1))
    expected_frames = _expected_frame_count(probe, int(args.expected_frames or 0))
    pass_rows: list[dict[str, Any]] = []
    unique_digests: set[str] = set()
    failures: list[str] = []
    warnings: list[str] = []

    for index in range(1, passes + 1):
        row = _decode_with_framehash(ffmpeg_bin, video_path)
        row["pass_index"] = index
        pass_rows.append(row)
        unique_digests.add(str(row.get("frame_hash_digest") or ""))

        if int(row.get("return_code") or 0) != 0:
            failures.append(
                f"pass {index}: ffmpeg decode returned {row.get('return_code')} "
                f"({'; '.join((row.get('error_lines') or [])[:3])})"
            )
        if int(row.get("malformed_lines") or 0) > 0:
            failures.append(f"pass {index}: malformed framehash lines={row.get('malformed_lines')}")
        if expected_frames > 0 and int(row.get("frame_count") or 0) != expected_frames:
            failures.append(
                f"pass {index}: decoded frame count mismatch "
                f"(expected={expected_frames}, got={row.get('frame_count')})"
            )
        if int(row.get("non_monotonic_pts") or 0) > 0:
            warnings.append(f"pass {index}: non-monotonic PTS count={row.get('non_monotonic_pts')}")
        if int(row.get("missing_dts") or 0) > 0:
            warnings.append(f"pass {index}: missing DTS frames={row.get('missing_dts')}")
        if int(row.get("non_monotonic_dts") or 0) > 0:
            warnings.append(f"pass {index}: non-monotonic DTS count={row.get('non_monotonic_dts')}")

    if len(unique_digests) > 1:
        failures.append(f"decode is non-deterministic across passes (digest_count={len(unique_digests)})")

    if args.strict_timestamps:
        timestamp_issues = [text for text in warnings if "PTS" in text or "DTS" in text]
        failures.extend(timestamp_issues)

    report = {
        "video_path": str(video_path),
        "ffprobe": probe,
        "expected_frames": expected_frames,
        "passes": pass_rows,
        "warnings": warnings,
        "failures": failures,
        "ok": len(failures) == 0,
    }

    print("=== Video Decode Probe ===")
    print(f"video={video_path}")
    print(
        "ffprobe: "
        f"codec={probe.get('codec_name')}/{probe.get('profile')} "
        f"duration={probe.get('duration_s')}s "
        f"nb_frames={probe.get('nb_frames')} nb_read_frames={probe.get('nb_read_frames')} "
        f"avg_fps={probe.get('avg_frame_rate')} r_fps={probe.get('r_frame_rate')}"
    )
    print(f"expected_frames={expected_frames} passes={passes}")
    for row in pass_rows:
        print(
            f"pass={row.get('pass_index')} frames={row.get('frame_count')} rc={row.get('return_code')} "
            f"missing_dts={row.get('missing_dts')} non_monotonic_pts={row.get('non_monotonic_pts')} "
            f"non_monotonic_dts={row.get('non_monotonic_dts')} digest={row.get('frame_hash_digest')}"
        )

    if warnings:
        print("--- warnings ---")
        for text in warnings:
            print(text)

    if failures:
        print("--- failures ---")
        for text in failures:
            print(text)
        status_code = 1
    else:
        print("[OK] all decode passes read full frame sequence successfully.")
        status_code = 0

    report_json_path = str(args.report_json or "").strip()
    if report_json_path:
        output_path = Path(report_json_path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"report_json={output_path}")

    return status_code


if __name__ == "__main__":
    raise SystemExit(main())
