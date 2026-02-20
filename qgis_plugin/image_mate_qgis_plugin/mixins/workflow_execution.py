# -*- coding: utf-8 -*-
"""Workflow orchestration mixin for Image Mate plugin."""

from pathlib import Path
from datetime import datetime, timezone
import shutil
import time
import traceback

from qgis import processing
from qgis.PyQt.QtCore import QThread
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsRasterLayer,
    QgsVectorLayer,
)

from ..workflow_execution import WorkflowEngineService

ADAPTER_ID_FOR_EACH_IMAGE_IN_STACK = "for_each_image_in_stack"


class WorkflowExecutionMixin:
    def handle_execute_workflow_request(self, workflow_payload):
        payload = workflow_payload if isinstance(workflow_payload, dict) else {}
        if self._workflow_running or (self._workflow_thread is not None and self._workflow_thread.isRunning()):
            self._workflow_log(
                "Execution request ignored: another workflow execution is still running.",
                level=Qgis.Warning,
            )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Workflow execution is already running. Wait for it to finish.",
                level=Qgis.Warning,
                duration=8,
            )
            return

        engine_service = self._workflow_create_engine_service()
        node_map, incoming = engine_service.prepare_graph(payload)
        total_nodes = len(node_map)
        if total_nodes == 0:
            self._workflow_log("Execution aborted: workflow has no executable nodes.", level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                "Workflow execution aborted: no executable nodes.",
                level=Qgis.Warning,
                duration=8,
            )
            return

        try:
            engine_service.validate_node_configs(node_map)
            prepared_node_map = engine_service.prepare_execution_node_map(node_map)
        except Exception as exc:
            self._workflow_log(f"Workflow preflight failed: {exc}", level=Qgis.Warning)
            self._workflow_log(traceback.format_exc(), level=Qgis.Warning)
            self._workflow_set_progress(0, total_nodes, f"Workflow preflight failed: {exc}")
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Workflow preflight failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            return

        if self.dock is not None:
            self.dock.reset_workflow_execution_visuals(clear_log=True)
            self.dock.set_workflow_execution_progress(0, total_nodes, "Preparing workflow execution...")
            self.dock.set_workflow_canvas_locked(True)
            self.dock.set_workflow_active_node("")
            for node_id in prepared_node_map:
                self.dock.set_workflow_node_execution_state(node_id, "pending")
            if hasattr(self.dock, "workflow_tabs") and hasattr(self.dock, "workflow_log_tab"):
                self.dock.workflow_tabs.setCurrentWidget(self.dock.workflow_log_tab)

        self._workflow_log(
            f"Execution started: {total_nodes} node(s), "
            f"{sum(len(v) for v in incoming.values())} edge(s)."
        )
        self._workflow_log(f"Node IDs: {', '.join(sorted(prepared_node_map.keys()))}")

        self._workflow_run_started_at = time.perf_counter()
        self._workflow_total_nodes = total_nodes
        self._workflow_node_types = {
            str(node_id): str(node.get("type") or "").strip().lower()
            for node_id, node in prepared_node_map.items()
        }
        self._workflow_node_adapter_embedded_function = {}
        for node_id, node in prepared_node_map.items():
            node_type = str(node.get("type") or "").strip().lower()
            payload = node.get("payload") if isinstance(node.get("payload"), dict) else {}
            if node_type != "adapter":
                continue
            self._workflow_node_adapter_embedded_function[str(node_id)] = bool(
                str(payload.get("adapted_function_id") or "").strip()
            )
        self._workflow_running = True

        self._cleanup_workflow_worker()
        self._workflow_thread = QThread(self.iface.mainWindow())
        self._workflow_worker = engine_service.build_worker(
            source_service=self.source_service,
            search_items=self.search_items,
            temp_dir=self.temp_dir,
            node_map=prepared_node_map,
            incoming=incoming,
        )
        self._workflow_worker.moveToThread(self._workflow_thread)

        self._workflow_thread.started.connect(self._workflow_worker.run)
        self._workflow_worker.log.connect(self._on_workflow_worker_log)
        self._workflow_worker.progress.connect(self._on_workflow_worker_progress)
        self._workflow_worker.node_state.connect(self._on_workflow_worker_node_state)
        self._workflow_worker.active_node.connect(self._on_workflow_worker_active_node)
        self._workflow_worker.finished.connect(self._on_workflow_worker_finished)
        self._workflow_worker.failed.connect(self._on_workflow_worker_failed)
        self._workflow_worker.finished.connect(self._workflow_thread.quit)
        self._workflow_worker.failed.connect(self._workflow_thread.quit)
        self._workflow_thread.finished.connect(self._cleanup_workflow_worker)

        self._workflow_thread.start()

    def _workflow_prepare_execution_node_map(self, node_map):
        prepared = {}
        for node_id, node in node_map.items():
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
                    self._workflow_prepare_clip_to_aoi_payload(node_id=row["id"], payload=payload)
                elif function_id == "temporal_stack_to_video":
                    self._workflow_prepare_temporal_stack_to_video_payload(node_id=row["id"], payload=payload)
            elif node_type == "adapter":
                self._workflow_prepare_adapter_payload(node_id=row["id"], payload=payload)
            prepared[row["id"]] = row
        return prepared

    def _workflow_prepare_adapter_payload(self, *, node_id, payload):
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
            self._workflow_prepare_clip_to_aoi_payload(node_id=node_id, payload=adapted_payload)
        else:
            raise RuntimeError(f"{node_id}: unsupported adapted_function_id '{adapted_function_id}'")
        payload["adapted_function_payload"] = adapted_payload

    def _workflow_prepare_clip_to_aoi_payload(self, *, node_id, payload):
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
            self._workflow_log(
                f"{node_id}: AOI project layer materialized -> {resolved_mask_path}"
            )
            return

        aoi_path = str(payload.get("aoi_path") or "").strip()
        if not aoi_path:
            raise RuntimeError(f"{node_id}: AOI file path is required for clip_to_aoi")
        if not Path(aoi_path).exists():
            raise RuntimeError(f"{node_id}: AOI file not found ({aoi_path})")
        payload["aoi_effective_mask_path"] = aoi_path
        payload["aoi_effective_mask_desc"] = f"aoi-file:{aoi_path}"

    def _workflow_prepare_temporal_stack_to_video_payload(self, *, node_id, payload):
        # temporal_stack_to_video no longer clips inputs; keep keys normalized for compatibility.
        payload["clip_mode"] = "none"
        payload["clip_effective_mask_path"] = ""
        payload["clip_effective_mask_desc"] = ""
        payload["aoi_effective_mask_path"] = ""
        payload["aoi_effective_mask_desc"] = ""

    def _workflow_materialize_canvas_extent_mask(self, *, node_id):
        canvas = self.iface.mapCanvas() if self.iface is not None else None
        if canvas is None:
            raise RuntimeError(f"{node_id}: map canvas is unavailable for canvas clipping")

        extent = QgsRectangle(canvas.extent())
        if extent.isEmpty():
            raise RuntimeError(f"{node_id}: map canvas extent is empty; cannot clip to canvas")

        map_settings = canvas.mapSettings()
        canvas_crs = (
            map_settings.destinationCrs() if map_settings is not None else QgsCoordinateReferenceSystem()
        )
        if not canvas_crs.isValid():
            canvas_crs = QgsProject.instance().crs()
        if not canvas_crs.isValid():
            raise RuntimeError(f"{node_id}: map canvas CRS is invalid; cannot clip to canvas")

        crs_authid = str(canvas_crs.authid() or "").strip()
        if not crs_authid:
            raise RuntimeError(f"{node_id}: map canvas CRS has no authid; cannot clip to canvas")

        mask_layer = QgsVectorLayer(
            f"Polygon?crs={crs_authid}",
            f"WorkflowCanvasMask-{node_id}",
            "memory",
        )
        if not mask_layer.isValid():
            raise RuntimeError(f"{node_id}: failed to allocate temporary canvas mask layer")

        feature = QgsFeature()
        feature.setGeometry(QgsGeometry.fromRect(extent))
        add_result = mask_layer.dataProvider().addFeatures([feature])
        add_ok = bool(add_result[0]) if isinstance(add_result, tuple) else bool(add_result)
        if not add_ok:
            raise RuntimeError(f"{node_id}: failed to build temporary canvas mask geometry")
        mask_layer.updateExtents()

        file_name = (
            f"workflow_{node_id.replace(':', '_').replace('/', '_')}_canvas_mask_"
            f"{datetime.now(tz=timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.gpkg"
        )
        mask_path = self.temp_dir / file_name
        result = processing.run(
            "native:savefeatures",
            {"INPUT": mask_layer, "OUTPUT": str(mask_path)},
        )
        resolved_mask_path = str(result.get("OUTPUT") or mask_path).strip()
        if not resolved_mask_path or not Path(resolved_mask_path).exists():
            raise RuntimeError(
                f"{node_id}: failed to materialize canvas extent to temporary file ({resolved_mask_path})"
            )

        self._workflow_log(f"{node_id}: canvas extent materialized -> {resolved_mask_path}")
        return resolved_mask_path

    def _on_workflow_worker_log(self, message, level):
        self._workflow_log(message, level=level)

    def _on_workflow_worker_progress(self, completed, total, status_text):
        self._workflow_set_progress(completed, total, status_text)

    def _on_workflow_worker_node_state(self, node_id, state):
        self._workflow_set_node_state(node_id, state)

    def _on_workflow_worker_active_node(self, node_id):
        if self.dock is not None and hasattr(self.dock, "set_workflow_active_node"):
            self.dock.set_workflow_active_node(node_id)

    def _on_workflow_worker_finished(self, result):
        result_payload = result if isinstance(result, dict) else {}
        outputs_by_node = result_payload.get("outputs_by_node")
        outputs_by_node = outputs_by_node if isinstance(outputs_by_node, dict) else {}

        try:
            added_layers, output_artifacts = self._workflow_attach_outputs(outputs_by_node)
            elapsed_s = max(0.0, float(time.perf_counter() - float(self._workflow_run_started_at or 0.0)))
            self._workflow_set_progress(
                self._workflow_total_nodes,
                self._workflow_total_nodes,
                f"Workflow execution completed in {elapsed_s:.2f}s.",
            )
            self._workflow_log(
                f"Workflow execution completed successfully in {elapsed_s:.2f}s | "
                f"output_artifacts={output_artifacts} | layers_added={added_layers}"
            )
            self.iface.messageBar().pushMessage(
                "Image Mate",
                (
                    f"Workflow completed: {self._workflow_total_nodes} node(s), "
                    f"{added_layers}/{output_artifacts} output layer(s) added."
                ),
                level=Qgis.Success,
                duration=10,
            )
        except Exception as exc:
            self._workflow_log(f"Workflow post-processing failed: {exc}", level=Qgis.Warning)
            self._workflow_log(traceback.format_exc(), level=Qgis.Warning)
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Workflow completed with post-processing errors: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
        finally:
            if self.dock is not None:
                self.dock.set_workflow_active_node("")
                self.dock.set_workflow_canvas_locked(False)
            self._workflow_running = False
            self._workflow_run_started_at = 0.0
            self._workflow_total_nodes = 0
            self._workflow_node_types = {}
            self._workflow_node_adapter_embedded_function = {}

    def _on_workflow_worker_failed(self, error_text, traceback_text):
        error_message = str(error_text or "").strip() or "Unknown workflow execution error."
        self._workflow_log(f"Workflow execution failed: {error_message}", level=Qgis.Warning)
        if traceback_text:
            self._workflow_log(str(traceback_text), level=Qgis.Warning)
        self._workflow_set_progress(0, self._workflow_total_nodes or 1, f"Workflow execution failed: {error_message}")
        self.iface.messageBar().pushMessage(
            "Image Mate",
            f"Workflow execution failed: {error_message}",
            level=Qgis.Warning,
            duration=12,
        )
        if self.dock is not None:
            self.dock.set_workflow_active_node("")
            self.dock.set_workflow_canvas_locked(False)
        self._workflow_running = False
        self._workflow_run_started_at = 0.0
        self._workflow_total_nodes = 0
        self._workflow_node_types = {}
        self._workflow_node_adapter_embedded_function = {}

    def _workflow_attach_outputs(self, outputs_by_node):
        added_layers = 0
        output_artifacts = 0
        for node_id, artifacts in outputs_by_node.items():
            node_key = str(node_id)
            node_type = self._workflow_node_types.get(node_key, "")
            if node_type == "source":
                continue
            if node_type == "adapter":
                embedded_map = getattr(self, "_workflow_node_adapter_embedded_function", {}) or {}
                has_embedded_function = bool(embedded_map.get(node_key))
                if not has_embedded_function:
                    self._workflow_log(
                        f"Skipping passthrough adapter outputs from node {node_id}.",
                        level=Qgis.Info,
                    )
                    continue
            artifact_rows = artifacts if isinstance(artifacts, list) else []
            for row in artifact_rows:
                if not isinstance(row, dict):
                    continue
                artifact_type = str(row.get("artifact_type") or "").strip().lower()
                if artifact_type == "video":
                    output_artifacts += 1
                    video_path = str(row.get("path") or "").strip()
                    if video_path:
                        self._workflow_log(
                            f"Generated workflow video output from node {node_id}: {video_path}",
                            level=Qgis.Info,
                        )
                    else:
                        self._workflow_log(
                            f"Video output from node {node_id} has empty path.",
                            level=Qgis.Warning,
                        )
                    continue
                if artifact_type != "raster":
                    continue
                output_artifacts += 1
                path_value = str(row.get("path") or "").strip()
                if not path_value:
                    self._workflow_log(
                        f"Skipping empty raster output from node {node_id}.",
                        level=Qgis.Warning,
                    )
                    continue
                output_path = Path(path_value)
                if not output_path.exists():
                    self._workflow_log(
                        f"Skipping missing raster output from node {node_id}: {output_path}",
                        level=Qgis.Warning,
                    )
                    continue

                layer_name = f"Image Mate Workflow Output {output_path.name}"
                layer = QgsRasterLayer(str(output_path), layer_name)
                if not layer.isValid():
                    self._workflow_log(
                        f"Output raster is invalid and will not be added: {output_path}",
                        level=Qgis.Warning,
                    )
                    continue

                self._add_layer_to_image_mate_group(layer)
                added_layers += 1
                self._workflow_log(
                    f"Added workflow output layer from node {node_id}: {output_path}",
                    level=Qgis.Info,
                )
        return added_layers, output_artifacts

    def _cleanup_workflow_worker(self):
        if self._workflow_worker is not None:
            try:
                self._workflow_worker.deleteLater()
            except Exception:
                pass
            self._workflow_worker = None
        if self._workflow_thread is not None:
            if self._workflow_thread.isRunning():
                return
            try:
                self._workflow_thread.deleteLater()
            except Exception:
                pass
            self._workflow_thread = None

    def _stop_workflow_execution(self, timeout_ms=0):
        thread = self._workflow_thread
        if thread is None:
            return
        if thread.isRunning():
            try:
                thread.quit()
                wait_ms = max(0, int(timeout_ms or 0))
                if wait_ms > 0:
                    thread.wait(wait_ms)
            except Exception:
                pass
        if thread.isRunning():
            self._workflow_log(
                "Workflow execution thread did not stop within the timeout window.",
                level=Qgis.Warning,
            )
            return
        self._workflow_running = False
        self._workflow_run_started_at = 0.0
        self._workflow_total_nodes = 0
        self._workflow_node_types = {}
        self._workflow_node_adapter_embedded_function = {}
        self._cleanup_workflow_worker()
        if self.dock is not None:
            self.dock.set_workflow_active_node("")
            self.dock.set_workflow_canvas_locked(False)

    def _workflow_log(self, text, level=Qgis.Info):
        message = str(text or "").strip()
        if not message:
            return
        self._append_search_log(f"[Workflow] {message}", level=level)
        self._append_debug_log(f"[Workflow] {message}", level=level)
        if self.dock is not None and hasattr(self.dock, "append_workflow_execution_log"):
            self.dock.append_workflow_execution_log(message)

    def _workflow_set_progress(self, completed, total, status_text):
        if self.dock is not None and hasattr(self.dock, "set_workflow_execution_progress"):
            self.dock.set_workflow_execution_progress(completed, total, status_text)

    def _workflow_set_node_state(self, node_id, state):
        if self.dock is not None and hasattr(self.dock, "set_workflow_node_execution_state"):
            self.dock.set_workflow_node_execution_state(node_id, state)

    def _workflow_create_engine_service(self):
        return WorkflowEngineService(
            temp_dir=self.temp_dir,
            iface=self.iface,
            log_callback=lambda message, level=Qgis.Info: self._workflow_log(message, level=level),
        )

    def execute_workflow_without_ui(
        self,
        workflow_payload,
        *,
        source_service=None,
        search_items=None,
        log_callback=None,
        progress_callback=None,
        node_state_callback=None,
        active_node_callback=None,
    ):
        engine_service = self._workflow_create_engine_service()
        return engine_service.execute_sync(
            workflow_payload=workflow_payload,
            source_service=source_service or self.source_service,
            search_items=search_items if search_items is not None else self.search_items,
            log_callback=log_callback,
            progress_callback=progress_callback,
            node_state_callback=node_state_callback,
            active_node_callback=active_node_callback,
        )

    def _workflow_prepare_graph(self, payload):
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
                self._workflow_log(f"Ignoring malformed edge: {row}", level=Qgis.Warning)
                continue
            if source_id not in node_map or target_id not in node_map:
                self._workflow_log(
                    f"Ignoring edge {source_id}->{target_id}: node id not found in node list.",
                    level=Qgis.Warning,
                )
                continue
            if source_id == target_id:
                self._workflow_log(
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
            self._workflow_log(
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

    def _workflow_validate_clip_to_aoi_payload(self, *, issues, node_id, payload, context_label):
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

    def _workflow_validate_node_configs(self, node_map):
        issues = []
        for node_id, node in node_map.items():
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
                    self._workflow_validate_clip_to_aoi_payload(
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
                self._workflow_validate_clip_to_aoi_payload(
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
