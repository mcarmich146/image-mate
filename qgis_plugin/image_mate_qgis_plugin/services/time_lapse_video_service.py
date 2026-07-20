# -*- coding: utf-8 -*-
"""Time-lapse video rendering service for project raster layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
from typing import Callable, Sequence


@dataclass(frozen=True)
class TimeLapseFrameSpec:
    """Normalized frame configuration for time-lapse rendering."""

    layer_ids: tuple[str, ...]
    hold_frames: int
    overlay_text: str
    label: str


def normalize_time_lapse_fps(value, *, default=2, min_value=1, max_value=60):
    """Normalize frames-per-second input."""

    try:
        fps = int(value)
    except Exception:
        fps = int(default)
    if fps < int(min_value) or fps > int(max_value):
        fps = int(default)
    return int(max(int(min_value), min(int(max_value), fps)))


def normalize_time_lapse_frames(frames_payload):
    """Normalize user-provided frame payloads into immutable frame specs."""

    rows = frames_payload if isinstance(frames_payload, list) else []
    normalized = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue

        layer_ids = []
        raw_ids = row.get("layer_ids") if isinstance(row.get("layer_ids"), list) else []
        for value in raw_ids:
            layer_id = str(value or "").strip()
            if layer_id and layer_id not in layer_ids:
                layer_ids.append(layer_id)
        if not layer_ids:
            layer_id = str(row.get("layer_id") or "").strip()
            if layer_id:
                layer_ids.append(layer_id)
        if not layer_ids:
            continue

        try:
            hold_frames = int(row.get("hold_frames") or 1)
        except Exception:
            hold_frames = 1
        hold_frames = max(1, min(10_000, hold_frames))

        label = str(row.get("frame_name") or row.get("label") or "").strip()
        if not label:
            label = f"Frame {index}"

        overlay_text = str(row.get("overlay_text") or "").strip() or label
        normalized.append(
            TimeLapseFrameSpec(
                layer_ids=tuple(layer_ids),
                hold_frames=int(hold_frames),
                overlay_text=overlay_text,
                label=label,
            )
        )

    if not normalized:
        raise ValueError("At least one valid frame is required to generate a time-lapse video.")
    return normalized


class TimeLapseVideoService:
    """Render QGIS project raster layers into an MP4 time-lapse video."""

    def render_project_time_lapse(
        self,
        *,
        frame_specs: Sequence[TimeLapseFrameSpec],
        output_path,
        frames_per_second,
        temp_dir=None,
        map_extent=None,
        destination_crs=None,
        frame_width=1280,
        frame_height=0,
        log_callback: Callable[[str, int], None] | None = None,
    ):
        from qgis.PyQt.QtCore import QSize
        from qgis.PyQt.QtGui import QColor
        from qgis.core import (
            Qgis,
            QgsCoordinateTransform,
            QgsMapSettings,
            QgsMapRendererSequentialJob,
            QgsProject,
            QgsRasterLayer,
            QgsRectangle,
        )

        normalized_specs = list(frame_specs or [])
        if not normalized_specs:
            raise RuntimeError("Time-lapse request contains no frame definitions.")

        fps = normalize_time_lapse_fps(frames_per_second, default=2, min_value=1, max_value=60)

        output_file = Path(output_path)
        if not output_file.suffix:
            output_file = output_file.with_suffix(".mp4")
        output_file.parent.mkdir(parents=True, exist_ok=True)

        staging_root = Path(temp_dir or Path(tempfile.gettempdir()) / "image_mate_qgis_plugin")
        staging_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        frame_dir = staging_root / f"timelapse_frames_{stamp}"
        sequence_dir = frame_dir / "sequence"
        frame_dir.mkdir(parents=True, exist_ok=True)
        sequence_dir.mkdir(parents=True, exist_ok=True)

        project = QgsProject.instance()
        ordered_layer_ids = []
        try:
            for layer in project.layerTreeRoot().layerOrder() or []:
                layer_id = str(layer.id() or "").strip()
                if layer_id and layer_id not in ordered_layer_ids:
                    ordered_layer_ids.append(layer_id)
        except Exception:
            ordered_layer_ids = []
        layer_order = {layer_id: idx for idx, layer_id in enumerate(ordered_layer_ids)}

        resolved_frames = []
        unique_layers = []
        seen_layer_ids = set()
        for frame_index, spec in enumerate(normalized_specs, start=1):
            frame_layers = []
            for layer_id in spec.layer_ids:
                project_layer = project.mapLayer(str(layer_id))
                if project_layer is None:
                    raise RuntimeError(f"Frame {frame_index}: raster layer not found ({layer_id}).")
                if not isinstance(project_layer, QgsRasterLayer):
                    raise RuntimeError(f"Frame {frame_index}: layer is not raster ({layer_id}).")
                if not project_layer.isValid():
                    raise RuntimeError(f"Frame {frame_index}: raster layer is invalid ({layer_id}).")
                frame_layers.append(project_layer)
                normalized_id = str(project_layer.id() or "").strip()
                if normalized_id and normalized_id not in seen_layer_ids:
                    seen_layer_ids.add(normalized_id)
                    unique_layers.append(project_layer)

            frame_layers.sort(key=lambda layer: layer_order.get(str(layer.id() or ""), 10_000_000))
            if not frame_layers:
                raise RuntimeError(f"Frame {frame_index} has no resolvable raster layers.")
            resolved_frames.append((spec, frame_layers))

        effective_destination_crs = None
        if destination_crs is not None:
            try:
                if destination_crs.isValid():
                    effective_destination_crs = destination_crs
            except Exception:
                effective_destination_crs = None
        if effective_destination_crs is None:
            for layer in unique_layers:
                layer_crs = layer.crs()
                if layer_crs is not None and layer_crs.isValid():
                    effective_destination_crs = layer_crs
                    break
        if effective_destination_crs is None or not effective_destination_crs.isValid():
            raise RuntimeError("Could not resolve a valid destination CRS for time-lapse rendering.")

        render_extent = None
        if map_extent is not None:
            try:
                if not map_extent.isEmpty():
                    render_extent = QgsRectangle(map_extent)
            except Exception:
                render_extent = None
        if render_extent is None:
            for layer in unique_layers:
                layer_extent = QgsRectangle(layer.extent())
                if layer_extent.isEmpty():
                    continue
                layer_crs = layer.crs()
                if (
                    layer_crs is not None
                    and layer_crs.isValid()
                    and effective_destination_crs.isValid()
                    and layer_crs != effective_destination_crs
                ):
                    transform = QgsCoordinateTransform(layer_crs, effective_destination_crs, project)
                    layer_extent = transform.transformBoundingBox(layer_extent)
                if render_extent is None:
                    render_extent = QgsRectangle(layer_extent)
                else:
                    render_extent.combineExtentWith(layer_extent)
        if render_extent is None or render_extent.isEmpty():
            raise RuntimeError("Could not resolve a non-empty render extent for time-lapse rendering.")

        width = self._clamp_even_dimension(frame_width, min_value=320, max_value=3840)
        if int(frame_height or 0) > 0:
            height = self._clamp_even_dimension(frame_height, min_value=240, max_value=2160)
        else:
            derived = 720
            try:
                extent_width = float(render_extent.width())
                extent_height = float(render_extent.height())
                if extent_width > 0.0 and extent_height > 0.0:
                    derived = int(round(float(width) * (extent_height / extent_width)))
            except Exception:
                derived = 720
            height = self._clamp_even_dimension(derived, min_value=240, max_value=2160)

        self._emit_log(
            log_callback,
            (
                f"time_lapse render start: frames={len(resolved_frames)} fps={fps} "
                f"size={width}x{height} output={output_file}"
            ),
            Qgis.Info,
        )

        sequence_index = 0
        for frame_index, (spec, frame_layers) in enumerate(resolved_frames, start=1):
            map_settings = QgsMapSettings()
            map_settings.setDestinationCrs(effective_destination_crs)
            map_settings.setExtent(render_extent)
            map_settings.setOutputSize(QSize(int(width), int(height)))
            map_settings.setBackgroundColor(QColor(0, 0, 0))
            map_settings.setLayers(list(frame_layers))

            job = QgsMapRendererSequentialJob(map_settings)
            job.start()
            job.waitForFinished()
            image = job.renderedImage()
            if image is None or image.isNull():
                raise RuntimeError(f"Failed to render time-lapse frame {frame_index}.")

            overlay_text = str(spec.overlay_text or "").strip()
            if overlay_text:
                self._draw_overlay_text(
                    image=image,
                    text=overlay_text,
                    horizontal_align="left",
                    vertical_align="top",
                )

            frame_path = frame_dir / f"frame_{frame_index:05d}.png"
            if not image.save(str(frame_path), "PNG"):
                raise RuntimeError(f"Failed to save rendered frame to disk: {frame_path}")

            repeat_count = max(1, int(spec.hold_frames))
            for _unused in range(repeat_count):
                sequence_index += 1
                sequence_path = sequence_dir / f"seq_{sequence_index:06d}.png"
                shutil.copyfile(str(frame_path), str(sequence_path))

            self._emit_log(
                log_callback,
                (
                    f"time_lapse rendered frame {frame_index}/{len(resolved_frames)} "
                    f"hold={repeat_count} layers={len(frame_layers)} label={spec.label}"
                ),
                Qgis.Info,
            )

        if sequence_index <= 0:
            raise RuntimeError("Time-lapse rendering produced no image sequence.")

        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            raise RuntimeError("ffmpeg executable was not found in PATH. Install ffmpeg to generate videos.")

        sequence_pattern = sequence_dir / "seq_%06d.png"
        command = [
            str(ffmpeg_bin),
            "-y",
            "-framerate",
            str(int(fps)),
            "-i",
            str(sequence_pattern),
            "-c:v",
            "libx264",
            "-bf",
            "0",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_file),
        ]
        expected_duration_s = float(sequence_index) / float(fps)
        self._emit_log(
            log_callback,
            (
                f"time_lapse encoding video with ffmpeg: sequence_frames={sequence_index} "
                f"expected_duration={expected_duration_s:.2f}s output={output_file}"
            ),
            Qgis.Info,
        )
        process = subprocess.run(command, capture_output=True, text=True)
        if int(process.returncode) != 0:
            stderr_text = str(process.stderr or "").strip()
            stderr_lines = stderr_text.splitlines()[-8:]
            summary = " | ".join(stderr_lines) if stderr_lines else f"exit_code={process.returncode}"
            raise RuntimeError(f"ffmpeg failed while encoding time-lapse video: {summary}")

        if not output_file.exists() or output_file.stat().st_size <= 0:
            raise RuntimeError(f"Time-lapse output video was not created: {output_file}")

        probe = self._probe_video_stream(output_file)
        if probe is None:
            self._emit_log(
                log_callback,
                (
                    "time_lapse sanity check skipped "
                    "(ffprobe unavailable or probe failed) "
                    f"expected_duration={expected_duration_s:.2f}s expected_frames={sequence_index}"
                ),
                Qgis.Warning,
            )
        else:
            measured_duration_s = max(0.0, float(probe.get("duration_s") or 0.0))
            measured_frames = int(probe.get("frame_count") or 0)
            duration_tolerance_s = (1.0 / float(max(1, int(fps)))) + 0.05
            duration_short = (
                measured_duration_s > 0.0
                and measured_duration_s + duration_tolerance_s < expected_duration_s
            )
            frame_short = measured_frames > 0 and measured_frames + 1 < int(sequence_index)
            if duration_short or frame_short:
                raise RuntimeError(
                    "Time-lapse output failed sanity checks: "
                    f"expected about {expected_duration_s:.2f}s/{sequence_index} frames, "
                    f"got {measured_duration_s:.3f}s/{measured_frames} frames."
                )
            self._emit_log(
                log_callback,
                (
                    "time_lapse sanity check passed: "
                    f"duration={measured_duration_s:.3f}s frames={measured_frames} "
                    f"avg_fps={probe.get('avg_frame_rate')} r_fps={probe.get('r_frame_rate')}"
                ),
                Qgis.Info,
            )

        self._emit_log(
            log_callback,
            f"time_lapse video encoded successfully: {output_file}",
            Qgis.Info,
        )

        return {
            "output_path": str(output_file),
            "frames_per_second": int(fps),
            "frame_count": len(resolved_frames),
            "sequence_frames": int(sequence_index),
        }

    @staticmethod
    def _emit_log(log_callback, message, level):
        if log_callback is None:
            return
        text = str(message or "").strip()
        if not text:
            return
        try:
            log_callback(text, int(level))
            return
        except TypeError:
            pass
        except Exception:
            return
        try:
            log_callback(text)
        except Exception:
            pass

    @staticmethod
    def _probe_video_stream(video_path):
        ffprobe_bin = shutil.which("ffprobe")
        if not ffprobe_bin:
            return None

        command = [
            str(ffprobe_bin),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration,nb_frames,nb_read_frames,avg_frame_rate,r_frame_rate",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ]
        process = subprocess.run(command, capture_output=True, text=True)
        if int(process.returncode) != 0:
            return None

        try:
            payload = json.loads(str(process.stdout or "").strip() or "{}")
        except Exception:
            return None
        return TimeLapseVideoService._parse_video_probe_payload(payload)

    @staticmethod
    def _parse_video_probe_payload(payload):
        if not isinstance(payload, dict):
            return None
        streams = payload.get("streams")
        if not isinstance(streams, list) or not streams:
            return None
        stream = streams[0] if isinstance(streams[0], dict) else {}
        if not isinstance(stream, dict):
            return None

        duration_s = 0.0
        try:
            duration_s = max(0.0, float(stream.get("duration") or 0.0))
        except Exception:
            duration_s = 0.0
        if duration_s <= 0.0:
            format_payload = payload.get("format") if isinstance(payload.get("format"), dict) else {}
            try:
                duration_s = max(0.0, float(format_payload.get("duration") or 0.0))
            except Exception:
                duration_s = 0.0

        frame_count = 0
        for key in ("nb_read_frames", "nb_frames"):
            raw_value = stream.get(key)
            text_value = str(raw_value or "").strip()
            if not text_value:
                continue
            try:
                frame_count = max(frame_count, int(text_value))
            except Exception:
                continue

        return {
            "duration_s": duration_s,
            "frame_count": frame_count,
            "avg_frame_rate": str(stream.get("avg_frame_rate") or "").strip(),
            "r_frame_rate": str(stream.get("r_frame_rate") or "").strip(),
        }

    @staticmethod
    def _draw_overlay_text(*, image, text, horizontal_align="left", vertical_align="top"):
        from qgis.PyQt.QtGui import QColor
        from qgis.PyQt.QtGui import QFont
        from qgis.PyQt.QtGui import QPainter
        from qgis.PyQt.QtGui import QPen

        if image is None or image.isNull():
            return
        message = str(text or "").strip()
        if not message:
            return

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        font_size = max(12, int(round(float(image.height()) * 0.035)))
        painter.setFont(QFont("Sans Serif", font_size))
        metrics = painter.fontMetrics()
        text_width = max(1, int(metrics.horizontalAdvance(message)))
        margin = max(12, int(round(float(image.height()) * 0.03)))

        horizontal = str(horizontal_align or "left").strip().lower()
        if horizontal == "center":
            x = max(margin, int((image.width() - text_width) / 2))
        elif horizontal == "right":
            x = max(margin, int(image.width() - text_width - margin))
        else:
            x = margin

        vertical = str(vertical_align or "top").strip().lower()
        if vertical == "bottom":
            y = max(margin + metrics.ascent(), int(image.height() - margin))
        else:
            y = max(margin + metrics.ascent(), margin + metrics.ascent())

        painter.setPen(QPen(QColor(0, 0, 0, 220), 3))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(x + dx, y + dy, message)

        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawText(x, y, message)
        painter.end()

    @staticmethod
    def _clamp_even_dimension(value, *, min_value, max_value):
        clamped = max(int(min_value), min(int(value), int(max_value)))
        if clamped % 2 != 0:
            if clamped < int(max_value):
                clamped += 1
            else:
                clamped -= 1
        return max(int(min_value), min(clamped, int(max_value)))
