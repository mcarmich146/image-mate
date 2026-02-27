# -*- coding: utf-8 -*-
"""Workflow execution worker for Image Mate workflows."""

from pathlib import Path
import json
from datetime import datetime, timezone
import subprocess
import shutil
from urllib.parse import urlparse
import re
import time
import traceback

from qgis import processing
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtGui import QPainter
from qgis.PyQt.QtGui import QPen
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMapSettings,
    QgsMapRendererSequentialJob,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
)

ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK = "for_each_image_in_stack"


class WorkflowExecutionWorker(QObject):
    log = pyqtSignal(str, int)
    progress = pyqtSignal(int, int, str)
    node_state = pyqtSignal(str, str)
    active_node = pyqtSignal(str)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str, str)

    def __init__(self, *, source_service, search_items, temp_dir, node_map, incoming, asset_cache_dir=None):
        super().__init__()
        self.source_service = source_service
        self.search_items = dict(search_items or {})
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.asset_cache_dir = Path(asset_cache_dir) if asset_cache_dir is not None else self.temp_dir
        self.asset_cache_dir.mkdir(parents=True, exist_ok=True)
        self.node_map = dict(node_map or {})
        self.incoming = {str(k): set(v or set()) for k, v in (incoming or {}).items()}
        self.outgoing = {node_id: set() for node_id in self.node_map}
        for target_node_id, parent_ids in self.incoming.items():
            for parent_id in parent_ids:
                if parent_id in self.outgoing:
                    self.outgoing[parent_id].add(str(target_node_id))
        self._mask_extent_cache_wgs84 = {}

    def run(self):
        try:
            total_nodes = len(self.node_map)
            outputs_by_node = {}
            remaining = set(self.node_map.keys())
            completed = 0
            self._emit_progress(0, total_nodes, "Preparing workflow execution...")

            while remaining:
                ready = sorted(
                    [
                        node_id
                        for node_id in remaining
                        if all(pred in outputs_by_node for pred in self.incoming.get(node_id, set()))
                    ]
                )
                self._emit_log(
                    f"Ready node(s): {', '.join(ready) if ready else '(none)'} | Remaining: {len(remaining)}",
                    Qgis.Info,
                )
                if not ready:
                    raise RuntimeError(
                        "Workflow graph has a cycle or unresolved dependency; no runnable nodes are available."
                    )

                for node_id in ready:
                    node = self.node_map[node_id]
                    node_type = str(node.get("type") or "").strip().lower()
                    node_label = str(node.get("label") or node_id).strip()
                    deps = sorted(self.incoming.get(node_id, set()))
                    input_artifacts = []
                    for dep_node_id in deps:
                        input_artifacts.extend(outputs_by_node.get(dep_node_id) or [])

                    self._emit_log(
                        f"Running node {node_id} ({node_type}) '{node_label}' | "
                        f"dependencies={deps} | input_artifacts={len(input_artifacts)}",
                        Qgis.Info,
                    )
                    self.active_node.emit(node_id)
                    self.node_state.emit(node_id, "running")
                    self._emit_progress(completed, total_nodes, f"Running {node_id}...")
                    started_at = time.perf_counter()

                    try:
                        outputs = self._execute_node(node=node, input_artifacts=input_artifacts)
                    except Exception as exc:
                        self.node_state.emit(node_id, "error")
                        self._emit_log(
                            f"Node {node_id} raised an exception: {exc}",
                            Qgis.Warning,
                        )
                        self._emit_log(traceback.format_exc(), Qgis.Warning)
                        raise RuntimeError(f"Node {node_id} failed: {exc}") from exc

                    outputs = outputs if isinstance(outputs, list) else []
                    outputs_by_node[node_id] = outputs
                    completed += 1
                    remaining.remove(node_id)
                    self.node_state.emit(node_id, "success")
                    self._emit_progress(completed, total_nodes, f"Completed {node_id}.")
                    elapsed_s = max(0.0, float(time.perf_counter() - started_at))
                    self._emit_log(
                        f"Node {node_id} completed successfully in {elapsed_s:.2f}s; "
                        f"output_artifacts={len(outputs)}",
                        Qgis.Info,
                    )

            self.active_node.emit("")
            self._emit_progress(total_nodes, total_nodes, "Workflow execution completed successfully.")
            self.finished.emit({"outputs_by_node": outputs_by_node})
        except Exception as exc:
            self.active_node.emit("")
            self._emit_log(f"Workflow worker failed: {exc}", Qgis.Warning)
            self._emit_log(traceback.format_exc(), Qgis.Warning)
            self.failed.emit(str(exc), traceback.format_exc())

    def _emit_log(self, message, level):
        self.log.emit(str(message or "").strip(), int(level))

    def _emit_progress(self, completed, total, text):
        self.progress.emit(int(completed or 0), int(total or 0), str(text or "").strip())

    def _run_processing_algorithm(self, *, algorithm_id, params, node_id, context):
        started_at = time.perf_counter()
        try:
            result = processing.run(str(algorithm_id or "").strip(), dict(params or {}))
        except Exception as exc:
            elapsed_s = max(0.0, float(time.perf_counter() - started_at))
            param_keys = sorted(str(key) for key in (params or {}).keys())
            self._emit_log(
                f"{context} node {node_id}: processing {algorithm_id} failed after {elapsed_s:.2f}s "
                f"param_keys={','.join(param_keys) if param_keys else '(none)'} error={exc}",
                Qgis.Warning,
            )
            raise
        elapsed_s = max(0.0, float(time.perf_counter() - started_at))
        result_keys = sorted(str(key) for key in (result or {}).keys())
        self._emit_log(
            f"{context} node {node_id}: processing {algorithm_id} completed in {elapsed_s:.2f}s "
            f"result_keys={','.join(result_keys) if result_keys else '(none)'}",
            Qgis.Info,
        )
        return result

    def _execute_node(self, *, node, input_artifacts):
        node_type = str(node.get("type") or "").strip().lower()
        payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
        node_id = str(node.get("id") or "").strip()

        if node_type == "source":
            return self._execute_source_node(node_id=node_id, payload=payload)
        if node_type == "adapter":
            return self._execute_adapter_node(
                node_id=node_id,
                payload=payload,
                input_artifacts=input_artifacts,
            )
        if node_type == "function":
            function_id = str(payload.get("function_id") or "").strip()
            return self._execute_function_node(
                node_id=node_id,
                function_id=function_id,
                payload=payload,
                input_artifacts=input_artifacts,
            )
        raise RuntimeError(f"Unsupported node type '{node_type}'")

    def _execute_adapter_node(self, *, node_id, payload, input_artifacts):
        adapter_id = str(payload.get("adapter_id") or "").strip()
        if adapter_id != ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK:
            raise RuntimeError(f"Unsupported adapter_id '{adapter_id}'")

        adapted_function_id = str(payload.get("adapted_function_id") or "").strip()
        if adapted_function_id:
            adapted_payload = payload.get("adapted_function_payload")
            adapted_payload = (
                dict(adapted_payload or {})
                if isinstance(adapted_payload, dict)
                else {}
            )
            if adapted_function_id == "clip_to_aoi":
                self._emit_log(
                    f"Adapter node {node_id}: applying embedded function {adapted_function_id}",
                    Qgis.Info,
                )
                outputs = self._execute_clip_to_aoi(
                    node_id=node_id,
                    payload=adapted_payload,
                    input_artifacts=input_artifacts,
                )
                self._emit_log(
                    f"Adapter node {node_id}: embedded function {adapted_function_id} produced {len(outputs)} artifact(s)",
                    Qgis.Info,
                )
                return outputs
            raise RuntimeError(f"Unsupported adapted_function_id '{adapted_function_id}'")

        # Backward-compatibility for older adapter nodes that did pass-through only.
        raster_outputs = []
        for row in input_artifacts or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("artifact_type") or "").strip().lower() != "raster":
                continue
            value = str(row.get("path") or "").strip()
            if not value:
                continue
            copied = dict(row)
            copied["adapter_id"] = adapter_id
            copied["adapter_node_id"] = node_id
            raster_outputs.append(copied)

        if not raster_outputs:
            raise RuntimeError(
                f"Adapter node {node_id} ({adapter_id}) received no raster inputs"
            )
        self._emit_log(
            f"Adapter node {node_id}: applied {adapter_id} to {len(raster_outputs)} raster artifact(s)",
            Qgis.Info,
        )
        return raster_outputs

    def _execute_source_node(self, *, node_id, payload):
        mode = str(payload.get("mode") or "single").strip().lower()
        item_ids = payload.get("item_ids")
        item_ids = item_ids if isinstance(item_ids, list) else []
        item_ids = [str(v or "").strip() for v in item_ids if str(v or "").strip()]
        self._emit_log(f"Source node {node_id}: mode={mode} | item_ids={item_ids}", Qgis.Info)

        downstream_mask_extents = self._downstream_clip_mask_extents_wgs84(node_id)
        if downstream_mask_extents:
            self._emit_log(
                f"Source node {node_id}: AOI prefilter enabled with {len(downstream_mask_extents)} downstream mask extent(s).",
                Qgis.Info,
            )

        outputs = []
        seen_logical_sources = set()
        for seed_item_id in item_ids:
            item = self.search_items.get(seed_item_id)
            if not item:
                raise RuntimeError(f"Source item not found in search cache: {seed_item_id}")

            logical_source_key = self._logical_source_key(item, fallback_id=seed_item_id)
            if logical_source_key in seen_logical_sources:
                self._emit_log(
                    f"Source node {node_id}: skipping duplicate logical source {logical_source_key}",
                    Qgis.Info,
                )
                continue
            seen_logical_sources.add(logical_source_key)

            tile_items = self._expand_tiles_for_item(item)
            tile_items = self._filter_tiles_by_mask_extents(
                node_id=node_id,
                logical_source_key=logical_source_key,
                tile_items=tile_items,
                mask_extents_wgs84=downstream_mask_extents,
            )
            tile_paths = []
            total_tiles = len(tile_items)
            for tile_index, tile_item in enumerate(tile_items, start=1):
                tile_item_id = str(tile_item.get("id") or "").strip() or "item"
                self._emit_log(
                    f"Source node {node_id}: downloading image {tile_index}/{total_tiles} "
                    f"for {logical_source_key} (item_id={tile_item_id})",
                    Qgis.Info,
                )
                tile_path = self._resolve_processing_raster_path(tile_item)
                tile_paths.append(tile_path)
                self._emit_log(
                    f"Source node {node_id}: tile resolved for logical_source={logical_source_key} "
                    f"tile_item_id={tile_item_id} path={tile_path}",
                    Qgis.Info,
                )

            if not tile_paths:
                raise RuntimeError(f"No raster tiles were resolved for source item {seed_item_id}")

            if len(tile_paths) > 1:
                source_path = self._stitch_source_tiles(
                    node_id=node_id,
                    logical_source_key=logical_source_key,
                    tile_paths=tile_paths,
                )
                self._emit_log(
                    f"Source node {node_id}: stitched {len(tile_paths)} tiles for {logical_source_key} -> {source_path}",
                    Qgis.Info,
                )
            else:
                source_path = tile_paths[0]

            outputs.append(
                {
                    "artifact_type": "raster",
                    "path": source_path,
                    "item_id": seed_item_id,
                    "node_id": node_id,
                    "logical_source_key": logical_source_key,
                    "tile_count": len(tile_paths),
                    "collection_datetime": str(item.get("datetime") or "").strip(),
                    "collection_date": str(item.get("datetime") or "").strip()[:10],
                }
            )
            self._emit_log(
                f"Source node {node_id}: resolved logical source {logical_source_key} -> raster {source_path}",
                Qgis.Info,
            )
        return outputs

    def _execute_function_node(self, *, node_id, function_id, payload, input_artifacts):
        self._emit_log(
            f"Function node {node_id}: function_id={function_id} | "
            f"input_artifacts={len(input_artifacts or [])}",
            Qgis.Info,
        )
        if function_id == "clip_to_aoi":
            return self._execute_clip_to_aoi(node_id=node_id, payload=payload, input_artifacts=input_artifacts)
        if function_id == "temporal_stack_to_video":
            return self._execute_temporal_stack_to_video(
                node_id=node_id,
                payload=payload,
                input_artifacts=input_artifacts,
            )
        raise RuntimeError(f"Unsupported function_id '{function_id}'")

    def _execute_clip_to_aoi(self, *, node_id, payload, input_artifacts):
        raster_inputs = []
        for row in input_artifacts or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("artifact_type") or "").strip().lower() != "raster":
                continue
            value = str(row.get("path") or "").strip()
            if value:
                raster_inputs.append(dict(row))
        if not raster_inputs:
            raise RuntimeError("No raster inputs provided to clip_to_aoi")

        mask_path = str(payload.get("aoi_effective_mask_path") or "").strip()
        mask_desc = str(payload.get("aoi_effective_mask_desc") or "").strip()
        if not mask_path:
            raise RuntimeError("clip_to_aoi missing resolved mask path")

        output_base = str(payload.get("output_path") or "").strip()
        if not output_base:
            safe_node = re.sub(r"[^0-9A-Za-z._-]+", "_", str(node_id or "node")).strip("_") or "node"
            output_base = str(self.temp_dir / f"{safe_node}_clip_output.tif")

        self._emit_log(
            f"clip_to_aoi node {node_id}: mask={mask_desc or mask_path} | "
            f"inputs={len(raster_inputs)} | output_base={output_base}",
            Qgis.Info,
        )
        self._emit_clip_diagnostics(
            node_id=node_id,
            mask_path=mask_path,
            raster_inputs=[
                str(row.get("path") or "").strip()
                for row in raster_inputs
                if str(row.get("path") or "").strip()
            ],
        )

        outputs = []
        used_output_paths = set()
        for index, input_artifact in enumerate(raster_inputs):
            input_path = str(input_artifact.get("path") or "").strip()
            output_path = self._build_output_path(
                output_base,
                index,
                len(raster_inputs),
                artifact=input_artifact,
                used_paths=used_output_paths,
            )
            output_parent = Path(output_path).parent
            if output_parent and not output_parent.exists():
                output_parent.mkdir(parents=True, exist_ok=True)

            params = {
                "INPUT": input_path,
                "MASK": mask_path,
                "SOURCE_CRS": None,
                "TARGET_CRS": None,
                "NODATA": None,
                "ALPHA_BAND": False,
                "CROP_TO_CUTLINE": True,
                "KEEP_RESOLUTION": True,
                "SET_RESOLUTION": False,
                "X_RESOLUTION": None,
                "Y_RESOLUTION": None,
                "MULTITHREADING": False,
                "OPTIONS": "",
                "DATA_TYPE": 0,
                "EXTRA": "",
                "OUTPUT": output_path,
            }
            self._emit_log(
                f"clip_to_aoi node {node_id}: running gdal:cliprasterbymasklayer "
                f"input={input_path} output={output_path}",
                Qgis.Info,
            )
            result = self._run_processing_algorithm(
                algorithm_id="gdal:cliprasterbymasklayer",
                params=params,
                node_id=node_id,
                context="clip_to_aoi",
            )
            result_path = str(result.get("OUTPUT") or output_path).strip()
            outputs.append(
                {
                    "artifact_type": "raster",
                    "path": result_path,
                    "node_id": node_id,
                    "item_id": str(input_artifact.get("item_id") or "").strip(),
                    "collection_date": str(input_artifact.get("collection_date") or "").strip(),
                    "collection_datetime": str(
                        input_artifact.get("collection_datetime") or input_artifact.get("datetime") or ""
                    ).strip(),
                }
            )
            self._emit_log(
                f"clip_to_aoi node {node_id}: output raster created {result_path}",
                Qgis.Info,
            )
        return outputs

    def _execute_temporal_stack_to_video(self, *, node_id, payload, input_artifacts):
        raster_artifacts = []
        for row in input_artifacts or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("artifact_type") or "").strip().lower() != "raster":
                continue
            raster_path = str(row.get("path") or "").strip()
            if not raster_path:
                continue
            raster_artifacts.append(dict(row))

        if not raster_artifacts:
            raise RuntimeError("No raster inputs provided to temporal_stack_to_video")

        output_path = str(payload.get("output_path") or "").strip()
        if not output_path:
            safe_node = re.sub(r"[^0-9A-Za-z._-]+", "_", str(node_id or "node")).strip("_") or "node"
            output_path = str(self.temp_dir / f"{safe_node}_temporal_video.mp4")
        output_file = Path(output_path)
        if not output_file.suffix:
            output_file = output_file.with_suffix(".mp4")
        output_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            fps = int(payload.get("frames_per_second") or 2)
        except Exception:
            fps = 2
        if fps <= 0:
            fps = 2
        try:
            pause_seconds = float(payload.get("pause_between_dates_seconds") or 0.0)
        except Exception:
            pause_seconds = 0.0
        pause_seconds = max(0.0, pause_seconds)
        text_template = str(payload.get("text_template") or "").strip()
        horizontal_align = str(payload.get("text_horizontal_align") or "left").strip().lower()
        vertical_align = str(payload.get("text_vertical_align") or "top").strip().lower()
        if horizontal_align not in {"left", "center", "right"}:
            horizontal_align = "left"
        if vertical_align not in {"top", "bottom"}:
            vertical_align = "top"

        overlay_layers = self._resolve_video_overlay_layers(node_id=node_id, payload=payload)

        indexed_rows = list(enumerate(raster_artifacts))
        indexed_rows.sort(key=lambda row: self._temporal_sort_key(row[0], row[1]))
        ordered = [row for _idx, row in indexed_rows]

        safe_node = re.sub(r"[^0-9A-Za-z._-]+", "_", str(node_id or "node")).strip("_") or "node"
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        frame_dir = self.temp_dir / f"{safe_node}_video_frames_{stamp}"
        frame_dir.mkdir(parents=True, exist_ok=True)

        base_duration_s = 1.0 / float(fps)
        frame_records = []
        total_frames = len(ordered)

        try:
            frame_width = int(payload.get("frame_width") or 1280)
        except Exception:
            frame_width = 1280
        frame_width = self._clamp_even_dimension(frame_width, min_value=320, max_value=3840)
        try:
            requested_frame_height = int(payload.get("frame_height") or 0)
        except Exception:
            requested_frame_height = 0
        if requested_frame_height > 0:
            frame_height = self._clamp_even_dimension(
                requested_frame_height,
                min_value=240,
                max_value=2160,
            )
        else:
            frame_height = None

        self._emit_log(
            f"temporal_stack_to_video node {node_id}: rendering {total_frames} frame(s) "
            f"at {fps} fps | pause_between_dates={pause_seconds:.2f}s | "
            f"output={output_file}",
            Qgis.Info,
        )
        self._emit_log(
            f"temporal_stack_to_video node {node_id}: output frame size target="
            f"{frame_width}x{frame_height if frame_height is not None else 'auto'}",
            Qgis.Info,
        )

        for frame_index, artifact in enumerate(ordered, start=1):
            input_path = str(artifact.get("path") or "").strip()
            raster_layer = QgsRasterLayer(input_path, f"WorkflowVideoSource-{frame_index}")
            if not raster_layer.isValid():
                raise RuntimeError(f"Video frame source raster is invalid ({input_path})")
            if not raster_layer.crs().isValid():
                raise RuntimeError(f"Video frame source raster has invalid CRS ({input_path})")

            if frame_height is None:
                width = max(1, int(raster_layer.width() or 1))
                height = max(1, int(raster_layer.height() or 1))
                derived_height = int(round(float(frame_width) * (float(height) / float(width))))
                frame_height = self._clamp_even_dimension(
                    derived_height,
                    min_value=240,
                    max_value=2160,
                )
                self._emit_log(
                    f"temporal_stack_to_video node {node_id}: locked auto frame size="
                    f"{frame_width}x{frame_height} from source {width}x{height}",
                    Qgis.Info,
                )

            map_settings = QgsMapSettings()
            map_settings.setDestinationCrs(raster_layer.crs())
            map_settings.setExtent(raster_layer.extent())
            map_settings.setOutputSize(QSize(frame_width, frame_height))
            map_settings.setBackgroundColor(QColor(0, 0, 0))
            map_settings.setLayers([raster_layer] + list(overlay_layers))

            job = QgsMapRendererSequentialJob(map_settings)
            job.start()
            job.waitForFinished()
            image = job.renderedImage()
            if image.isNull():
                raise RuntimeError(f"Failed to render frame {frame_index}/{total_frames} for {input_path}")

            overlay_text = self._format_video_overlay_text(text_template, artifact)
            if overlay_text:
                self._draw_video_overlay_text(
                    image=image,
                    text=overlay_text,
                    horizontal_align=horizontal_align,
                    vertical_align=vertical_align,
                )

            frame_path = frame_dir / f"frame_{frame_index:05d}.png"
            if not image.save(str(frame_path), "PNG"):
                raise RuntimeError(f"Failed to save rendered frame {frame_path}")

            frame_duration = base_duration_s
            if pause_seconds > 0.0 and frame_index < total_frames:
                current_date_key = self._collection_date_token(artifact)
                next_date_key = self._collection_date_token(ordered[frame_index])
                if current_date_key and next_date_key and current_date_key != next_date_key:
                    frame_duration += pause_seconds

            frame_records.append(
                {
                    "path": frame_path,
                    "duration_s": max(0.001, float(frame_duration)),
                    "collection_date": self._collection_date_token(artifact),
                }
            )
            self._emit_log(
                f"temporal_stack_to_video node {node_id}: rendered frame {frame_index}/{total_frames} "
                f"(date={self._collection_date_token(artifact) or 'unknown'})",
                Qgis.Info,
            )

        if not frame_records:
            raise RuntimeError("temporal_stack_to_video did not produce any frames")

        sequence_dir = frame_dir / "sequence"
        sequence_dir.mkdir(parents=True, exist_ok=True)
        sequence_index = 0
        for row in frame_records:
            repeat_count = max(1, int(round(float(row.get("duration_s") or 0.0) * float(fps))))
            for _ in range(repeat_count):
                sequence_index += 1
                seq_path = sequence_dir / f"seq_{sequence_index:06d}.png"
                shutil.copyfile(str(row["path"]), str(seq_path))
        if sequence_index <= 0:
            raise RuntimeError("temporal_stack_to_video did not build an ffmpeg input sequence")

        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            raise RuntimeError(
                "ffmpeg executable was not found in PATH. Install ffmpeg to use temporal_stack_to_video."
            )

        sequence_pattern = sequence_dir / "seq_%06d.png"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-framerate",
            str(int(fps)),
            "-i",
            str(sequence_pattern),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_file),
        ]
        expected_duration_s = float(sequence_index) / float(fps)
        self._emit_log(
            f"temporal_stack_to_video node {node_id}: encoding video with ffmpeg -> {output_file} "
            f"(sequence_frames={sequence_index}, expected_duration={expected_duration_s:.2f}s)",
            Qgis.Info,
        )
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if int(proc.returncode) != 0:
            stderr_text = str(proc.stderr or "").strip()
            stderr_lines = stderr_text.splitlines()[-8:]
            raise RuntimeError(
                "ffmpeg failed while encoding workflow video: "
                + (" | ".join(stderr_lines) if stderr_lines else f"exit_code={proc.returncode}")
            )

        min_duration_s = max(0.0, float(expected_duration_s) * 0.50)
        min_frame_count = max(1, int(round(float(sequence_index) * 0.50)))
        probe = self._probe_video_stream(output_file)
        if probe is None:
            self._emit_log(
                f"temporal_stack_to_video node {node_id}: sanity check skipped "
                f"(ffprobe unavailable or probe failed) | expected_duration={expected_duration_s:.2f}s "
                f"expected_frames={sequence_index}",
                Qgis.Warning,
            )
        else:
            measured_duration_s = max(0.0, float(probe.get("duration_s") or 0.0))
            measured_frames = int(probe.get("frame_count") or 0)
            if measured_duration_s < min_duration_s or measured_frames < min_frame_count:
                raise RuntimeError(
                    "temporal_stack_to_video sanity check failed: "
                    f"expected about {expected_duration_s:.2f}s/{sequence_index} frames, "
                    f"got {measured_duration_s:.3f}s/{measured_frames} frames."
                )
            self._emit_log(
                f"temporal_stack_to_video node {node_id}: sanity check passed "
                f"(duration={measured_duration_s:.3f}s frames={measured_frames})",
                Qgis.Info,
            )

        self._emit_log(
            f"temporal_stack_to_video node {node_id}: video output created {output_file}",
            Qgis.Info,
        )
        return [
            {
                "artifact_type": "video",
                "path": str(output_file),
                "node_id": node_id,
                "frame_count": len(frame_records),
                "frames_per_second": fps,
            }
        ]

    def _resolve_video_overlay_layers(self, *, node_id, payload):
        layer_ids = []
        for key in ("overlay_vector_layer_id", "overlay_shapefile_layer_id"):
            value = str(payload.get(key) or "").strip()
            if value and value not in layer_ids:
                layer_ids.append(value)

        layers = []
        for layer_id in layer_ids:
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer is None:
                raise RuntimeError(
                    f"temporal_stack_to_video node {node_id}: overlay layer not found ({layer_id})"
                )
            if not isinstance(layer, QgsVectorLayer):
                raise RuntimeError(
                    f"temporal_stack_to_video node {node_id}: overlay layer is not vector ({layer_id})"
                )
            if not layer.isValid():
                raise RuntimeError(
                    f"temporal_stack_to_video node {node_id}: overlay layer is invalid ({layer_id})"
                )
            layers.append(layer)
            self._emit_log(
                f"temporal_stack_to_video node {node_id}: overlay layer added "
                f"{layer.name()} ({layer_id})",
                Qgis.Info,
            )
        return layers

    def _temporal_sort_key(self, index, artifact):
        dt_value = str(artifact.get("collection_datetime") or artifact.get("datetime") or "").strip()
        parsed = self._parse_iso_datetime_utc(dt_value)
        if parsed is None:
            return (1, datetime(9999, 12, 31, tzinfo=timezone.utc), index)
        return (0, parsed, index)

    @staticmethod
    def _parse_iso_datetime_utc(value):
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                return parsed.replace(tzinfo=timezone.utc)
            except Exception:
                continue
        return None

    def _collection_date_token(self, artifact):
        date_value = str(artifact.get("collection_date") or "").strip()
        if date_value:
            return date_value[:10]
        dt_value = str(artifact.get("collection_datetime") or artifact.get("datetime") or "").strip()
        parsed = self._parse_iso_datetime_utc(dt_value)
        if parsed is not None:
            return parsed.strftime("%Y-%m-%d")
        if len(dt_value) >= 10:
            return dt_value[:10]
        return ""

    def _format_video_overlay_text(self, text_template, artifact):
        template = str(text_template or "").strip()
        if not template:
            return ""
        pattern = r"\{collection_date(?:\s*,\s*['\"]([^'\"]+)['\"])?\}"

        def repl(match):
            fmt = str(match.group(1) or "yyyy-mm-dd").strip() or "yyyy-mm-dd"
            return self._format_collection_date_with_template(artifact=artifact, fmt=fmt)

        return re.sub(pattern, repl, template)

    def _format_collection_date_with_template(self, *, artifact, fmt):
        parsed = self._parse_iso_datetime_utc(
            str(artifact.get("collection_datetime") or artifact.get("datetime") or "").strip()
        )
        if parsed is None:
            return self._collection_date_token(artifact)
        py_fmt = self._date_format_to_strftime(fmt)
        try:
            return parsed.strftime(py_fmt)
        except Exception:
            return self._collection_date_token(artifact)

    @staticmethod
    def _date_format_to_strftime(fmt):
        value = str(fmt or "").strip()
        if not value:
            return "%Y-%m-%d"
        replacements = [
            ("yyyy", "%Y"),
            ("yy", "%y"),
            ("mm", "%m"),
            ("MM", "%m"),
            ("dd", "%d"),
            ("HH", "%H"),
            ("hh", "%H"),
            ("ss", "%S"),
        ]
        for old, new in replacements:
            value = value.replace(old, new)
        return value

    @staticmethod
    def _draw_video_overlay_text(*, image, text, horizontal_align, vertical_align):
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

        if str(horizontal_align or "left").strip().lower() == "center":
            x = max(margin, int((image.width() - text_width) / 2))
        elif str(horizontal_align or "left").strip().lower() == "right":
            x = max(margin, int(image.width() - text_width - margin))
        else:
            x = margin

        if str(vertical_align or "top").strip().lower() == "bottom":
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
    def _probe_video_stream(video_path):
        ffprobe_bin = shutil.which("ffprobe")
        if not ffprobe_bin:
            return None

        cmd = [
            ffprobe_bin,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration,nb_frames,nb_read_frames,avg_frame_rate,r_frame_rate",
            "-of",
            "json",
            str(video_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if int(proc.returncode) != 0:
            return None

        try:
            payload = json.loads(str(proc.stdout or "").strip() or "{}")
        except Exception:
            return None
        streams = payload.get("streams") if isinstance(payload, dict) else None
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
    def _clamp_even_dimension(value, *, min_value, max_value):
        clamped = max(int(min_value), min(int(value), int(max_value)))
        if clamped % 2 != 0:
            if clamped < int(max_value):
                clamped += 1
            else:
                clamped -= 1
        return max(int(min_value), min(clamped, int(max_value)))

    def _resolve_processing_raster_path(self, item):
        source_id = str(item.get("source_id") or "").strip() or None
        contract_id = str(item.get("contract_id") or "").strip() or None
        item_id = str(item.get("id") or "").strip() or "item"
        assets = item.get("assets") if isinstance(item.get("assets"), dict) else {}
        candidates = [
            ("analytic", str(assets.get("analytic") or "").strip()),
            ("visual_fullres", str(assets.get("visual_fullres") or "").strip()),
            ("visual", str(assets.get("visual") or "").strip()),
        ]
        errors = []
        for key, url in candidates:
            if not url:
                continue
            try:
                expected_size = self._asset_expected_size_bytes(
                    item=item,
                    asset_key=key,
                    asset_url=url,
                )
                cached_path = self._find_cached_asset_path(
                    item_id=item_id,
                    preferred_key=f"workflow_{key}",
                    asset_url=url,
                    expected_size=expected_size,
                )
                if cached_path is not None:
                    cached_ext = str(cached_path.suffix or "").strip().lower()
                    if cached_ext in {".jpg", ".jpeg", ".png", ".webp"}:
                        self._emit_log(
                            f"Cached workflow asset '{key}' is preview format ({cached_ext}); downloading source again.",
                            Qgis.Warning,
                        )
                    elif cached_ext not in {".tif", ".tiff", ".jp2"}:
                        self._emit_log(
                            f"Cached workflow asset '{key}' uses unsupported format ({cached_ext}); downloading source again.",
                            Qgis.Warning,
                        )
                    else:
                        cached_layer = QgsRasterLayer(str(cached_path), f"Workflow Source {item_id} {key}")
                        if cached_layer.isValid() and cached_layer.crs().isValid():
                            self._emit_log(
                                f"Reusing cached source asset '{key}' for item {item_id}: {cached_path}",
                                Qgis.Info,
                            )
                            return str(cached_path)
                        self._emit_log(
                            f"Cached workflow asset '{key}' failed layer validation; downloading source again.",
                            Qgis.Warning,
                        )

                data = self.source_service.download_asset(url, source_hint=source_id, contract_id=contract_id)
                ext = self._guess_asset_extension(url, data)
                if ext in {".jpg", ".jpeg", ".png", ".webp"}:
                    raise RuntimeError(f"non-georeferenced preview format is not allowed for workflow ({ext})")
                if ext not in {".tif", ".tiff", ".jp2"}:
                    raise RuntimeError(f"unsupported workflow raster format ({ext})")
                file_name = f"{item_id.replace(':', '_').replace('/', '_')}_workflow_{key}{ext}"
                path = self.asset_cache_dir / file_name
                path.parent.mkdir(parents=True, exist_ok=True)
                if expected_size is not None and expected_size > 0 and int(len(data)) != int(expected_size):
                    self._emit_log(
                        f"Source size mismatch for item {item_id} asset '{key}': "
                        f"expected={expected_size} downloaded={len(data)}",
                        Qgis.Warning,
                    )
                path.write_bytes(data)
                layer = QgsRasterLayer(str(path), f"Workflow Source {item_id} {key}")
                if not layer.isValid():
                    raise RuntimeError(f"QGIS could not open workflow asset ({path.name})")
                if not layer.crs().isValid():
                    raise RuntimeError(f"Workflow asset has invalid CRS ({path.name})")
                self._emit_log(
                    f"Resolved source asset '{key}' for item {item_id}: {self._raster_diagnostics(str(path))}",
                    Qgis.Info,
                )
                return str(path)
            except Exception as exc:
                errors.append(f"{key}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))
        raise RuntimeError("No usable georeferenced imagery assets were available for workflow source")

    def _find_cached_asset_path(self, *, item_id, preferred_key, asset_url, expected_size):
        if expected_size is None or int(expected_size) <= 0:
            return None
        safe_item_id = str(item_id or "item").replace(":", "_").replace("/", "_")
        candidates = self._cached_asset_candidate_paths(
            item_id=safe_item_id,
            preferred_key=preferred_key,
            asset_url=asset_url,
        )
        for candidate in candidates:
            try:
                size_on_disk = int(candidate.stat().st_size)
            except Exception:
                continue
            if size_on_disk != int(expected_size):
                continue
            return candidate
        return None

    def _cached_asset_candidate_paths(self, *, item_id, preferred_key, asset_url):
        safe_item_id = str(item_id or "item").replace(":", "_").replace("/", "_")
        name_prefix = f"{safe_item_id}_{preferred_key}"
        out = []
        suffix = Path(urlparse(str(asset_url or "")).path).suffix.lower()
        if suffix:
            out.append(self.asset_cache_dir / f"{name_prefix}{suffix}")
        for candidate in sorted(self.asset_cache_dir.glob(f"{name_prefix}.*")):
            if candidate.is_file():
                out.append(candidate)
        dedup = []
        seen = set()
        for candidate in out:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            dedup.append(candidate)
        return dedup

    def _asset_expected_size_bytes(self, *, item, asset_key, asset_url):
        row = item if isinstance(item, dict) else {}
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        raw_assets = raw.get("assets") if isinstance(raw.get("assets"), dict) else {}
        if not raw_assets:
            return None

        key_norm = str(asset_key or "").strip()
        if key_norm.startswith("workflow_"):
            key_norm = key_norm[len("workflow_") :]

        candidate_assets = []
        seen_obj_ids = set()

        direct_asset = raw_assets.get(key_norm)
        if isinstance(direct_asset, dict):
            candidate_assets.append(direct_asset)
            seen_obj_ids.add(id(direct_asset))

        for raw_asset in raw_assets.values():
            if not isinstance(raw_asset, dict):
                continue
            if id(raw_asset) in seen_obj_ids:
                continue
            raw_hrefs = self._asset_hrefs_from_raw_asset(raw_asset)
            if any(self._asset_urls_match(href, asset_url) for href in raw_hrefs):
                candidate_assets.append(raw_asset)
                seen_obj_ids.add(id(raw_asset))

        for asset in candidate_assets:
            size_value = self._extract_size_from_asset_dict(asset)
            if size_value is not None and int(size_value) > 0:
                return int(size_value)
        return None

    @staticmethod
    def _asset_hrefs_from_raw_asset(asset):
        out = []
        if not isinstance(asset, dict):
            return out
        href = str(asset.get("href") or "").strip()
        if href:
            out.append(href)
        alternate = asset.get("alternate")
        if isinstance(alternate, dict):
            for row in alternate.values():
                if not isinstance(row, dict):
                    continue
                alt_href = str(row.get("href") or "").strip()
                if alt_href:
                    out.append(alt_href)
        return out

    @classmethod
    def _extract_size_from_asset_dict(cls, asset):
        if not isinstance(asset, dict):
            return None
        direct = cls._extract_size_from_mapping(asset)
        if direct is not None:
            return direct
        file_meta = asset.get("file")
        if isinstance(file_meta, dict):
            nested = cls._extract_size_from_mapping(file_meta)
            if nested is not None:
                return nested
        props = asset.get("properties")
        if isinstance(props, dict):
            nested = cls._extract_size_from_mapping(props)
            if nested is not None:
                return nested
        return None

    @classmethod
    def _extract_size_from_mapping(cls, mapping):
        if not isinstance(mapping, dict):
            return None
        for key in (
            "file:size",
            "size",
            "content_length",
            "content-length",
            "length",
            "bytes",
            "fileSize",
            "file_size",
        ):
            value = mapping.get(key)
            parsed = cls._coerce_positive_int(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _coerce_positive_int(value):
        if value is None:
            return None
        try:
            parsed = int(float(value))
        except Exception:
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _asset_urls_match(left, right):
        left_text = str(left or "").strip()
        right_text = str(right or "").strip()
        if not left_text or not right_text:
            return False
        if left_text == right_text:
            return True
        left_parsed = urlparse(left_text)
        right_parsed = urlparse(right_text)
        if left_parsed.path and right_parsed.path and left_parsed.path == right_parsed.path:
            return True
        left_core = f"{left_parsed.scheme}://{left_parsed.netloc}{left_parsed.path}"
        right_core = f"{right_parsed.scheme}://{right_parsed.netloc}{right_parsed.path}"
        return bool(left_core and right_core and left_core == right_core)

    def _expand_tiles_for_item(self, item):
        if not isinstance(item, dict):
            return []
        outcome_id = str(item.get("outcome_id") or "").strip()
        source_id = str(item.get("source_id") or "").strip()
        collection_id = self._normalize_collection_id(item.get("collection"))
        if not outcome_id or self._is_quickvisual_thumb_collection(collection_id):
            return [item]

        matches = []
        for candidate in self.search_items.values():
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("outcome_id") or "").strip() != outcome_id:
                continue
            if self._normalize_collection_id(candidate.get("collection")) != collection_id:
                continue
            if str(candidate.get("source_id") or "").strip() != source_id:
                continue
            matches.append(candidate)
        if len(matches) <= 1:
            return [item]

        matches.sort(key=lambda row: str(row.get("id") or "").strip())
        return matches

    def _stitch_source_tiles(self, *, node_id, logical_source_key, tile_paths):
        safe_key = re.sub(r"[^0-9A-Za-z._-]+", "_", str(logical_source_key or "source")).strip("_")
        if not safe_key:
            safe_key = "source"
        if len(safe_key) > 96:
            safe_key = safe_key[:96]
        stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        vrt_path = self.temp_dir / f"{safe_key}_workflow_mosaic_{stamp}.vrt"

        build_vrt_params = {
            "INPUT": [str(path) for path in tile_paths],
            "RESOLUTION": 0,
            "SEPARATE": False,
            "PROJ_DIFFERENCE": False,
            "ADD_ALPHA": False,
            "OUTPUT": str(vrt_path),
        }
        self._emit_log(
            f"Source node {node_id}: stitching tiles with gdal:buildvirtualraster | "
            f"logical_source={logical_source_key} tile_count={len(tile_paths)} output={vrt_path}",
            Qgis.Info,
        )
        result = self._run_processing_algorithm(
            algorithm_id="gdal:buildvirtualraster",
            params=build_vrt_params,
            node_id=node_id,
            context="source-stitch",
        )
        result_path = str(result.get("OUTPUT") or vrt_path).strip()
        layer = QgsRasterLayer(result_path, f"Workflow Mosaic {logical_source_key}")
        if not layer.isValid():
            raise RuntimeError(f"Stitched VRT raster is invalid ({result_path})")
        if not layer.crs().isValid():
            raise RuntimeError(f"Stitched VRT raster has invalid CRS ({result_path})")
        self._emit_log(
            f"Source node {node_id}: stitched raster diagnostics {self._raster_diagnostics(result_path)}",
            Qgis.Info,
        )
        return result_path

    def _logical_source_key(self, item, *, fallback_id=""):
        if not isinstance(item, dict):
            return str(fallback_id or "source").strip() or "source"
        item_id = str(item.get("id") or "").strip()
        outcome_id = str(item.get("outcome_id") or "").strip()
        collection_id = self._normalize_collection_id(item.get("collection"))
        if outcome_id and not self._is_quickvisual_thumb_collection(collection_id):
            return f"{collection_id}:{outcome_id}"
        return item_id or str(fallback_id or "source").strip() or "source"

    @staticmethod
    def _normalize_collection_id(collection_id):
        return str(collection_id or "").strip().lower().replace("_", "-")

    @staticmethod
    def _is_quickvisual_thumb_collection(collection_id):
        norm = str(collection_id or "").strip().lower().replace("_", "-")
        return norm in {
            "quickview-visual-thumb",
            "quickvisual-thumb",
            "quickview-thumb",
            "quickview-thumbnail",
            "thumb",
            "thumbnail",
        }

    def _filter_tiles_by_mask_extents(self, *, node_id, logical_source_key, tile_items, mask_extents_wgs84):
        rows = list(tile_items or [])
        if not rows:
            return []
        if not mask_extents_wgs84:
            return rows

        kept = []
        skipped = 0
        unknown_geom = 0
        for tile_item in rows:
            tile_extent = self._item_extent_wgs84(tile_item)
            if tile_extent is None:
                unknown_geom += 1
                kept.append(tile_item)
                continue
            intersects = any(mask_extent.intersects(tile_extent) for mask_extent in mask_extents_wgs84)
            if intersects:
                kept.append(tile_item)
            else:
                skipped += 1
                tile_item_id = str(tile_item.get("id") or "").strip() or "item"
                self._emit_log(
                    f"Source node {node_id}: skipping non-overlapping tile {tile_item_id} "
                    f"for {logical_source_key}",
                    Qgis.Info,
                )

        self._emit_log(
            f"Source node {node_id}: AOI prefilter kept {len(kept)}/{len(rows)} tile(s) "
            f"for {logical_source_key} (skipped={skipped}, unknown_geom={unknown_geom})",
            Qgis.Info,
        )
        if not kept:
            raise RuntimeError(
                f"Source node {node_id}: no source tiles intersect downstream AOI for {logical_source_key}"
            )
        return kept

    def _downstream_clip_mask_extents_wgs84(self, source_node_id):
        source_key = str(source_node_id or "").strip()
        if not source_key:
            return []

        extents = []
        visited = set()
        stack = list(self.outgoing.get(source_key, set()))
        while stack:
            node_id = str(stack.pop() or "").strip()
            if not node_id or node_id in visited:
                continue
            visited.add(node_id)

            node = self.node_map.get(node_id)
            if not isinstance(node, dict):
                continue
            node_type = str(node.get("type") or "").strip().lower()
            payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
            if node_type == "function" and str(payload.get("function_id") or "").strip() == "clip_to_aoi":
                mask_path = str(payload.get("aoi_effective_mask_path") or "").strip()
                if mask_path:
                    mask_extent = self._mask_extent_wgs84(mask_path)
                    if mask_extent is not None:
                        extents.append(mask_extent)
            for next_id in self.outgoing.get(node_id, set()):
                if next_id not in visited:
                    stack.append(next_id)
        return extents

    def _mask_extent_wgs84(self, mask_path):
        key = str(mask_path or "").strip()
        if not key:
            return None
        cached = self._mask_extent_cache_wgs84.get(key)
        if isinstance(cached, QgsRectangle):
            return QgsRectangle(cached)

        mask_layer = QgsVectorLayer(key, f"WorkflowMask-{Path(key).name}", "ogr")
        if not mask_layer.isValid():
            self._emit_log(f"Mask AOI prefilter skipped: invalid mask layer {key}", Qgis.Warning)
            self._mask_extent_cache_wgs84[key] = None
            return None

        extent = QgsRectangle(mask_layer.extent())
        if extent.isEmpty():
            self._emit_log(f"Mask AOI prefilter skipped: empty extent {key}", Qgis.Warning)
            self._mask_extent_cache_wgs84[key] = None
            return None

        try:
            src_crs = mask_layer.crs()
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            if src_crs.isValid() and src_crs != wgs84:
                transform = QgsCoordinateTransform(
                    src_crs,
                    wgs84,
                    QgsProject.instance().transformContext(),
                )
                extent = transform.transformBoundingBox(extent)
        except Exception as exc:
            self._emit_log(
                f"Mask AOI prefilter skipped: failed CRS transform for {key} ({exc})",
                Qgis.Warning,
            )
            self._mask_extent_cache_wgs84[key] = None
            return None

        self._mask_extent_cache_wgs84[key] = QgsRectangle(extent)
        return QgsRectangle(extent)

    def _item_extent_wgs84(self, item):
        row = item if isinstance(item, dict) else {}
        bbox = row.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            try:
                min_x = float(min(bbox[0], bbox[2]))
                max_x = float(max(bbox[0], bbox[2]))
                min_y = float(min(bbox[1], bbox[3]))
                max_y = float(max(bbox[1], bbox[3]))
                if max_x > min_x and max_y > min_y:
                    return QgsRectangle(min_x, min_y, max_x, max_y)
            except Exception:
                pass

        geometry_payload = row.get("geometry")
        if isinstance(geometry_payload, dict):
            try:
                geom = QgsGeometry.fromGeoJson(json.dumps(geometry_payload))
                if geom is not None and not geom.isEmpty():
                    return QgsRectangle(geom.boundingBox())
            except Exception:
                return None
        return None

    def _emit_clip_diagnostics(self, *, node_id, mask_path, raster_inputs):
        mask_layer = QgsVectorLayer(str(mask_path), f"WorkflowMask-{node_id}", "ogr")
        if not mask_layer.isValid():
            self._emit_log(
                f"clip_to_aoi node {node_id}: mask layer diagnostics unavailable (invalid layer: {mask_path})",
                Qgis.Warning,
            )
            return

        mask_extent = mask_layer.extent()
        mask_crs = mask_layer.crs().authid() if mask_layer.crs().isValid() else "unknown"
        mask_geometry = self._vector_layer_union_geometry(mask_layer)
        geometry_mode = "feature_union" if mask_geometry is not None and not mask_geometry.isEmpty() else "extent_fallback"
        if geometry_mode == "extent_fallback":
            mask_geometry = QgsGeometry.fromRect(mask_extent)
        self._emit_log(
            f"clip_to_aoi node {node_id}: mask diagnostics "
            f"crs={mask_crs} extent={self._format_extent(mask_extent)} "
            f"features={mask_layer.featureCount()} geometry_mode={geometry_mode}",
            Qgis.Info,
        )

        for input_path in raster_inputs:
            raster_layer = QgsRasterLayer(str(input_path), f"WorkflowRaster-{node_id}")
            if not raster_layer.isValid():
                self._emit_log(
                    f"clip_to_aoi node {node_id}: input diagnostics unavailable (invalid raster: {input_path})",
                    Qgis.Warning,
                )
                continue

            raster_extent = raster_layer.extent()
            raster_crs = raster_layer.crs()
            transformed_mask_extent = QgsRectangle(mask_extent)
            transformed_mask_geometry = QgsGeometry(mask_geometry)
            intersects = True
            transform_note = "same_crs"
            overlap_ratio = 0.0
            overlap_area = 0.0
            mask_area = 0.0
            try:
                if mask_layer.crs().isValid() and raster_crs.isValid() and mask_layer.crs() != raster_crs:
                    transform = QgsCoordinateTransform(
                        mask_layer.crs(),
                        raster_crs,
                        QgsProject.instance().transformContext(),
                    )
                    transformed_mask_extent = transform.transformBoundingBox(mask_extent)
                    transformed_mask_geometry.transform(transform)
                    transform_note = "transformed"
                raster_geometry = QgsGeometry.fromRect(raster_extent)
                intersects = raster_geometry.intersects(transformed_mask_geometry)
                mask_area = max(0.0, float(transformed_mask_geometry.area()))
                if intersects and mask_area > 0.0:
                    overlap_geometry = raster_geometry.intersection(transformed_mask_geometry)
                    if overlap_geometry is not None and not overlap_geometry.isEmpty():
                        overlap_area = max(0.0, float(overlap_geometry.area()))
                        overlap_ratio = max(0.0, min(1.0, overlap_area / mask_area))
            except Exception as exc:
                intersects = False
                transform_note = f"transform_error:{exc}"

            low_overlap = bool(mask_area > 0.0 and overlap_ratio < 0.50)
            level = Qgis.Warning if (not intersects or low_overlap) else Qgis.Info
            self._emit_log(
                f"clip_to_aoi node {node_id}: overlap check input={input_path} "
                f"raster_crs={(raster_crs.authid() if raster_crs.isValid() else 'unknown')} "
                f"raster_extent={self._format_extent(raster_extent)} "
                f"mask_extent_raster_crs={self._format_extent(transformed_mask_extent)} "
                f"intersects={intersects} overlap={overlap_ratio * 100.0:.1f}% "
                f"(threshold>=50.0%, mask_area={mask_area:.6f}, overlap_area={overlap_area:.6f}) "
                f"({transform_note})",
                level,
            )
            if low_overlap:
                self._emit_log(
                    f"clip_to_aoi node {node_id}: warning low overlap for input={input_path} "
                    f"({overlap_ratio * 100.0:.1f}% of clip polygon covered; minimum is 50.0%).",
                    Qgis.Warning,
                )

    @staticmethod
    def _vector_layer_union_geometry(layer):
        if layer is None:
            return None
        geometries = []
        try:
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue
                geometries.append(QgsGeometry(geom))
        except Exception:
            return None

        if not geometries:
            return None
        try:
            union_geom = QgsGeometry.unaryUnion(geometries)
            if union_geom is not None and not union_geom.isEmpty():
                return union_geom
        except Exception:
            pass

        merged = QgsGeometry(geometries[0])
        for geom in geometries[1:]:
            try:
                merged = merged.combine(geom)
            except Exception:
                continue
        if merged is not None and not merged.isEmpty():
            return merged
        return None

    def _raster_diagnostics(self, raster_path):
        layer = QgsRasterLayer(str(raster_path), "WorkflowRasterDiagnostics")
        if not layer.isValid():
            return f"path={raster_path} invalid_raster"
        crs_text = layer.crs().authid() if layer.crs().isValid() else "unknown"
        return (
            f"path={raster_path} crs={crs_text} size={layer.width()}x{layer.height()} "
            f"bands={layer.bandCount()} extent={self._format_extent(layer.extent())}"
        )

    @staticmethod
    def _format_extent(extent):
        if extent is None:
            return "(none)"
        try:
            return (
                f"({extent.xMinimum():.6f}, {extent.yMinimum():.6f}, "
                f"{extent.xMaximum():.6f}, {extent.yMaximum():.6f})"
            )
        except Exception:
            return "(invalid)"

    @classmethod
    def _build_output_path(cls, base_output_path, index, total, *, artifact=None, used_paths=None):
        base = Path(str(base_output_path or "").strip())
        token_values = {
            "index": str(int(index) + 1),
            "index_03": f"{int(index) + 1:03d}",
            "item_id": cls._sanitize_output_token((artifact or {}).get("item_id")),
            "collection_date": cls._sanitize_output_token((artifact or {}).get("collection_date")),
            "collection_datetime": cls._sanitize_output_token((artifact or {}).get("collection_datetime")),
            "logical_source_key": cls._sanitize_output_token((artifact or {}).get("logical_source_key")),
        }

        template_text = str(base)
        has_token = any(f"{{{key}}}" in template_text for key in token_values)
        if has_token:
            rendered_text = template_text
            for key, value in token_values.items():
                rendered_text = rendered_text.replace(f"{{{key}}}", str(value))
            candidate = Path(rendered_text)
            if not candidate.suffix:
                candidate = candidate.with_suffix(base.suffix or ".tif")
            return str(cls._dedupe_output_path(candidate, used_paths))

        if total <= 1:
            return str(cls._dedupe_output_path(base, used_paths))
        stem = base.stem or "output"
        suffix = base.suffix or ".tif"
        candidate = base.with_name(f"{stem}_{int(index) + 1:03d}{suffix}")
        return str(cls._dedupe_output_path(candidate, used_paths))

    @staticmethod
    def _sanitize_output_token(value):
        text = str(value or "").strip()
        if not text:
            return "unknown"
        # Keep token expansions conservative for filesystem/GDAL compatibility.
        sanitized = re.sub(r"[^0-9A-Za-z_-]+", "_", text).strip("_-")
        return sanitized or "unknown"

    @staticmethod
    def _dedupe_output_path(path_obj, used_paths):
        candidate = Path(path_obj)
        tracker = used_paths if isinstance(used_paths, set) else None
        if tracker is None:
            return candidate
        key = str(candidate).lower()
        if key not in tracker:
            tracker.add(key)
            return candidate
        base_stem = candidate.stem or "output"
        suffix = candidate.suffix or ".tif"
        parent = candidate.parent
        serial = 2
        while True:
            retry = parent / f"{base_stem}_{serial:03d}{suffix}"
            retry_key = str(retry).lower()
            if retry_key not in tracker:
                tracker.add(retry_key)
                return retry
            serial += 1

    @staticmethod
    def _guess_asset_extension(url, data):
        suffix = Path(urlparse(str(url or "")).path).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".jp2", ".webp"}:
            return suffix
        sample = bytes(data[:16] if data else b"")
        if sample.startswith(b"\x89PNG"):
            return ".png"
        if sample.startswith(b"\xff\xd8"):
            return ".jpg"
        if sample.startswith(b"II*\x00") or sample.startswith(b"MM\x00*"):
            return ".tif"
        if sample.startswith(b"\x00\x00\x00\x0cjP  \r\n\x87\n") or sample[4:8] == b"jP  ":
            return ".jp2"
        return ".bin"
