# -*- coding: utf-8 -*-
"""Coverage simulation worker using Skyfield TLE propagation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import traceback

from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import Qgis
from qgis.core import QgsCoordinateReferenceSystem
from qgis.core import QgsCoordinateTransform
from qgis.core import QgsGeometry
from qgis.core import QgsPointXY
from qgis.core import QgsProject
from qgis.core import QgsWkbTypes

from ..services.simulation_progress_planner import coverage_progress_plan


class _SimulationCancelled(RuntimeError):
    """Internal cancellation marker."""


class CoverageSimulationWorker(QObject):
    """Run coverage analysis in background thread."""

    log = pyqtSignal(str, int)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(dict)
    failed = pyqtSignal(str, str)
    cancelled = pyqtSignal()

    def __init__(self, payload: dict):
        super().__init__()
        self.payload = dict(payload or {})
        self._cancel_requested = False

    def cancel(self):
        self._cancel_requested = True

    def run(self):
        try:
            result = self._execute()
            if self._cancel_requested:
                self.cancelled.emit()
                return
            self.finished.emit(result)
        except _SimulationCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())

    def _execute(self) -> dict:
        skyfield_api = self._import_skyfield()
        EarthSatellite = skyfield_api["EarthSatellite"]
        load = skyfield_api["load"]
        wgs84 = skyfield_api["wgs84"]

        scenario = str(self.payload.get("scenario_id") or "coverage_analysis").strip() or "coverage_analysis"
        if scenario != "coverage_analysis":
            raise RuntimeError(f"Unsupported simulation scenario '{scenario}'.")

        start_utc = self._parse_utc(self.payload.get("start_utc"))
        end_utc = self._parse_utc(self.payload.get("end_utc"))
        if start_utc >= end_utc:
            raise RuntimeError("Simulation start_utc must be before end_utc.")

        try:
            time_step_sec = int(float(self.payload.get("time_step_sec", 60)))
        except Exception:
            time_step_sec = 60
        time_step_sec = max(1, time_step_sec)

        try:
            off_nadir_deg = float(self.payload.get("off_nadir_deg", 30.0))
        except Exception:
            off_nadir_deg = 30.0
        if off_nadir_deg <= 0.0 or off_nadir_deg > 60.0:
            raise RuntimeError("Simulation off_nadir_deg must be in (0, 60].")
        off_nadir_rad = math.radians(off_nadir_deg)
        swath_width_override_m = self._resolve_swath_width_override_m(self.payload.get("swath_width_m"))

        all_satellites = self.payload.get("satellites")
        all_satellites = all_satellites if isinstance(all_satellites, list) else []
        selected_satellites = self._select_satellites(
            satellites=all_satellites,
            selection_mode=str(self.payload.get("selection_mode") or "top_n").strip().lower(),
            satellite_count=self.payload.get("satellite_count"),
            selected_satellite_ids=self.payload.get("selected_satellite_ids"),
        )
        if not selected_satellites:
            raise RuntimeError("No satellites selected for simulation.")

        sample_count = int((end_utc - start_utc).total_seconds() // time_step_sec) + 1
        if sample_count <= 1:
            raise RuntimeError("Simulation duration must include at least two timesteps.")
        if len(selected_satellites) * sample_count > 3_000_000:
            raise RuntimeError(
                "Simulation request is too dense (satellite_count * sample_count > 3,000,000). "
                "Increase timestep or shorten duration."
            )

        aoi_geojson = self.payload.get("aoi_geojson")
        aoi_wkt = str(self.payload.get("aoi_wkt") or "").strip()
        geojson_payload_type = type(aoi_geojson).__name__
        geojson_geom_type = ""
        if isinstance(aoi_geojson, dict):
            geojson_geom_type = str(aoi_geojson.get("type") or "").strip()
        self._emit_log(
            "AOI payload received: "
            f"geojson_payload_type={geojson_payload_type} "
            f"geojson_geom_type={geojson_geom_type or '-'} "
            f"wkt_len={len(aoi_wkt)}",
            Qgis.Info,
        )

        aoi_wgs84, aoi_parse_source = self._resolve_aoi_geometry(
            aoi_geojson=aoi_geojson,
            aoi_wkt=aoi_wkt,
        )
        if aoi_wgs84 is None or aoi_wgs84.isEmpty():
            raise RuntimeError(
                "Simulation AOI geometry is missing or invalid "
                f"(geojson_payload_type={geojson_payload_type}, "
                f"geojson_geom_type={geojson_geom_type or '-'}, "
                f"wkt_len={len(aoi_wkt)})."
            )
        if QgsWkbTypes.geometryType(aoi_wgs84.wkbType()) != QgsWkbTypes.PolygonGeometry:
            got_type = QgsWkbTypes.displayString(aoi_wgs84.wkbType())
            raise RuntimeError(f"Simulation AOI geometry must be polygonal, got '{got_type}'.")
        self._emit_log(
            f"AOI geometry parsed via {aoi_parse_source}: {QgsWkbTypes.displayString(aoi_wgs84.wkbType())}.",
            Qgis.Info,
        )

        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_equal_area = QgsCoordinateReferenceSystem("EPSG:6933")
        to_equal = QgsCoordinateTransform(crs_wgs84, crs_equal_area, QgsProject.instance())
        to_wgs84 = QgsCoordinateTransform(crs_equal_area, crs_wgs84, QgsProject.instance())

        aoi_equal = QgsGeometry(aoi_wgs84)
        aoi_equal.transform(to_equal)
        if aoi_equal.isEmpty():
            raise RuntimeError("Simulation AOI geometry became empty after projection.")

        aoi_area_km2 = max(0.0, float(aoi_equal.area()) / 1_000_000.0)
        if aoi_area_km2 <= 0.0:
            raise RuntimeError("Simulation AOI area is zero after projection.")
        self._emit_log(f"AOI area after projection: {aoi_area_km2:.3f} km2.", Qgis.Info)
        self._emit_log(
            "Applying daylight filter: sample must be on sunlit side (approx sun elevation > 0 deg).",
            Qgis.Info,
        )
        if swath_width_override_m is not None:
            self._emit_log(
                f"Collection model: steered strip swath with fixed width {swath_width_override_m / 1000.0:.2f} km.",
                Qgis.Info,
            )
        else:
            self._emit_log(
                "Collection model: steered strip swath with heuristic width "
                "clamp(0.08 * mean_reach, 5km, 40km).",
                Qgis.Info,
            )

        sample_times = [start_utc + timedelta(seconds=time_step_sec * idx) for idx in range(sample_count)]
        ts = load.timescale()
        sf_times = ts.from_datetimes(sample_times)
        pass_gap_sec = 2 * int(time_step_sec)

        total_area_imaged_km2 = 0.0
        total_collection_passes = 0
        unique_geom_equal = None
        daily = {}

        total_satellites = len(selected_satellites)
        total_days_span = max(1, (end_utc.date() - start_utc.date()).days + 1)
        progress_plan = coverage_progress_plan(
            total_satellites=total_satellites,
            total_days=total_days_span,
        )
        satellite_progress_units = int(progress_plan.get("satellite_units", 1000) or 1000)
        finalization_units = int(progress_plan.get("finalization_units", 120) or 120)
        total_progress_units = int(progress_plan.get("total_units", 1) or 1)
        finalization_base = total_satellites * satellite_progress_units
        self._emit_progress(0, total_progress_units, "Preparing simulation...")
        for sat_idx, sat_row in enumerate(selected_satellites, start=1):
            self._check_cancelled()
            sat_name = str(
                sat_row.get("name")
                or sat_row.get("satellite_id")
                or sat_row.get("id")
                or "satellite"
            ).strip() or "satellite"
            tle = sat_row.get("tle") if isinstance(sat_row.get("tle"), dict) else {}
            line1 = str(tle.get("line1") or sat_row.get("tle_line1") or "").strip()
            line2 = str(tle.get("line2") or sat_row.get("tle_line2") or "").strip()
            if not line1 or not line2:
                self._emit_log(f"Skipping {sat_name}: missing TLE line1/line2.", Qgis.Warning)
                continue

            sat_base = (sat_idx - 1) * satellite_progress_units
            sat_upper = sat_base + satellite_progress_units
            last_sat_progress = sat_base

            def _emit_satellite_progress(phase_ratio: float, text: str):
                nonlocal last_sat_progress
                safe_ratio = max(0.0, min(1.0, float(phase_ratio)))
                current = sat_base + int(round(safe_ratio * satellite_progress_units))
                current = max(last_sat_progress, min(current, sat_upper))
                last_sat_progress = current
                self._emit_progress(current, total_progress_units, text)

            self._emit_progress(
                sat_base,
                total_progress_units,
                f"Simulating {sat_name} ({sat_idx}/{total_satellites})...",
            )
            satellite = EarthSatellite(line1, line2, sat_name, ts=ts)
            geocentric = satellite.at(sf_times)
            lat_obj, lon_obj = wgs84.latlon_of(geocentric)
            height_obj = wgs84.height_of(geocentric)

            latitudes = lat_obj.degrees
            longitudes = lon_obj.degrees
            heights_km = height_obj.km

            sat_swath_width_override_m = self._resolve_satellite_swath_width_m(
                sat_row,
                fallback_swath_width_m=swath_width_override_m,
            )
            if sat_swath_width_override_m is not None:
                self._emit_log(
                    f"{sat_name}: using configured swath width {sat_swath_width_override_m / 1000.0:.2f} km.",
                    Qgis.Info,
                )
            else:
                self._emit_log(
                    f"{sat_name}: swath width not configured; using heuristic width estimate.",
                    Qgis.Warning,
                )

            sample_rows = []
            dark_filtered_samples = 0
            progress_stride = max(1, sample_count // 300)
            for sample_idx in range(sample_count):
                self._check_cancelled()
                if (sample_idx % progress_stride) == 0 or sample_idx == (sample_count - 1):
                    sample_ratio = float(sample_idx + 1) / float(sample_count)
                    _emit_satellite_progress(
                        0.05 + (0.75 * sample_ratio),
                        f"Simulating {sat_name}: sample {sample_idx + 1}/{sample_count}",
                    )

                try:
                    lon = float(longitudes[sample_idx])
                    lat = float(latitudes[sample_idx])
                    height_km = float(heights_km[sample_idx])
                except Exception:
                    continue
                if not self._is_daylight_approx(sample_times[sample_idx], lat, lon):
                    dark_filtered_samples += 1
                    continue

                reach_m = max(0.0, float(height_km) * math.tan(off_nadir_rad) * 1000.0)
                if reach_m <= 0.0:
                    continue

                try:
                    point_equal = to_equal.transform(QgsPointXY(lon, lat))
                except Exception:
                    continue
                reach_geom = QgsGeometry.fromPointXY(point_equal).buffer(reach_m, 16)
                if reach_geom is None or reach_geom.isEmpty():
                    continue
                has_access = bool(reach_geom.intersects(aoi_equal))
                sample_rows.append(
                    {
                        "time": sample_times[sample_idx],
                        "point": point_equal,
                        "reach_m": float(reach_m),
                        "access": has_access,
                    }
                )

            pass_rows = self._build_passes(sample_rows, pass_gap_sec=pass_gap_sec)
            _emit_satellite_progress(
                0.82,
                f"Simulating {sat_name}: grouping {len(pass_rows)} pass window(s)...",
            )
            self._emit_log(
                f"{sat_name}: {len(pass_rows)} candidate pass window(s) over AOI.",
                Qgis.Info,
            )
            sat_passes = 0
            sat_total_km2 = 0.0
            sat_unique_km2 = 0.0
            sat_abs_offset_m = 0.0
            sat_swath_width_m = 0.0
            pass_count = max(1, len(pass_rows))
            pass_progress_stride = max(1, pass_count // 100)
            for pass_idx, pass_row in enumerate(pass_rows, start=1):
                self._check_cancelled()
                selected = self._select_pass_collection_geometry(
                    pass_row=pass_row,
                    aoi_equal=aoi_equal,
                    unique_geom_equal=unique_geom_equal,
                    swath_width_override_m=sat_swath_width_override_m,
                )
                if not isinstance(selected, dict):
                    continue

                pass_footprint = selected.get("footprint")
                if not isinstance(pass_footprint, QgsGeometry) or pass_footprint.isEmpty():
                    continue
                if not pass_footprint.intersects(aoi_equal):
                    continue

                pass_imaged = selected.get("imaged")
                if not isinstance(pass_imaged, QgsGeometry):
                    pass_imaged = pass_footprint.intersection(aoi_equal)
                if pass_imaged is None or pass_imaged.isEmpty():
                    continue

                pass_area_km2 = float(selected.get("imaged_area_km2", 0.0) or 0.0)
                if pass_area_km2 <= 0.0:
                    pass_area_km2 = max(0.0, float(pass_imaged.area()) / 1_000_000.0)
                total_area_imaged_km2 += pass_area_km2
                total_collection_passes += 1
                sat_passes += 1
                sat_total_km2 += pass_area_km2
                sat_unique_km2 += float(selected.get("unique_gain_km2", 0.0) or 0.0)
                sat_abs_offset_m += abs(float(selected.get("offset_m", 0.0) or 0.0))
                sat_swath_width_m = float(selected.get("swath_width_m", sat_swath_width_m) or sat_swath_width_m)

                if unique_geom_equal is None:
                    unique_geom_equal = QgsGeometry(pass_imaged)
                else:
                    unique_geom_equal = self._unary_union([unique_geom_equal, pass_imaged])

                pass_start = pass_row.get("start")
                if not isinstance(pass_start, datetime):
                    continue
                day_key = pass_start.date().isoformat()
                day_row = daily.get(day_key)
                if not isinstance(day_row, dict):
                    day_row = {
                        "day_area_km2": 0.0,
                        "collection_passes": 0,
                        "geoms": [],
                    }
                    daily[day_key] = day_row
                day_row["day_area_km2"] = float(day_row.get("day_area_km2", 0.0)) + pass_area_km2
                day_row["collection_passes"] = int(day_row.get("collection_passes", 0)) + 1
                day_geoms = day_row.get("geoms")
                if not isinstance(day_geoms, list):
                    day_geoms = []
                    day_row["geoms"] = day_geoms
                day_geoms.append(pass_imaged)
                if (pass_idx % pass_progress_stride) == 0 or pass_idx == pass_count:
                    pass_ratio = float(pass_idx) / float(pass_count)
                    _emit_satellite_progress(
                        0.83 + (0.16 * pass_ratio),
                        f"Simulating {sat_name}: pass {pass_idx}/{pass_count}",
                    )

            _emit_satellite_progress(1.0, f"Completed {sat_name} ({sat_idx}/{total_satellites}).")
            self._emit_log(
                f"{sat_name}: collection_passes={sat_passes}, "
                f"area_imaged={sat_total_km2:.2f} km2, "
                f"unique_gain={sat_unique_km2:.2f} km2, "
                f"night_filtered={dark_filtered_samples}, "
                f"avg_abs_steer={((sat_abs_offset_m / sat_passes) / 1000.0) if sat_passes else 0.0:.2f} km, "
                f"swath_width={sat_swath_width_m / 1000.0:.2f} km.",
                Qgis.Info,
            )

        self._emit_progress(
            finalization_base,
            total_progress_units,
            "Finalizing daily coverage metrics...",
        )

        self._check_cancelled()

        days = []
        cursor = start_utc.date()
        end_date = end_utc.date()
        cumulative_imaged_km2 = 0.0
        cumulative_unique_equal = None
        day_progress_stride = max(1, total_days_span // 240)

        while cursor <= end_date:
            self._check_cancelled()
            day_key = cursor.isoformat()
            row = daily.get(day_key) if isinstance(daily.get(day_key), dict) else {}
            day_area_km2 = float(row.get("day_area_km2", 0.0) or 0.0)
            day_passes = int(row.get("collection_passes", 0) or 0)
            day_geoms = row.get("geoms") if isinstance(row, dict) else []
            day_geoms = day_geoms if isinstance(day_geoms, list) else []
            day_union_equal = self._unary_union(day_geoms)

            cumulative_imaged_km2 += day_area_km2
            if day_union_equal is not None and not day_union_equal.isEmpty():
                if cumulative_unique_equal is None:
                    cumulative_unique_equal = QgsGeometry(day_union_equal)
                else:
                    cumulative_unique_equal = self._unary_union([cumulative_unique_equal, day_union_equal])

            cumulative_unique_km2 = (
                max(0.0, float(cumulative_unique_equal.area()) / 1_000_000.0)
                if cumulative_unique_equal is not None and not cumulative_unique_equal.isEmpty()
                else 0.0
            )

            days.append(
                {
                    "date": day_key,
                    "day_imaged_km2": day_area_km2,
                    "cumulative_imaged_km2": cumulative_imaged_km2,
                    "cumulative_unique_km2": cumulative_unique_km2,
                    "collection_passes": day_passes,
                    "day_geometry_geojson": self._geometry_to_geojson(day_union_equal, transform=to_wgs84),
                    "cumulative_unique_geojson": self._geometry_to_geojson(cumulative_unique_equal, transform=to_wgs84),
                }
            )
            processed_days = len(days)
            if (processed_days % day_progress_stride) == 0 or processed_days == total_days_span:
                day_ratio = float(processed_days) / float(total_days_span)
                current_progress = finalization_base + int(round(day_ratio * finalization_units))
                self._emit_progress(
                    current_progress,
                    total_progress_units,
                    f"Finalizing daily coverage metrics: day {processed_days}/{total_days_span}",
                )

            cursor = cursor + timedelta(days=1)

        total_unique_area_km2 = (
            max(0.0, float(unique_geom_equal.area()) / 1_000_000.0)
            if unique_geom_equal is not None and not unique_geom_equal.isEmpty()
            else 0.0
        )
        coverage_pct = 0.0
        if aoi_area_km2 > 0.0:
            coverage_pct = max(0.0, min(100.0, (total_unique_area_km2 / aoi_area_km2) * 100.0))
        self._emit_progress(total_progress_units, total_progress_units, "Simulation completed.")
        return {
            "scenario": "coverage_analysis",
            "start_utc": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_utc": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "satellite_count": len(selected_satellites),
            "aoi_area_km2": aoi_area_km2,
            "total_unique_area_km2": total_unique_area_km2,
            "aoi_coverage_percent": coverage_pct,
            "total_area_imaged_km2": total_area_imaged_km2,
            "total_collection_passes": int(total_collection_passes),
            "days": days,
        }

    @staticmethod
    def _import_skyfield() -> dict:
        try:
            from skyfield.api import EarthSatellite
            from skyfield.api import load
            from skyfield.api import wgs84
        except Exception as exc:
            raise RuntimeError(
                "Skyfield is required for Simulation tab coverage analysis. "
                "Install skyfield==1.54 in your QGIS Python environment."
            ) from exc
        return {
            "EarthSatellite": EarthSatellite,
            "load": load,
            "wgs84": wgs84,
        }

    @staticmethod
    def _parse_utc(value) -> datetime:
        text = str(value or "").strip()
        if not text:
            raise RuntimeError("Simulation datetime is required.")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except Exception as exc:
            raise RuntimeError(f"Invalid simulation datetime '{value}'.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _local_solar_hour_approx(sample_time_utc: datetime, lon_deg: float) -> float:
        dt = sample_time_utc.astimezone(timezone.utc)
        utc_hours = (
            float(dt.hour)
            + float(dt.minute) / 60.0
            + float(dt.second) / 3600.0
            + float(dt.microsecond) / 3_600_000_000.0
        )
        solar_hour = utc_hours + (float(lon_deg) / 15.0)
        return solar_hour % 24.0

    @classmethod
    def _is_daylight_approx(cls, sample_time_utc: datetime, lat_deg: float, lon_deg: float) -> bool:
        # Fast approximation: sun above horizon from local solar geometry.
        try:
            dt = sample_time_utc.astimezone(timezone.utc)
            lat_rad = math.radians(float(lat_deg))
            day_of_year = int(dt.timetuple().tm_yday)
            decl_deg = 23.44 * math.sin((2.0 * math.pi / 365.0) * (day_of_year - 81))
            decl_rad = math.radians(decl_deg)
            solar_hour = cls._local_solar_hour_approx(dt, float(lon_deg))
            hour_angle_rad = math.radians((solar_hour - 12.0) * 15.0)
            sin_elev = (
                (math.sin(lat_rad) * math.sin(decl_rad))
                + (math.cos(lat_rad) * math.cos(decl_rad) * math.cos(hour_angle_rad))
            )
        except Exception:
            return True
        return sin_elev > 0.0

    @classmethod
    def _select_satellites(
        cls,
        *,
        satellites,
        selection_mode,
        satellite_count,
        selected_satellite_ids,
    ) -> list[dict]:
        rows = [row for row in (satellites or []) if isinstance(row, dict)]
        enabled_rows = [row for row in rows if bool(row.get("enabled", True))]
        if not enabled_rows:
            raise RuntimeError("Simulation constellation has no enabled satellites.")

        mode = str(selection_mode or "top_n").strip().lower()
        if mode == "manual":
            selected_ids = {
                str(value or "").strip()
                for value in (selected_satellite_ids or [])
                if str(value or "").strip()
            }
            out = []
            for row in enabled_rows:
                sat_id = str(row.get("satellite_id") or row.get("id") or "").strip()
                if sat_id and sat_id in selected_ids:
                    out.append(row)
            if not out:
                raise RuntimeError("Manual simulation selection is empty.")
            return out

        try:
            top_n = int(float(satellite_count or 1))
        except Exception:
            top_n = 1
        top_n = max(1, min(top_n, len(enabled_rows)))
        def _priority_value(row):
            try:
                return int(float(row.get("priority", 100)))
            except Exception:
                return 100
        enabled_rows.sort(
            key=lambda row: (
                _priority_value(row),
                str(row.get("satellite_id") or row.get("id") or "").strip(),
            )
        )
        return enabled_rows[:top_n]

    @staticmethod
    def _resolve_aoi_geometry(*, aoi_geojson, aoi_wkt):
        wkt_text = str(aoi_wkt or "").strip()
        if wkt_text:
            try:
                parsed = QgsGeometry.fromWkt(wkt_text)
            except Exception:
                parsed = None
            if parsed is not None and not parsed.isEmpty():
                return parsed, "wkt"

        parsed = CoverageSimulationWorker._geometry_from_geojson(aoi_geojson)
        if parsed is not None and not parsed.isEmpty():
            return parsed, "geojson"
        return None, "none"

    @staticmethod
    def _geometry_from_geojson(geometry_payload):
        payload = geometry_payload
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = None
        if not isinstance(payload, dict):
            return None
        if str(payload.get("type") or "").strip() == "Feature" and isinstance(payload.get("geometry"), dict):
            payload = payload.get("geometry")
        if not isinstance(payload, dict):
            return None
        if str(payload.get("type") or "").strip() == "FeatureCollection":
            features = payload.get("features")
            features = features if isinstance(features, list) else []
            geoms = []
            for feature in features:
                candidate = feature if isinstance(feature, dict) else {}
                geom_payload = candidate.get("geometry") if isinstance(candidate.get("geometry"), dict) else None
                parsed = CoverageSimulationWorker._geometry_from_geojson(geom_payload)
                if parsed is not None and not parsed.isEmpty():
                    geoms.append(parsed)
            return CoverageSimulationWorker._unary_union(geoms)

        try:
            if hasattr(QgsGeometry, "fromGeoJson"):
                parsed = QgsGeometry.fromGeoJson(json.dumps(payload))
                if parsed is not None and not parsed.isEmpty():
                    return parsed
        except Exception:
            pass

        geom_type = str(payload.get("type") or "").strip()
        coords = payload.get("coordinates")

        def pt(pair):
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                return None
            try:
                return QgsPointXY(float(pair[0]), float(pair[1]))
            except Exception:
                return None

        try:
            if geom_type == "Point":
                p = pt(coords)
                return QgsGeometry.fromPointXY(p) if p is not None else None
            if geom_type == "MultiPoint" and isinstance(coords, list):
                pts = [p for p in (pt(row) for row in coords) if p is not None]
                return QgsGeometry.fromMultiPointXY(pts) if pts else None
            if geom_type == "LineString" and isinstance(coords, list):
                line = [p for p in (pt(row) for row in coords) if p is not None]
                return QgsGeometry.fromPolylineXY(line) if len(line) >= 2 else None
            if geom_type == "MultiLineString" and isinstance(coords, list):
                lines = []
                for row in coords:
                    if not isinstance(row, list):
                        continue
                    line = [p for p in (pt(pair) for pair in row) if p is not None]
                    if len(line) >= 2:
                        lines.append(line)
                return QgsGeometry.fromMultiPolylineXY(lines) if lines else None
            if geom_type == "Polygon" and isinstance(coords, list):
                rings = []
                for ring in coords:
                    if not isinstance(ring, list):
                        continue
                    pts = [p for p in (pt(pair) for pair in ring) if p is not None]
                    if len(pts) >= 3:
                        rings.append(pts)
                return QgsGeometry.fromPolygonXY(rings) if rings else None
            if geom_type == "MultiPolygon" and isinstance(coords, list):
                polys = []
                for poly in coords:
                    if not isinstance(poly, list):
                        continue
                    rings = []
                    for ring in poly:
                        if not isinstance(ring, list):
                            continue
                        pts = [p for p in (pt(pair) for pair in ring) if p is not None]
                        if len(pts) >= 3:
                            rings.append(pts)
                    if rings:
                        polys.append(rings)
                return QgsGeometry.fromMultiPolygonXY(polys) if polys else None
        except Exception:
            return None
        return None

    @staticmethod
    def _geometry_to_geojson(geometry, *, transform=None):
        if geometry is None or not isinstance(geometry, QgsGeometry) or geometry.isEmpty():
            return None
        geom = QgsGeometry(geometry)
        if transform is not None:
            try:
                geom.transform(transform)
            except Exception:
                return None
        if geom.isEmpty():
            return None
        try:
            payload = json.loads(geom.asJson())
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _resolve_swath_width_override_m(value):
        if value is None:
            return None
        try:
            width_m = float(value)
        except Exception:
            return None
        if width_m <= 0.0:
            return None
        return width_m

    @classmethod
    def _resolve_satellite_swath_width_m(cls, sat_row, *, fallback_swath_width_m=None):
        row = sat_row if isinstance(sat_row, dict) else {}
        width_km = row.get("swath_width_km")
        if width_km is None:
            width_km = row.get("swath_km")
        if width_km is not None:
            try:
                width_km_val = float(width_km)
            except Exception:
                width_km_val = 0.0
            if width_km_val > 0.0:
                return width_km_val * 1000.0

        width_m = cls._resolve_swath_width_override_m(row.get("swath_width_m"))
        if width_m is not None:
            return width_m
        return cls._resolve_swath_width_override_m(fallback_swath_width_m)

    @staticmethod
    def _estimate_swath_width_m(*, mean_reach_m, swath_width_override_m):
        if swath_width_override_m is not None and swath_width_override_m > 0.0:
            return float(swath_width_override_m)
        # Conservative default to avoid over-estimation from access corridor.
        # Reach is "how far we can steer", not native sensor swath width.
        return max(5_000.0, min(40_000.0, float(mean_reach_m or 0.0) * 0.08))

    @classmethod
    def _build_passes(cls, sample_rows, *, pass_gap_sec):
        samples = []
        for row in sample_rows or []:
            sample = row if isinstance(row, dict) else {}
            sample_time = sample.get("time")
            point = sample.get("point")
            if not isinstance(sample_time, datetime) or not isinstance(point, QgsPointXY):
                continue
            try:
                reach_m = float(sample.get("reach_m", 0.0) or 0.0)
            except Exception:
                reach_m = 0.0
            if reach_m <= 0.0:
                continue
            samples.append(
                {
                    "time": sample_time,
                    "point": point,
                    "reach_m": reach_m,
                    "access": bool(sample.get("access", False)),
                }
            )
        if not samples:
            return []

        samples.sort(key=lambda row: row["time"])
        access_indices = [idx for idx, row in enumerate(samples) if bool(row.get("access", False))]
        if not access_indices:
            return []

        grouped_access_ranges = []
        first_idx = access_indices[0]
        prev_idx = access_indices[0]
        for idx in access_indices[1:]:
            gap = (samples[idx]["time"] - samples[prev_idx]["time"]).total_seconds()
            if gap > float(pass_gap_sec):
                grouped_access_ranges.append((first_idx, prev_idx))
                first_idx = idx
            prev_idx = idx
        grouped_access_ranges.append((first_idx, prev_idx))

        out = []
        for first_access_idx, last_access_idx in grouped_access_ranges:
            expand_start_idx = first_access_idx
            if first_access_idx > 0:
                prev_gap = (samples[first_access_idx]["time"] - samples[first_access_idx - 1]["time"]).total_seconds()
                if prev_gap <= float(pass_gap_sec):
                    expand_start_idx = first_access_idx - 1

            expand_end_idx = last_access_idx
            if last_access_idx + 1 < len(samples):
                next_gap = (samples[last_access_idx + 1]["time"] - samples[last_access_idx]["time"]).total_seconds()
                if next_gap <= float(pass_gap_sec):
                    expand_end_idx = last_access_idx + 1

            expanded_samples = samples[expand_start_idx:expand_end_idx + 1]
            if not expanded_samples:
                continue

            reaches = [float(row.get("reach_m", 0.0) or 0.0) for row in expanded_samples]
            points = [row.get("point") for row in expanded_samples if isinstance(row.get("point"), QgsPointXY)]
            if not points:
                continue

            centerline = cls._build_centerline(points)
            max_reach_m = max(reaches) if reaches else 0.0
            corridor = cls._build_track_corridor(centerline, max_reach_m=max_reach_m)
            if centerline is None or centerline.isEmpty():
                continue
            out.append(
                {
                    "start": samples[first_access_idx]["time"],
                    "end": samples[last_access_idx]["time"],
                    "samples": list(expanded_samples),
                    "centerline": centerline,
                    "corridor": corridor,
                    "mean_reach_m": (sum(reaches) / float(len(reaches))) if reaches else 0.0,
                    "max_reach_m": max_reach_m,
                }
            )
        return out

    @staticmethod
    def _build_centerline(points):
        rows = [pt for pt in (points or []) if isinstance(pt, QgsPointXY)]
        if not rows:
            return None
        if len(rows) == 1:
            return QgsGeometry.fromPointXY(rows[0])
        try:
            return QgsGeometry.fromPolylineXY(rows)
        except Exception:
            return None

    @classmethod
    def _build_track_corridor(cls, centerline, *, max_reach_m):
        if centerline is None or not isinstance(centerline, QgsGeometry) or centerline.isEmpty():
            return None
        try:
            width_m = float(max_reach_m or 0.0)
        except Exception:
            width_m = 0.0
        if width_m <= 0.0:
            return None
        try:
            corridor = centerline.buffer(width_m, 8)
        except Exception:
            corridor = None
        if corridor is None or corridor.isEmpty():
            return None
        return corridor

    @staticmethod
    def _offset_candidates(max_reach_m):
        try:
            reach = float(max_reach_m or 0.0)
        except Exception:
            reach = 0.0
        if reach <= 0.0:
            return [0.0]
        count = 9
        values = [(-reach + (2.0 * reach * idx / float(count - 1))) for idx in range(count)]
        values.append(0.0)
        dedup = sorted({round(val, 3) for val in values})
        return [float(val) for val in dedup]

    @classmethod
    def _select_pass_collection_geometry(
        cls,
        *,
        pass_row,
        aoi_equal,
        unique_geom_equal,
        swath_width_override_m,
    ):
        row = pass_row if isinstance(pass_row, dict) else {}
        samples = row.get("samples") if isinstance(row.get("samples"), list) else []
        if not samples:
            return None
        mean_reach_m = float(row.get("mean_reach_m", 0.0) or 0.0)
        max_reach_m = float(row.get("max_reach_m", 0.0) or 0.0)
        swath_width_m = cls._estimate_swath_width_m(
            mean_reach_m=mean_reach_m,
            swath_width_override_m=swath_width_override_m,
        )
        swath_half_m = max(100.0, float(swath_width_m) * 0.5)
        offsets = cls._offset_candidates(max_reach_m)

        remaining = None
        if isinstance(unique_geom_equal, QgsGeometry) and not unique_geom_equal.isEmpty():
            try:
                remaining = aoi_equal.difference(unique_geom_equal)
            except Exception:
                remaining = None
            if remaining is not None and remaining.isEmpty():
                remaining = None

        best = None
        for offset in offsets:
            centerline = cls._build_steered_centerline(samples, offset)
            strip = cls._buffer_centerline(centerline, swath_half_m)
            if strip is None or strip.isEmpty():
                continue
            if not strip.intersects(aoi_equal):
                continue
            imaged = strip.intersection(aoi_equal)
            if imaged is None or imaged.isEmpty():
                continue

            total_area = float(imaged.area())
            unique_area = total_area
            if remaining is not None and not remaining.isEmpty():
                try:
                    unique_part = imaged.intersection(remaining)
                    unique_area = float(unique_part.area()) if unique_part is not None and not unique_part.isEmpty() else 0.0
                except Exception:
                    unique_area = 0.0
            score = (unique_area, total_area, -abs(float(offset)))
            if best is None or score > best["score"]:
                best = {
                    "score": score,
                    "footprint": strip,
                    "imaged": imaged,
                    "offset_m": float(offset),
                    "swath_width_m": swath_width_m,
                    "imaged_area_km2": max(0.0, total_area / 1_000_000.0),
                    "unique_gain_km2": max(0.0, unique_area / 1_000_000.0),
                }
        return best

    @classmethod
    def _build_steered_centerline(cls, samples, offset_m):
        rows = [row for row in (samples or []) if isinstance(row, dict)]
        points = [row.get("point") for row in rows if isinstance(row.get("point"), QgsPointXY)]
        if not points:
            return None
        if len(points) == 1:
            return QgsGeometry.fromPointXY(points[0])

        shifted = []
        for idx, point in enumerate(points):
            prev_pt = points[idx - 1] if idx > 0 else points[idx]
            next_pt = points[idx + 1] if idx < (len(points) - 1) else points[idx]
            dx = float(next_pt.x()) - float(prev_pt.x())
            dy = float(next_pt.y()) - float(prev_pt.y())
            norm = math.hypot(dx, dy)
            if norm <= 1.0e-6:
                shifted.append(point)
                continue
            nx = -dy / norm
            ny = dx / norm
            try:
                reach_m = float(rows[idx].get("reach_m", 0.0) or 0.0)
            except Exception:
                reach_m = 0.0
            local_offset = float(offset_m)
            if reach_m > 0.0:
                local_offset = max(-reach_m, min(reach_m, local_offset))
            shifted.append(
                QgsPointXY(
                    float(point.x()) + local_offset * nx,
                    float(point.y()) + local_offset * ny,
                )
            )
        return cls._build_centerline(shifted)

    @staticmethod
    def _buffer_centerline(centerline, swath_half_m):
        if centerline is None or not isinstance(centerline, QgsGeometry) or centerline.isEmpty():
            return None
        half = max(100.0, float(swath_half_m or 0.0))
        try:
            return centerline.buffer(half, 8)
        except Exception:
            return None

    @staticmethod
    def _unary_union(geometries):
        rows = []
        for geom in geometries or []:
            if isinstance(geom, QgsGeometry) and not geom.isEmpty():
                rows.append(geom)
        if not rows:
            return None
        if len(rows) == 1:
            return QgsGeometry(rows[0])
        try:
            unioned = QgsGeometry.unaryUnion(rows)
            if unioned is not None and not unioned.isEmpty():
                return unioned
        except Exception:
            unioned = None
        if unioned is None or unioned.isEmpty():
            acc = QgsGeometry(rows[0])
            for geom in rows[1:]:
                try:
                    acc = acc.combine(geom)
                except Exception:
                    continue
            if acc is None or acc.isEmpty():
                return None
            return acc
        return unioned

    def _check_cancelled(self):
        if self._cancel_requested:
            raise _SimulationCancelled()

    def _emit_log(self, text, level):
        self.log.emit(str(text or "").strip(), int(level))

    def _emit_progress(self, current, total, text):
        self.progress.emit(int(current or 0), int(total or 0), str(text or "").strip())
