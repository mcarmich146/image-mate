# -*- coding: utf-8 -*-
"""Simulation orchestration mixin for coverage analysis."""

from __future__ import annotations

import json

from qgis.PyQt.QtCore import QThread
from qgis.core import Qgis
from qgis.core import QgsCoordinateReferenceSystem
from qgis.core import QgsCoordinateTransform
from qgis.core import QgsFeature
from qgis.core import QgsFillSymbol
from qgis.core import QgsGeometry
from qgis.core import QgsMarkerSymbol
from qgis.core import QgsPointXY
from qgis.core import QgsProject
from qgis.core import QgsSingleSymbolRenderer
from qgis.core import QgsVectorLayer
from qgis.core import QgsWkbTypes

from ..services.simulation_day_navigation import clamp_day_index
from ..services.simulation_day_navigation import end_day_index
from ..services.simulation_day_navigation import shift_day_index
from ..services.simulation_day_navigation import start_day_index
from ..simulation.coverage_worker import CoverageSimulationWorker
from ..simulation.revisit_worker import PointRevisitSimulationWorker


class SimulationExecutionMixin:
    """Mixin adding Simulation tab execution lifecycle."""

    def _simulation_bind_dock_data(self):
        if self.dock is None:
            return
        try:
            config = self.simulation_config_service.load_config()
        except Exception as exc:
            config = self.simulation_config_service.default_config()
            if hasattr(self, "_append_search_log"):
                self._append_search_log(f"Simulation config load failed: {exc}", level=Qgis.Warning)
        if hasattr(self.dock, "set_simulation_constellation"):
            self.dock.set_simulation_constellation(config)
        if hasattr(self.dock, "set_simulation_status"):
            if bool(self._simulation_running):
                self.dock.set_simulation_status("Simulation status: running...")
            elif self._simulation_result:
                self.dock.set_simulation_status("Simulation status: completed.")
            else:
                self.dock.set_simulation_status("Simulation status: idle")
        if hasattr(self.dock, "set_simulation_progress"):
            self.dock.set_simulation_progress(0, 1, "Ready.")
        if hasattr(self.dock, "set_simulation_summary"):
            self.dock.set_simulation_summary({})
        if hasattr(self.dock, "set_simulation_day"):
            self.dock.set_simulation_day({})
        if hasattr(self.dock, "set_simulation_revisit_summary"):
            self.dock.set_simulation_revisit_summary({})
        if hasattr(self.dock, "set_simulation_revisit_events"):
            self.dock.set_simulation_revisit_events([])
        scenario_hint = ""
        if isinstance(self._simulation_result, dict):
            scenario_hint = str(self._simulation_result.get("scenario") or "").strip()
        if not scenario_hint and hasattr(self.dock, "current_simulation_scenario_id"):
            scenario_hint = str(self.dock.current_simulation_scenario_id() or "").strip()
        if hasattr(self.dock, "set_simulation_result_mode"):
            self.dock.set_simulation_result_mode(scenario_hint or "coverage_analysis")
        target_state = self._simulation_target_point if isinstance(self._simulation_target_point, dict) else {}
        if hasattr(self.dock, "set_simulation_target_point") and target_state:
            self.dock.set_simulation_target_point(
                target_state.get("lat"),
                target_state.get("lon"),
                source=target_state.get("source"),
                label=target_state.get("label"),
            )
        if hasattr(self.dock, "set_simulation_controls_enabled"):
            self.dock.set_simulation_controls_enabled(not bool(self._simulation_running))
        if self._simulation_result:
            self._simulation_apply_result(self._simulation_result)
        else:
            self._simulation_clear_layers()

    def handle_simulation_config_changed(self, payload):
        request = payload if isinstance(payload, dict) else {}
        config = request.get("config")
        try:
            self.simulation_config_service.save_config(config)
            if self.dock is not None and hasattr(self.dock, "set_simulation_status"):
                self.dock.set_simulation_status("Simulation config saved.")
        except Exception as exc:
            if self.dock is not None and hasattr(self.dock, "set_simulation_status"):
                self.dock.set_simulation_status(f"Simulation config save failed: {exc}")
            if hasattr(self, "_append_search_log"):
                self._append_search_log(f"Simulation config save failed: {exc}", level=Qgis.Warning)

    def handle_simulation_start_request(self, payload):
        request = payload if isinstance(payload, dict) else {}
        if self._simulation_running or (
            self._simulation_thread is not None and self._simulation_thread.isRunning()
        ):
            if self.dock is not None and hasattr(self.dock, "set_simulation_status"):
                self.dock.set_simulation_status("Simulation is already running.")
            return

        try:
            scenario_id = str(request.get("scenario_id") or "coverage_analysis").strip().lower()
            config = self.simulation_config_service.save_config(request.get("constellation_config"))
            satellites = config.get("satellites") if isinstance(config.get("satellites"), list) else []
            if not satellites:
                raise RuntimeError("Simulation constellation is empty. Add at least one satellite with TLE.")
            worker_payload = {
                "scenario_id": scenario_id,
                "selection_mode": str(request.get("selection_mode") or "top_n").strip(),
                "satellite_count": int(float(request.get("satellite_count") or 1)),
                "selected_satellite_ids": request.get("selected_satellite_ids") if isinstance(request.get("selected_satellite_ids"), list) else [],
                "off_nadir_deg": float(request.get("off_nadir_deg") or 30.0),
                "start_utc": str(request.get("start_utc") or "").strip(),
                "end_utc": str(request.get("end_utc") or "").strip(),
                "time_step_sec": int(float(request.get("time_step_sec") or 60)),
                "satellites": satellites,
            }
            if not worker_payload["start_utc"] or not worker_payload["end_utc"]:
                raise RuntimeError("Simulation start and end UTC are required.")
            if scenario_id == "point_revisit_analysis":
                target = self._simulation_parse_target(request)
                self._simulation_target_point = dict(target)
                worker_payload["target"] = {
                    "lat": float(target["lat"]),
                    "lon": float(target["lon"]),
                    "source": str(target.get("source") or "manual").strip() or "manual",
                    "label": str(target.get("label") or "").strip(),
                }
                if self.dock is not None and hasattr(self.dock, "set_simulation_target_point"):
                    self.dock.set_simulation_target_point(
                        target["lat"],
                        target["lon"],
                        source=target.get("source"),
                        label=target.get("label"),
                    )
                if hasattr(self, "_append_search_log"):
                    self._append_search_log(
                        "[Simulation] point target prepared "
                        f"lat={float(target['lat']):.6f} lon={float(target['lon']):.6f} "
                        f"source={str(target.get('source') or 'manual').strip() or 'manual'}"
                    )
                worker_class = PointRevisitSimulationWorker
            else:
                raw_aoi_geojson = self._resolve_simulation_aoi_geojson(request)
                if hasattr(self, "_append_search_log"):
                    raw_type = str(raw_aoi_geojson.get("type") or "").strip() if isinstance(raw_aoi_geojson, dict) else ""
                    self._append_search_log(
                        "[Simulation] AOI raw payload "
                        f"source={str(request.get('aoi_source') or 'map_extent').strip()} "
                        f"payload_type={type(raw_aoi_geojson).__name__} "
                        f"geometry_type={raw_type or '-'}"
                    )
                aoi_geom_wgs84, aoi_geojson = self._simulation_normalize_aoi_geometry(raw_aoi_geojson)
                aoi_wkt = str(aoi_geom_wgs84.asWkt() or "").strip()
                if not aoi_wkt:
                    raise RuntimeError("AOI geometry WKT serialization failed.")
                worker_payload["aoi_source"] = str(request.get("aoi_source") or "map_extent").strip()
                worker_payload["aoi_layer_id"] = str(request.get("aoi_layer_id") or "").strip()
                worker_payload["aoi_geojson"] = aoi_geojson
                worker_payload["aoi_wkt"] = aoi_wkt
                if hasattr(self, "_append_search_log"):
                    geom_type = QgsWkbTypes.displayString(aoi_geom_wgs84.wkbType())
                    bbox = aoi_geom_wgs84.boundingBox()
                    self._append_search_log(
                        "[Simulation] AOI prepared "
                        f"source={worker_payload['aoi_source']} "
                        f"type={geom_type} "
                        f"bbox=({bbox.xMinimum():.6f}, {bbox.yMinimum():.6f}, {bbox.xMaximum():.6f}, {bbox.yMaximum():.6f})"
                    )
                worker_class = CoverageSimulationWorker
        except Exception as exc:
            if self.dock is not None and hasattr(self.dock, "set_simulation_status"):
                self.dock.set_simulation_status(f"Simulation validation failed: {exc}")
            self.iface.messageBar().pushMessage(
                "Image Mate",
                f"Simulation validation failed: {exc}",
                level=Qgis.Warning,
                duration=10,
            )
            return

        self._simulation_result = {}
        self._simulation_day_index = 0
        self._simulation_running = True
        self._simulation_clear_layers()
        if self.dock is not None:
            if hasattr(self.dock, "set_simulation_controls_enabled"):
                self.dock.set_simulation_controls_enabled(False)
            if hasattr(self.dock, "set_simulation_status"):
                self.dock.set_simulation_status("Simulation status: running...")
            if hasattr(self.dock, "set_simulation_progress"):
                self.dock.set_simulation_progress(0, 1, "Starting simulation...")
            if hasattr(self.dock, "set_simulation_result_mode"):
                self.dock.set_simulation_result_mode(worker_payload.get("scenario_id"))

        self._cleanup_simulation_worker()
        self._simulation_thread = QThread(self.iface.mainWindow())
        self._simulation_worker = worker_class(worker_payload)
        self._simulation_worker.moveToThread(self._simulation_thread)

        self._simulation_thread.started.connect(self._simulation_worker.run)
        self._simulation_worker.log.connect(self._on_simulation_worker_log)
        self._simulation_worker.progress.connect(self._on_simulation_worker_progress)
        self._simulation_worker.finished.connect(self._on_simulation_worker_finished)
        self._simulation_worker.failed.connect(self._on_simulation_worker_failed)
        self._simulation_worker.cancelled.connect(self._on_simulation_worker_cancelled)
        self._simulation_worker.finished.connect(self._simulation_thread.quit)
        self._simulation_worker.failed.connect(self._simulation_thread.quit)
        self._simulation_worker.cancelled.connect(self._simulation_thread.quit)
        self._simulation_thread.finished.connect(self._cleanup_simulation_worker)

        self._simulation_thread.start()

    @staticmethod
    def _simulation_parse_target(request):
        row = request if isinstance(request, dict) else {}
        try:
            lat = float(row.get("target_lat_deg"))
            lon = float(row.get("target_lon_deg"))
        except Exception as exc:
            raise RuntimeError("Point target lat/lon are required for point revisit scenario.") from exc
        if lat < -90.0 or lat > 90.0:
            raise RuntimeError("Point target latitude must be in [-90, 90].")
        if lon < -180.0 or lon > 180.0:
            raise RuntimeError("Point target longitude must be in [-180, 180].")
        return {
            "lat": float(lat),
            "lon": float(lon),
            "source": str(row.get("target_source") or "manual").strip() or "manual",
            "label": str(row.get("target_label") or "").strip(),
        }

    def _simulation_normalize_aoi_geometry(self, geometry_payload):
        geom = self._geometry_from_geojson(geometry_payload)
        if geom is None or geom.isEmpty():
            raise RuntimeError("AOI geometry could not be parsed from selected source.")

        if QgsWkbTypes.geometryType(geom.wkbType()) != QgsWkbTypes.PolygonGeometry:
            geom_label = QgsWkbTypes.displayString(geom.wkbType())
            raise RuntimeError(f"AOI must be polygonal, got '{geom_label}'.")

        if hasattr(geom, "isGeosValid") and not geom.isGeosValid():
            if hasattr(geom, "makeValid"):
                try:
                    candidate = geom.makeValid()
                    if candidate is not None and not candidate.isEmpty():
                        geom = candidate
                except Exception:
                    pass

        if geom is None or geom.isEmpty():
            raise RuntimeError("AOI geometry is empty after validation.")

        try:
            payload = json.loads(geom.asJson())
        except Exception as exc:
            raise RuntimeError(f"AOI geometry serialization failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("AOI geometry serialization returned invalid JSON payload.")
        return geom, payload

    def handle_simulation_cancel_request(self):
        if self._simulation_worker is not None:
            try:
                self._simulation_worker.cancel()
            except Exception:
                pass
        if self.dock is not None and hasattr(self.dock, "set_simulation_status"):
            self.dock.set_simulation_status("Simulation status: cancelling...")

    def handle_simulation_first_day_request(self):
        self._simulation_jump_to_day_boundary(start=True)

    def handle_simulation_prev_30_days_request(self):
        self._simulation_shift_day_index(-30)

    def handle_simulation_prev_day_request(self):
        self._simulation_shift_day_index(-1)

    def handle_simulation_next_day_request(self):
        self._simulation_shift_day_index(1)

    def handle_simulation_next_30_days_request(self):
        self._simulation_shift_day_index(30)

    def handle_simulation_last_day_request(self):
        self._simulation_jump_to_day_boundary(start=False)

    def _simulation_days_count(self):
        result = self._simulation_result if isinstance(self._simulation_result, dict) else {}
        days = result.get("days")
        days = days if isinstance(days, list) else []
        return len(days)

    def _simulation_shift_day_index(self, day_delta):
        total = self._simulation_days_count()
        if total <= 0:
            return
        target_index = shift_day_index(self._simulation_day_index, total, day_delta)
        self._simulation_apply_day(target_index)

    def _simulation_jump_to_day_boundary(self, *, start):
        total = self._simulation_days_count()
        if total <= 0:
            return
        if bool(start):
            target_index = start_day_index(total)
        else:
            target_index = end_day_index(total)
        self._simulation_apply_day(target_index)

    def _resolve_simulation_aoi_geojson(self, request):
        source = str(request.get("aoi_source") or "map_extent").strip().lower()
        if source == "polygon_layer":
            layer_id = str(request.get("aoi_layer_id") or "").strip()
            payload = self._simulation_polygon_layer_geometry_wgs84(layer_id)
        else:
            payload = self._current_extent_geometry_wgs84()
        if not isinstance(payload, dict):
            raise RuntimeError(f"AOI source '{source}' did not return a valid geometry object.")
        return payload

    def _simulation_polygon_layer_geometry_wgs84(self, layer_id):
        layer_key = str(layer_id or "").strip()
        if not layer_key:
            raise RuntimeError("Select a polygon layer for AOI source.")
        layer = QgsProject.instance().mapLayer(layer_key)
        if layer is None:
            raise RuntimeError(f"AOI polygon layer not found: {layer_key}")
        if not isinstance(layer, QgsVectorLayer):
            raise RuntimeError(f"AOI layer is not a vector layer: {layer_key}")
        if not layer.isValid():
            raise RuntimeError(f"AOI layer is invalid: {layer_key}")
        if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
            raise RuntimeError("AOI layer must be polygonal.")

        src_crs = layer.crs()
        dst_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = None
        if src_crs.isValid() and src_crs != dst_crs:
            transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())

        parts = []
        for feature in layer.getFeatures():
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            cloned = QgsGeometry(geom)
            if transform is not None:
                try:
                    cloned.transform(transform)
                except Exception:
                    continue
            if cloned.isEmpty():
                continue
            parts.append(cloned)
        if not parts:
            raise RuntimeError("AOI polygon layer has no usable geometries.")
        merged = QgsGeometry.unaryUnion(parts)
        if merged is None or merged.isEmpty():
            raise RuntimeError("AOI polygon layer union is empty.")
        try:
            payload = json.loads(merged.asJson())
        except Exception as exc:
            raise RuntimeError(f"Failed to serialize AOI geometry: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("AOI geometry serialization returned non-object.")
        return payload

    def _on_simulation_worker_log(self, message, level):
        text = str(message or "").strip()
        if not text:
            return
        if hasattr(self, "_append_search_log"):
            self._append_search_log(f"[Simulation] {text}", level=level)
        if hasattr(self, "_append_debug_log"):
            self._append_debug_log(f"[Simulation] {text}", level=level)

    def _on_simulation_worker_progress(self, current, total, status_text):
        if self.dock is not None and hasattr(self.dock, "set_simulation_progress"):
            self.dock.set_simulation_progress(int(current or 0), int(total or 0), status_text)

    def _on_simulation_worker_finished(self, result):
        self._simulation_running = False
        self._simulation_result = result if isinstance(result, dict) else {}
        self._simulation_day_index = 0
        scenario = str(self._simulation_result.get("scenario") or "coverage_analysis").strip()
        if self.dock is not None:
            if hasattr(self.dock, "set_simulation_controls_enabled"):
                self.dock.set_simulation_controls_enabled(True)
            if hasattr(self.dock, "set_simulation_status"):
                self.dock.set_simulation_status("Simulation status: completed.")
            if hasattr(self.dock, "set_simulation_result_mode"):
                self.dock.set_simulation_result_mode(scenario)
            if scenario == "point_revisit_analysis":
                if hasattr(self.dock, "set_simulation_revisit_summary"):
                    self.dock.set_simulation_revisit_summary(self._simulation_result)
                if hasattr(self.dock, "set_simulation_revisit_events"):
                    self.dock.set_simulation_revisit_events(self._simulation_result.get("events", []))
            else:
                if hasattr(self.dock, "set_simulation_summary"):
                    self.dock.set_simulation_summary(self._simulation_result)
            if hasattr(self.dock, "set_simulation_progress"):
                days_count = len(self._simulation_result.get("days", [])) if isinstance(self._simulation_result.get("days"), list) else 0
                self.dock.set_simulation_progress(days_count, max(days_count, 1), "Simulation completed.")
            if hasattr(self.dock, "show_simulation_results_tab"):
                self.dock.show_simulation_results_tab()
        self._simulation_apply_result(self._simulation_result)
        self.iface.messageBar().pushMessage(
            "Image Mate",
            "Simulation completed.",
            level=Qgis.Success,
            duration=8,
        )

    def _on_simulation_worker_failed(self, error_text, traceback_text):
        self._simulation_running = False
        if self.dock is not None:
            if hasattr(self.dock, "set_simulation_controls_enabled"):
                self.dock.set_simulation_controls_enabled(True)
            if hasattr(self.dock, "set_simulation_status"):
                self.dock.set_simulation_status(f"Simulation status: failed ({error_text})")
        if hasattr(self, "_append_search_log"):
            self._append_search_log(f"[Simulation] failed: {error_text}", level=Qgis.Warning)
        if traceback_text and hasattr(self, "_append_debug_log"):
            self._append_debug_log(f"[Simulation] {traceback_text}", level=Qgis.Warning)
        self.iface.messageBar().pushMessage(
            "Image Mate",
            f"Simulation failed: {error_text}",
            level=Qgis.Warning,
            duration=12,
        )

    def _on_simulation_worker_cancelled(self):
        self._simulation_running = False
        if self.dock is not None:
            if hasattr(self.dock, "set_simulation_controls_enabled"):
                self.dock.set_simulation_controls_enabled(True)
            if hasattr(self.dock, "set_simulation_status"):
                self.dock.set_simulation_status("Simulation status: cancelled.")
            if hasattr(self.dock, "set_simulation_progress"):
                self.dock.set_simulation_progress(0, 1, "Cancelled.")

    def _simulation_apply_result(self, result):
        row = result if isinstance(result, dict) else {}
        scenario = str(row.get("scenario") or "coverage_analysis").strip()
        if self.dock is not None and hasattr(self.dock, "set_simulation_result_mode"):
            self.dock.set_simulation_result_mode(scenario)
        if scenario == "point_revisit_analysis":
            self._simulation_apply_revisit_result(row)
            return
        if self.dock is not None and hasattr(self.dock, "set_simulation_summary"):
            self.dock.set_simulation_summary(row)
        self._simulation_apply_day(self._simulation_day_index)

    def _simulation_apply_day(self, index):
        result = self._simulation_result if isinstance(self._simulation_result, dict) else {}
        days = result.get("days")
        days = days if isinstance(days, list) else []
        if not days:
            if self.dock is not None and hasattr(self.dock, "set_simulation_day"):
                self.dock.set_simulation_day({})
            self._simulation_clear_layers()
            return
        bounded = clamp_day_index(index, len(days))
        self._simulation_day_index = bounded
        day_row = days[bounded] if isinstance(days[bounded], dict) else {}
        payload = dict(day_row)
        payload["index"] = bounded
        payload["total_days"] = len(days)
        if self.dock is not None and hasattr(self.dock, "set_simulation_day"):
            self.dock.set_simulation_day(payload)
        self._simulation_render_day_layers(day_row)

    def _simulation_apply_revisit_result(self, result):
        row = result if isinstance(result, dict) else {}
        if self.dock is not None:
            if hasattr(self.dock, "set_simulation_revisit_summary"):
                self.dock.set_simulation_revisit_summary(row)
            if hasattr(self.dock, "set_simulation_revisit_events"):
                self.dock.set_simulation_revisit_events(
                    row.get("events") if isinstance(row.get("events"), list) else []
                )
            if hasattr(self.dock, "set_simulation_day"):
                self.dock.set_simulation_day({})

        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        self._simulation_render_revisit_target_layer(target)

    def _simulation_render_day_layers(self, day_row):
        row = day_row if isinstance(day_row, dict) else {}
        day_geojson = row.get("day_geometry_geojson")
        cumulative_geojson = row.get("cumulative_unique_geojson")

        self._remove_layer_by_id(self._simulation_day_layer_id)
        self._remove_layer_by_id(self._simulation_unique_layer_id)
        self._simulation_day_layer_id = None
        self._simulation_unique_layer_id = None

        unique_layer = self._simulation_layer_from_geojson(
            geometry_payload=cumulative_geojson,
            layer_name="Image Mate Simulation - Cumulative Unique",
            fill_color="90, 180, 110, 70",
            outline_color="40, 120, 50, 200",
        )
        if unique_layer is not None:
            self._add_layer_to_image_mate_group(unique_layer, insert_on_top=False)
            self._simulation_unique_layer_id = unique_layer.id()

        day_layer = self._simulation_layer_from_geojson(
            geometry_payload=day_geojson,
            layer_name="Image Mate Simulation - Day Imaged",
            fill_color="255, 170, 60, 80",
            outline_color="200, 110, 20, 200",
        )
        if day_layer is not None:
            self._add_layer_to_image_mate_group(day_layer, insert_on_top=True)
            self._simulation_day_layer_id = day_layer.id()

    def _simulation_layer_from_geojson(self, *, geometry_payload, layer_name, fill_color, outline_color):
        geom = self._geometry_from_geojson(geometry_payload)
        if geom is None or geom.isEmpty():
            return None
        layer = QgsVectorLayer("MultiPolygon?crs=EPSG:4326", str(layer_name or "Simulation Layer"), "memory")
        if not layer.isValid():
            return None
        provider = layer.dataProvider()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(geom)
        add_result = provider.addFeatures([feature])
        add_ok = bool(add_result[0]) if isinstance(add_result, tuple) else bool(add_result)
        if not add_ok:
            return None
        layer.updateExtents()
        symbol = QgsFillSymbol.createSimple(
            {
                "color": str(fill_color or "255,0,0,60"),
                "outline_color": str(outline_color or "255,0,0,180"),
                "outline_width": "0.8",
            }
        )
        if symbol is not None:
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        return layer

    def _simulation_render_revisit_target_layer(self, target):
        row = target if isinstance(target, dict) else {}
        try:
            lat = float(row.get("lat"))
            lon = float(row.get("lon"))
        except Exception:
            self._remove_layer_by_id(self._simulation_revisit_target_layer_id)
            self._simulation_revisit_target_layer_id = None
            return
        if lat < -90.0 or lat > 90.0 or lon < -180.0 or lon > 180.0:
            self._remove_layer_by_id(self._simulation_revisit_target_layer_id)
            self._simulation_revisit_target_layer_id = None
            return

        self._remove_layer_by_id(self._simulation_revisit_target_layer_id)
        self._simulation_revisit_target_layer_id = None

        layer = QgsVectorLayer("Point?crs=EPSG:4326", "Image Mate Simulation - Revisit Target", "memory")
        if not layer.isValid():
            return
        provider = layer.dataProvider()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(float(lon), float(lat))))
        add_result = provider.addFeatures([feature])
        add_ok = bool(add_result[0]) if isinstance(add_result, tuple) else bool(add_result)
        if not add_ok:
            return
        layer.updateExtents()
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "cross_fill",
                "color": "230, 30, 30, 230",
                "size": "4.0",
                "outline_color": "255,255,255,220",
                "outline_width": "0.5",
            }
        )
        if symbol is not None:
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        self._add_layer_to_image_mate_group(layer, insert_on_top=True)
        self._simulation_revisit_target_layer_id = layer.id()

    def _simulation_clear_layers(self):
        self._remove_layer_by_id(self._simulation_day_layer_id)
        self._remove_layer_by_id(self._simulation_unique_layer_id)
        self._remove_layer_by_id(self._simulation_revisit_target_layer_id)
        self._simulation_day_layer_id = None
        self._simulation_unique_layer_id = None
        self._simulation_revisit_target_layer_id = None

    def _cleanup_simulation_worker(self):
        if self._simulation_worker is not None:
            try:
                self._simulation_worker.deleteLater()
            except Exception:
                pass
            self._simulation_worker = None
        if self._simulation_thread is not None:
            if self._simulation_thread.isRunning():
                return
            try:
                self._simulation_thread.deleteLater()
            except Exception:
                pass
            self._simulation_thread = None

    def _stop_simulation_execution(self, timeout_ms=0):
        if self._simulation_worker is not None:
            try:
                self._simulation_worker.cancel()
            except Exception:
                pass
        thread = self._simulation_thread
        if thread is not None and thread.isRunning():
            try:
                thread.quit()
                wait_ms = max(0, int(timeout_ms or 0))
                if wait_ms > 0:
                    thread.wait(wait_ms)
            except Exception:
                pass
        self._simulation_running = False
        self._cleanup_simulation_worker()
        self._simulation_clear_layers()
