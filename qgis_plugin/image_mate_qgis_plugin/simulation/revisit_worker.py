# -*- coding: utf-8 -*-
"""Point target revisit simulation worker using Skyfield TLE propagation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import traceback

from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtCore import pyqtSignal
from qgis.core import Qgis
from qgis.core import QgsCoordinateReferenceSystem
from qgis.core import QgsCoordinateTransform
from qgis.core import QgsPointXY
from qgis.core import QgsProject

from ..services.simulation_progress_planner import revisit_progress_plan


class _SimulationCancelled(RuntimeError):
    """Internal cancellation marker."""


class PointRevisitSimulationWorker(QObject):
    """Run point target revisit analysis in a background thread."""

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

        scenario = str(self.payload.get("scenario_id") or "point_revisit_analysis").strip().lower()
        if scenario != "point_revisit_analysis":
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

        target = self._parse_target(self.payload.get("target"))
        target_lat = float(target["lat"])
        target_lon = float(target["lon"])
        target_source = str(target.get("source") or "manual").strip() or "manual"
        target_label = str(target.get("label") or "").strip()

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

        self._emit_log(
            "Point revisit request: "
            f"target=({target_lat:.6f}, {target_lon:.6f}) "
            f"scenario={scenario} "
            f"satellites={len(selected_satellites)} "
            f"step={time_step_sec}s",
            Qgis.Info,
        )
        self._emit_log(
            "Applying daylight filter: target must be on sunlit side (approx sun elevation > 0 deg).",
            Qgis.Info,
        )

        crs_wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_equal = QgsCoordinateReferenceSystem("EPSG:6933")
        to_equal = QgsCoordinateTransform(crs_wgs84, crs_equal, QgsProject.instance())

        target_point_equal = to_equal.transform(QgsPointXY(target_lon, target_lat))

        sample_times = [start_utc + timedelta(seconds=time_step_sec * idx) for idx in range(sample_count)]
        target_daylight_mask = [
            self._is_daylight_approx(sample_time, target_lat, target_lon)
            for sample_time in sample_times
        ]
        dark_target_samples = int(sum(1 for flag in target_daylight_mask if not bool(flag)))
        self._emit_log(
            f"Target daylight samples: {sample_count - dark_target_samples}/{sample_count} "
            f"(night samples filtered: {dark_target_samples}).",
            Qgis.Info,
        )
        ts = load.timescale()
        pass_gap_sec = 2 * int(time_step_sec)

        total_satellites = len(selected_satellites)
        total_days_span = max(1, (end_utc.date() - start_utc.date()).days + 1)
        progress_plan = revisit_progress_plan(
            total_satellites=total_satellites,
            total_days=total_days_span,
        )
        progress_units_per_satellite = int(progress_plan.get("satellite_units", 1000) or 1000)
        finalization_units = int(progress_plan.get("finalization_units", 80) or 80)
        total_progress_units = int(progress_plan.get("total_units", 1) or 1)
        finalization_base = total_satellites * progress_units_per_satellite
        self._emit_progress(0, total_progress_units, "Preparing point revisit simulation...")

        events = []
        for sat_idx, sat_row in enumerate(selected_satellites, start=1):
            self._check_cancelled()
            sat_id = str(sat_row.get("satellite_id") or sat_row.get("id") or "").strip() or "satellite"
            sat_name = str(sat_row.get("name") or sat_id).strip() or sat_id
            tle = sat_row.get("tle") if isinstance(sat_row.get("tle"), dict) else {}
            line1 = str(tle.get("line1") or sat_row.get("tle_line1") or "").strip()
            line2 = str(tle.get("line2") or sat_row.get("tle_line2") or "").strip()
            if not line1 or not line2:
                self._emit_log(f"Skipping {sat_name}: missing TLE line1/line2.", Qgis.Warning)
                continue

            sat_base = (sat_idx - 1) * progress_units_per_satellite
            sat_upper = sat_idx * progress_units_per_satellite
            last_sat_progress = sat_base

            def _emit_satellite_progress(phase_ratio: float, text: str):
                nonlocal last_sat_progress
                safe_ratio = max(0.0, min(1.0, float(phase_ratio)))
                current = sat_base + int(round(safe_ratio * progress_units_per_satellite))
                current = max(last_sat_progress, min(current, sat_upper))
                last_sat_progress = current
                self._emit_progress(current, total_progress_units, text)

            self._emit_progress(
                sat_base,
                total_progress_units,
                f"Initializing {sat_name} ({sat_idx}/{len(selected_satellites)})...",
            )
            _emit_satellite_progress(0.02, f"Initializing {sat_name} ({sat_idx}/{len(selected_satellites)})...")

            satellite = EarthSatellite(line1, line2, sat_name, ts=ts)

            access_samples = []
            # Chunk propagation to keep progress responsive even for a single satellite.
            chunk_size = max(30, min(240, int(math.ceil(sample_count / 50.0))))
            progress_stride = max(1, sample_count // 500)
            for chunk_start in range(0, sample_count, chunk_size):
                self._check_cancelled()
                chunk_end = min(sample_count, chunk_start + chunk_size)
                chunk_times = ts.from_datetimes(sample_times[chunk_start:chunk_end])
                geocentric = satellite.at(chunk_times)
                lat_obj, lon_obj = wgs84.latlon_of(geocentric)
                height_obj = wgs84.height_of(geocentric)

                latitudes = lat_obj.degrees
                longitudes = lon_obj.degrees
                heights_km = height_obj.km
                for offset in range(chunk_end - chunk_start):
                    sample_idx = chunk_start + offset
                    self._check_cancelled()
                    if (sample_idx % progress_stride) == 0 or sample_idx == (sample_count - 1):
                        sample_ratio = float(sample_idx + 1) / float(sample_count)
                        _emit_satellite_progress(
                            0.05 + (0.80 * sample_ratio),
                            f"Simulating {sat_name}: sample {sample_idx + 1}/{sample_count}",
                        )

                    try:
                        lon = float(longitudes[offset])
                        lat = float(latitudes[offset])
                        height_km = float(heights_km[offset])
                    except Exception:
                        continue
                    if not bool(target_daylight_mask[sample_idx]):
                        continue

                    reach_m = max(0.0, float(height_km) * math.tan(off_nadir_rad) * 1000.0)
                    if reach_m <= 0.0:
                        continue

                    try:
                        subpoint_equal = to_equal.transform(QgsPointXY(lon, lat))
                    except Exception:
                        continue

                    distance_m = self._distance_m(subpoint_equal, target_point_equal)
                    if distance_m > reach_m:
                        continue

                    off_nadir_sample_deg = math.degrees(
                        math.atan2(distance_m, max(1.0, float(height_km) * 1000.0))
                    )
                    access_samples.append(
                        {
                            "time": sample_times[sample_idx],
                            "distance_m": float(distance_m),
                            "off_nadir_deg": float(off_nadir_sample_deg),
                        }
                    )

            pass_rows = self._build_passes(access_samples, pass_gap_sec=pass_gap_sec)
            _emit_satellite_progress(
                0.88,
                f"Simulating {sat_name}: grouping {len(pass_rows)} pass(es)...",
            )
            sat_events = 0
            pass_count = max(1, len(pass_rows))
            pass_progress_stride = max(1, pass_count // 80)
            for pass_idx, pass_row in enumerate(pass_rows, start=1):
                self._check_cancelled()
                closest = pass_row.get("closest")
                start = pass_row.get("start")
                end = pass_row.get("end")
                if not isinstance(closest, dict):
                    continue
                if not isinstance(start, datetime) or not isinstance(end, datetime):
                    continue
                event_time = closest.get("time")
                if not isinstance(event_time, datetime):
                    continue
                events.append(
                    {
                        "event_utc": event_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "satellite_id": sat_id,
                        "satellite_name": sat_name,
                        "pass_start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "pass_end_utc": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "closest_distance_km": max(0.0, float(closest.get("distance_m", 0.0) or 0.0) / 1000.0),
                        "closest_off_nadir_deg": max(0.0, float(closest.get("off_nadir_deg", 0.0) or 0.0)),
                    }
                )
                sat_events += 1
                if (pass_idx % pass_progress_stride) == 0 or pass_idx == len(pass_rows):
                    pass_ratio = float(pass_idx) / float(pass_count)
                    _emit_satellite_progress(
                        0.88 + (0.11 * pass_ratio),
                        f"Simulating {sat_name}: pass {pass_idx}/{pass_count}",
                    )

            self._emit_log(f"{sat_name}: revisit events={sat_events}.", Qgis.Info)
            _emit_satellite_progress(1.0, f"Completed {sat_name} ({sat_idx}/{len(selected_satellites)}).")

        self._check_cancelled()
        self._emit_progress(
            finalization_base,
            total_progress_units,
            "Finalizing point revisit metrics...",
        )
        events.sort(key=lambda row: str(row.get("event_utc") or ""))
        self._emit_progress(
            finalization_base + int(round(0.20 * finalization_units)),
            total_progress_units,
            "Finalizing point revisit metrics: sorting events...",
        )
        metrics = self._build_metrics(
            events=events,
            start_utc=start_utc,
            end_utc=end_utc,
        )
        self._emit_progress(
            finalization_base + int(round(0.45 * finalization_units)),
            total_progress_units,
            "Finalizing point revisit metrics: computing summary stats...",
        )

        def _on_days_progress(done_days, total_days):
            if total_days <= 0:
                return
            ratio = max(0.0, min(1.0, float(done_days) / float(total_days)))
            current = finalization_base + int(round((0.45 + (0.50 * ratio)) * finalization_units))
            self._emit_progress(
                current,
                total_progress_units,
                f"Finalizing point revisit metrics: day {int(done_days)}/{int(total_days)}",
            )

        days = self._build_days(
            events=events,
            start_utc=start_utc,
            end_utc=end_utc,
            progress_callback=_on_days_progress,
        )
        self._emit_progress(total_progress_units, total_progress_units, "Simulation completed.")

        self._emit_log(
            "Point revisit completed: "
            f"events={metrics['total_collection_events']}, "
            f"first={metrics['first_access_utc'] or '-'}, "
            f"last={metrics['last_access_utc'] or '-'}, "
            f"longest_gap_min={metrics['longest_gap_min']:.2f}.",
            Qgis.Info,
        )

        return {
            "scenario": "point_revisit_analysis",
            "start_utc": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_utc": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "satellite_count": len(selected_satellites),
            "target": {
                "lat": target_lat,
                "lon": target_lon,
                "source": target_source,
                "label": target_label,
            },
            "total_collection_events": metrics["total_collection_events"],
            "first_access_utc": metrics["first_access_utc"],
            "last_access_utc": metrics["last_access_utc"],
            "revisit_intervals_min": metrics["revisit_intervals_min"],
            "min_revisit_min": metrics["min_revisit_min"],
            "mean_revisit_min": metrics["mean_revisit_min"],
            "max_revisit_min": metrics["max_revisit_min"],
            "longest_gap_min": metrics["longest_gap_min"],
            "events": events,
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
                "Skyfield is required for Simulation tab point revisit analysis. "
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

    @staticmethod
    def _parse_target(value):
        row = value if isinstance(value, dict) else {}
        try:
            lat = float(row.get("lat"))
            lon = float(row.get("lon"))
        except Exception as exc:
            raise RuntimeError("Point target coordinates are required.") from exc
        if lat < -90.0 or lat > 90.0:
            raise RuntimeError("Point target latitude must be in [-90, 90].")
        if lon < -180.0 or lon > 180.0:
            raise RuntimeError("Point target longitude must be in [-180, 180].")
        return {
            "lat": lat,
            "lon": lon,
            "source": str(row.get("source") or "manual").strip() or "manual",
            "label": str(row.get("label") or "").strip(),
        }

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

    @classmethod
    def _build_passes(cls, access_samples, *, pass_gap_sec):
        samples = []
        for row in access_samples or []:
            if not isinstance(row, dict):
                continue
            sample_time = row.get("time")
            if not isinstance(sample_time, datetime):
                continue
            try:
                distance_m = float(row.get("distance_m", 0.0) or 0.0)
            except Exception:
                distance_m = 0.0
            try:
                off_nadir_deg = float(row.get("off_nadir_deg", 0.0) or 0.0)
            except Exception:
                off_nadir_deg = 0.0
            samples.append(
                {
                    "time": sample_time,
                    "distance_m": max(0.0, distance_m),
                    "off_nadir_deg": max(0.0, off_nadir_deg),
                }
            )
        if not samples:
            return []

        samples.sort(key=lambda row: row["time"])
        out = []
        active = []
        active_start = None
        active_prev = None

        def _flush():
            if not active:
                return
            start = active_start
            end = active[-1]["time"]
            closest = min(active, key=lambda row: float(row.get("distance_m", 0.0)))
            out.append(
                {
                    "start": start,
                    "end": end,
                    "closest": {
                        "time": closest.get("time"),
                        "distance_m": float(closest.get("distance_m", 0.0) or 0.0),
                        "off_nadir_deg": float(closest.get("off_nadir_deg", 0.0) or 0.0),
                    },
                }
            )

        for sample in samples:
            sample_time = sample["time"]
            if active_start is None:
                active_start = sample_time
                active_prev = sample_time
                active = [sample]
                continue
            gap = (sample_time - active_prev).total_seconds()
            if gap > float(pass_gap_sec):
                _flush()
                active_start = sample_time
                active = [sample]
            else:
                active.append(sample)
            active_prev = sample_time
        _flush()
        return out

    @classmethod
    def _build_metrics(cls, *, events, start_utc, end_utc):
        event_times = []
        for row in events or []:
            event_utc = str(row.get("event_utc") or "").strip()
            if not event_utc:
                continue
            try:
                event_times.append(cls._parse_utc(event_utc))
            except Exception:
                continue
        event_times.sort()

        intervals_min = []
        if len(event_times) >= 2:
            for idx in range(1, len(event_times)):
                delta_min = (event_times[idx] - event_times[idx - 1]).total_seconds() / 60.0
                intervals_min.append(max(0.0, float(delta_min)))

        first_access = event_times[0].strftime("%Y-%m-%dT%H:%M:%SZ") if event_times else None
        last_access = event_times[-1].strftime("%Y-%m-%dT%H:%M:%SZ") if event_times else None

        min_revisit = min(intervals_min) if intervals_min else None
        max_revisit = max(intervals_min) if intervals_min else None
        mean_revisit = (sum(intervals_min) / float(len(intervals_min))) if intervals_min else None

        boundaries = []
        if event_times:
            boundaries.append((event_times[0] - start_utc).total_seconds() / 60.0)
            for idx in range(1, len(event_times)):
                boundaries.append((event_times[idx] - event_times[idx - 1]).total_seconds() / 60.0)
            boundaries.append((end_utc - event_times[-1]).total_seconds() / 60.0)
        else:
            boundaries.append((end_utc - start_utc).total_seconds() / 60.0)
        longest_gap = max(0.0, max(float(value) for value in boundaries)) if boundaries else 0.0

        return {
            "total_collection_events": int(len(event_times)),
            "first_access_utc": first_access,
            "last_access_utc": last_access,
            "revisit_intervals_min": intervals_min,
            "min_revisit_min": min_revisit,
            "mean_revisit_min": mean_revisit,
            "max_revisit_min": max_revisit,
            "longest_gap_min": longest_gap,
        }

    @classmethod
    def _build_days(cls, *, events, start_utc, end_utc, progress_callback=None):
        counts = {}
        for row in events or []:
            event_utc = str(row.get("event_utc") or "").strip()
            if not event_utc:
                continue
            try:
                event_time = cls._parse_utc(event_utc)
            except Exception:
                continue
            day_key = event_time.date().isoformat()
            counts[day_key] = int(counts.get(day_key, 0)) + 1

        out = []
        cursor = start_utc.date()
        end_date = end_utc.date()
        total_days = max(1, int((end_date - cursor).days) + 1)
        cumulative = 0
        processed_days = 0
        while cursor <= end_date:
            day_key = cursor.isoformat()
            day_count = int(counts.get(day_key, 0))
            cumulative += day_count
            out.append(
                {
                    "date": day_key,
                    "event_count": day_count,
                    "cumulative_event_count": cumulative,
                }
            )
            processed_days += 1
            if progress_callback is not None:
                try:
                    progress_callback(processed_days, total_days)
                except Exception:
                    pass
            cursor = cursor + timedelta(days=1)
        return out

    @staticmethod
    def _distance_m(a: QgsPointXY, b: QgsPointXY) -> float:
        dx = float(a.x()) - float(b.x())
        dy = float(a.y()) - float(b.y())
        return math.hypot(dx, dy)

    def _check_cancelled(self):
        if self._cancel_requested:
            raise _SimulationCancelled()

    def _emit_log(self, text, level):
        self.log.emit(str(text or "").strip(), int(level))

    def _emit_progress(self, current, total, text):
        self.progress.emit(int(current or 0), int(total or 0), str(text or "").strip())
