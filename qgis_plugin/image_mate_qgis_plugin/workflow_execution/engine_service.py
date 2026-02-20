# -*- coding: utf-8 -*-
"""Reusable workflow engine service.

This module extracts workflow preparation and validation logic from the QGIS UI
layer so the workflow engine can run with or without the front-end dock.
"""

from pathlib import Path
from datetime import datetime, timezone
import shutil

from qgis import processing
from qgis.core import (
    Qgis,
    QgsProject,
    QgsVectorLayer,
)

from .worker import WorkflowExecutionWorker

ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK = "for_each_image_in_stack"


class WorkflowEngineService:
    def __init__(self, *, temp_dir, iface=None, log_callback=None):
        self.temp_dir = Path(temp_dir)
        self.iface = iface
        self._log_callback = log_callback

    def set_iface(self, iface):
        self.iface = iface

    def set_log_callback(self, callback):
        self._log_callback = callback

    def _log(self, message, level=Qgis.Info):
        callback = self._log_callback
        if callback is None:
            return
        text = str(message or "").strip()
        if not text:
            return
        try:
            callback(text, level)
        except TypeError:
            callback(text)

    def prepare_graph(self, workflow_payload):
        payload = workflow_payload if isinstance(workflow_payload, dict) else {}
        raw_nodes = payload.get("nodes")
        raw_edges = payload.get("edges")
        raw_nodes = raw_nodes if isinstance(raw_nodes, list) else []
        raw_edges = raw_edges if isinstance(raw_edges, list) else []

        node_map = {}
        for row in raw_nodes:
            if not isinstance(row, dict):
                continue
            node_id = str(row.get("id") or "").strip()
            if not node_id:
                continue
            node_payload = row.get("payload")
            node_map[node_id] = {
                "id": node_id,
                "type": str(row.get("type") or "").strip().lower(),
                "label": str(row.get("label") or node_id).strip(),
                "payload": dict(node_payload or {}) if isinstance(node_payload, dict) else {},
            }

        incoming = {node_id: set() for node_id in node_map}
        for row in raw_edges:
            if not isinstance(row, dict):
                continue
            source_id = str(row.get("source") or "").strip()
            target_id = str(row.get("target") or "").strip()
            if not source_id or not target_id:
                self._log(f"Ignoring malformed edge: {row}", level=Qgis.Warning)
                continue
            if source_id not in node_map or target_id not in node_map:
                self._log(
                    f"Ignoring edge {source_id}->{target_id}: node id not found in node list.",
                    level=Qgis.Warning,
                )
                continue
            if source_id == target_id:
                self._log(
                    f"Ignoring self-referencing edge {source_id}->{target_id}.",
                    level=Qgis.Warning,
                )
                continue
            incoming[target_id].add(source_id)

        source_node_ids = [
            node_id
            for node_id, node in node_map.items()
            if str(node.get("type") or "").strip().lower() == "source"
        ]
        if not source_node_ids:
            return node_map, incoming

        outgoing = {node_id: set() for node_id in node_map}
        for target_id, source_ids in incoming.items():
            for source_id in source_ids:
                outgoing[source_id].add(target_id)

        reachable = set()
        queue = list(source_node_ids)
        while queue:
            current = queue.pop(0)
            if current in reachable:
                continue
            reachable.add(current)
            for downstream_id in sorted(outgoing.get(current, set())):
                if downstream_id not in reachable:
                    queue.append(downstream_id)

        disconnected = [node_id for node_id in node_map if node_id not in reachable]
        if disconnected:
            self._log(
                "Skipping disconnected node(s) not reachable from a source: "
                + ", ".join(disconnected),
                level=Qgis.Warning,
            )

        filtered_node_map = {
            node_id: row
            for node_id, row in node_map.items()
            if node_id in reachable
        }
        filtered_incoming = {
            node_id: {source_id for source_id in incoming.get(node_id, set()) if source_id in reachable}
            for node_id in filtered_node_map
        }
        return filtered_node_map, filtered_incoming

    def _validate_clip_to_aoi_payload(self, *, issues, node_id, payload, context_label):
        source_type = str(payload.get("aoi_source_type") or "file").strip().lower()
        output_path = str(payload.get("output_path") or "").strip()
        aoi_layer_id = str(payload.get("aoi_project_layer_id") or "").strip()
        aoi_file = str(payload.get("aoi_path") or "").strip()
        if source_type == "project_layer":
            if not aoi_layer_id:
                issues.append(f"{node_id}: {context_label} missing AOI project layer id")
            elif QgsProject.instance().mapLayer(aoi_layer_id) is None:
                issues.append(f"{node_id}: AOI project layer not found ({aoi_layer_id})")
        else:
            if not aoi_file:
                issues.append(f"{node_id}: {context_label} missing AOI file path")
            elif not Path(aoi_file).exists():
                issues.append(f"{node_id}: AOI file not found ({aoi_file})")
        if not output_path:
            issues.append(f"{node_id}: {context_label} missing output path")

    def validate_node_configs(self, node_map):
        issues = []
        for node_id, node in (node_map or {}).items():
            node_type = str(node.get("type") or "").strip().lower()
            payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}

            if node_type == "source":
                item_ids = payload.get("item_ids")
                item_ids = item_ids if isinstance(item_ids, list) else []
                item_ids = [str(v or "").strip() for v in item_ids if str(v or "").strip()]
                if not item_ids:
                    issues.append(f"{node_id}: source node has no item_ids")
                continue

            if node_type == "adapter":
                adapter_id = str(payload.get("adapter_id") or "").strip()
                if not adapter_id:
                    issues.append(f"{node_id}: adapter node missing adapter_id")
                elif adapter_id != ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK:
                    issues.append(f"{node_id}: unsupported adapter_id '{adapter_id}'")
                adapted_function_id = str(payload.get("adapted_function_id") or "").strip()
                if not adapted_function_id:
                    continue
                adapted_payload = payload.get("adapted_function_payload")
                if not isinstance(adapted_payload, dict):
                    issues.append(f"{node_id}: adapter node missing adapted_function_payload object")
                    continue
                if adapted_function_id == "clip_to_aoi":
                    self._validate_clip_to_aoi_payload(
                        issues=issues,
                        node_id=node_id,
                        payload=adapted_payload,
                        context_label="adapter clip_to_aoi",
                    )
                else:
                    issues.append(f"{node_id}: unsupported adapted_function_id '{adapted_function_id}'")
                continue

            if node_type != "function":
                continue

            function_id = str(payload.get("function_id") or "").strip()
            if function_id == "clip_to_aoi":
                self._validate_clip_to_aoi_payload(
                    issues=issues,
                    node_id=node_id,
                    payload=payload,
                    context_label="clip_to_aoi",
                )
            elif function_id == "temporal_stack_to_video":
                output_path = str(payload.get("output_path") or "").strip()
                if not output_path:
                    issues.append(f"{node_id}: temporal_stack_to_video missing output path")
                if shutil.which("ffmpeg") is None:
                    issues.append(f"{node_id}: temporal_stack_to_video requires ffmpeg in PATH")

                pause_value = payload.get("pause_between_dates_seconds")
                try:
                    if float(pause_value if pause_value is not None else 0.0) < 0.0:
                        issues.append(
                            f"{node_id}: temporal_stack_to_video pause_between_dates_seconds must be >= 0"
                        )
                except Exception:
                    issues.append(f"{node_id}: temporal_stack_to_video pause_between_dates_seconds is invalid")

                fps_value = payload.get("frames_per_second")
                try:
                    if int(fps_value if fps_value is not None else 2) <= 0:
                        issues.append(f"{node_id}: temporal_stack_to_video frames_per_second must be > 0")
                except Exception:
                    issues.append(f"{node_id}: temporal_stack_to_video frames_per_second is invalid")

                horizontal_align = str(payload.get("text_horizontal_align") or "left").strip().lower()
                vertical_align = str(payload.get("text_vertical_align") or "top").strip().lower()
                if horizontal_align not in {"left", "center", "right"}:
                    issues.append(
                        f"{node_id}: temporal_stack_to_video text_horizontal_align must be left|center|right"
                    )
                if vertical_align not in {"top", "bottom"}:
                    issues.append(f"{node_id}: temporal_stack_to_video text_vertical_align must be top|bottom")

                for key in ("overlay_vector_layer_id", "overlay_shapefile_layer_id"):
                    layer_id = str(payload.get(key) or "").strip()
                    if not layer_id:
                        continue
                    layer = QgsProject.instance().mapLayer(layer_id)
                    if layer is None:
                        issues.append(f"{node_id}: temporal_stack_to_video overlay layer not found ({layer_id})")
                        continue
                    if not isinstance(layer, QgsVectorLayer):
                        issues.append(
                            f"{node_id}: temporal_stack_to_video overlay layer is not vector ({layer_id})"
                        )
            else:
                issues.append(f"{node_id}: unsupported function_id '{function_id}'")

        if issues:
            message = "Workflow validation failed:\n- " + "\n- ".join(issues)
            raise RuntimeError(message)

    def prepare_execution_node_map(self, node_map):
        prepared = {}
        for node_id, node in (node_map or {}).items():
            row = {
                "id": str(node.get("id") or node_id).strip(),
                "type": str(node.get("type") or "").strip().lower(),
                "label": str(node.get("label") or node_id).strip(),
                "payload": dict(node.get("payload") or {}),
            }

            node_type = row["type"]
            payload = row["payload"]
            if node_type == "function":
                function_id = str(payload.get("function_id") or "").strip()
                if function_id == "clip_to_aoi":
                    self._prepare_clip_to_aoi_payload(node_id=row["id"], payload=payload)
                elif function_id == "temporal_stack_to_video":
                    self._prepare_temporal_stack_to_video_payload(node_id=row["id"], payload=payload)
            elif node_type == "adapter":
                self._prepare_adapter_payload(node_id=row["id"], payload=payload)
            prepared[row["id"]] = row
        return prepared

    def _prepare_adapter_payload(self, *, node_id, payload):
        adapter_id = str(payload.get("adapter_id") or "").strip()
        if not adapter_id:
            raise RuntimeError(f"{node_id}: adapter node is missing adapter_id")
        if adapter_id != ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK:
            raise RuntimeError(f"{node_id}: unsupported adapter_id '{adapter_id}'")
        payload["adapter_id"] = adapter_id

        adapted_function_id = str(payload.get("adapted_function_id") or "").strip()
        if not adapted_function_id:
            return
        adapted_payload = payload.get("adapted_function_payload")
        if not isinstance(adapted_payload, dict):
            raise RuntimeError(f"{node_id}: adapter node missing adapted_function_payload object")
        adapted_payload = dict(adapted_payload)

        if adapted_function_id == "clip_to_aoi":
            self._prepare_clip_to_aoi_payload(node_id=node_id, payload=adapted_payload)
        else:
            raise RuntimeError(f"{node_id}: unsupported adapted_function_id '{adapted_function_id}'")
        payload["adapted_function_payload"] = adapted_payload

    def _prepare_clip_to_aoi_payload(self, *, node_id, payload):
        source_type = str(payload.get("aoi_source_type") or "file").strip().lower()
        if source_type == "project_layer":
            layer_id = str(payload.get("aoi_project_layer_id") or "").strip()
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer is None:
                raise RuntimeError(f"{node_id}: AOI project layer not found ({layer_id})")
            if not isinstance(layer, QgsVectorLayer):
                raise RuntimeError(f"{node_id}: AOI layer is not a vector layer ({layer_id})")
            if not layer.isValid():
                raise RuntimeError(f"{node_id}: AOI project layer is invalid ({layer_id})")

            self.temp_dir.mkdir(parents=True, exist_ok=True)
            file_name = (
                f"workflow_{node_id.replace(':', '_').replace('/', '_')}_mask_"
                f"{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.gpkg"
            )
            mask_path = self.temp_dir / file_name
            result = processing.run(
                "native:savefeatures",
                {"INPUT": layer, "OUTPUT": str(mask_path)},
            )
            resolved_mask_path = str(result.get("OUTPUT") or mask_path).strip()
            if not resolved_mask_path or not Path(resolved_mask_path).exists():
                raise RuntimeError(
                    f"{node_id}: failed to materialize AOI project layer to temporary file ({resolved_mask_path})"
                )
            payload["aoi_effective_mask_path"] = resolved_mask_path
            payload["aoi_effective_mask_desc"] = f"project-layer:{layer_id}"
            self._log(f"{node_id}: AOI project layer materialized -> {resolved_mask_path}", level=Qgis.Info)
            return

        aoi_path = str(payload.get("aoi_path") or "").strip()
        if not aoi_path:
            raise RuntimeError(f"{node_id}: AOI file path is required for clip_to_aoi")
        if not Path(aoi_path).exists():
            raise RuntimeError(f"{node_id}: AOI file not found ({aoi_path})")
        payload["aoi_effective_mask_path"] = aoi_path
        payload["aoi_effective_mask_desc"] = f"aoi-file:{aoi_path}"

    @staticmethod
    def _prepare_temporal_stack_to_video_payload(*, payload, **_kwargs):
        # temporal_stack_to_video no longer clips inputs; keep keys normalized for compatibility.
        payload["clip_mode"] = "none"
        payload["clip_effective_mask_path"] = ""
        payload["clip_effective_mask_desc"] = ""
        payload["aoi_effective_mask_path"] = ""
        payload["aoi_effective_mask_desc"] = ""

    def preflight(self, workflow_payload):
        node_map, incoming = self.prepare_graph(workflow_payload)
        self.validate_node_configs(node_map)
        prepared_node_map = self.prepare_execution_node_map(node_map)
        return prepared_node_map, incoming

    @staticmethod
    def build_worker(*, source_service, search_items, temp_dir, node_map, incoming):
        return WorkflowExecutionWorker(
            source_service=source_service,
            search_items=search_items,
            temp_dir=temp_dir,
            node_map=node_map,
            incoming=incoming,
        )

    def execute_sync(
        self,
        *,
        workflow_payload,
        source_service,
        search_items,
        log_callback=None,
        progress_callback=None,
        node_state_callback=None,
        active_node_callback=None,
    ):
        prepared_node_map, incoming = self.preflight(workflow_payload)
        worker = self.build_worker(
            source_service=source_service,
            search_items=search_items,
            temp_dir=self.temp_dir,
            node_map=prepared_node_map,
            incoming=incoming,
        )

        if callable(log_callback):
            worker.log.connect(log_callback)
        if callable(progress_callback):
            worker.progress.connect(progress_callback)
        if callable(node_state_callback):
            worker.node_state.connect(node_state_callback)
        if callable(active_node_callback):
            worker.active_node.connect(active_node_callback)

        result_holder = {}
        failure_holder = {}

        def _on_finished(result):
            result_holder["value"] = result if isinstance(result, dict) else {}

        def _on_failed(error_text, traceback_text):
            failure_holder["error_text"] = str(error_text or "").strip() or "Workflow execution failed."
            failure_holder["traceback_text"] = str(traceback_text or "").strip()

        worker.finished.connect(_on_finished)
        worker.failed.connect(_on_failed)
        worker.run()

        if failure_holder:
            error_message = failure_holder.get("error_text") or "Workflow execution failed."
            traceback_text = failure_holder.get("traceback_text") or ""
            if traceback_text:
                raise RuntimeError(f"{error_message}\n{traceback_text}")
            raise RuntimeError(error_message)

        return result_holder.get("value") or {"outputs_by_node": {}}
