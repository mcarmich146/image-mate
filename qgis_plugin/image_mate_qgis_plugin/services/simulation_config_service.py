# -*- coding: utf-8 -*-
"""Simulation constellation configuration persistence and validation."""

from __future__ import annotations

from pathlib import Path
import json

from qgis.core import QgsApplication


class SimulationConfigService:
    """Load/save constellation config used by simulation workflows."""

    SCHEMA_VERSION = 1
    DEFAULT_SWATH_WIDTH_KM = 6.5

    def __init__(self):
        base_dir = Path(str(QgsApplication.qgisSettingsDirPath() or "")).expanduser()
        if not str(base_dir).strip():
            base_dir = Path.home() / ".qgis3"
        self._config_path = base_dir / "image_mate" / "simulation_constellation.json"

    @property
    def config_path(self) -> Path:
        return self._config_path

    def default_config(self) -> dict:
        return {
            "schema_version": int(self.SCHEMA_VERSION),
            "constellation_name": "default",
            "satellites": [
                {
                    "satellite_id": "SIM-SSO-475",
                    "name": "Simulation SSO 475km",
                    "priority": 1,
                    "enabled": True,
                    "swath_width_km": float(self.DEFAULT_SWATH_WIDTH_KM),
                    "tle": {
                        # Synthetic example TLE representing an approximately
                        # 475 km sun-synchronous style orbit for MVP simulation.
                        "line1": "1 99999U 26001A   26052.00000000  .00000010  00000+0  10000-3 0  9993",
                        "line2": "2 99999  97.4000 120.0000 0010000  90.0000   0.0000 15.31900000    09",
                    },
                }
            ],
        }

    def load_config(self) -> dict:
        if not self._config_path.exists():
            return self.default_config()
        try:
            payload = json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Failed to read simulation config {self._config_path}: {exc}") from exc
        normalized = self.validate_config(payload)
        satellites = normalized.get("satellites") if isinstance(normalized.get("satellites"), list) else []
        if satellites:
            return normalized
        return self.default_config()

    def save_config(self, cfg: dict) -> dict:
        normalized = self.validate_config(cfg)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(normalized, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return normalized

    def import_config(self, path: str) -> dict:
        file_path = Path(str(path or "").strip()).expanduser()
        if not file_path.exists():
            raise RuntimeError(f"Simulation config import path does not exist: {file_path}")
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Failed to parse simulation config JSON {file_path}: {exc}") from exc
        return self.validate_config(payload)

    def export_config(self, path: str, cfg: dict) -> dict:
        normalized = self.validate_config(cfg)
        file_path = Path(str(path or "").strip()).expanduser()
        if not str(file_path).strip():
            raise RuntimeError("Simulation config export path is required.")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(normalized, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return normalized

    def validate_config(self, cfg: dict) -> dict:
        raw = cfg if isinstance(cfg, dict) else {}
        raw_satellites = raw.get("satellites")
        if raw_satellites is None:
            raw_satellites = []
        if not isinstance(raw_satellites, list):
            raise RuntimeError("Simulation config 'satellites' must be a list.")

        satellites = []
        seen_ids = set()
        for idx, row in enumerate(raw_satellites):
            sat = row if isinstance(row, dict) else {}
            satellite_id = str(sat.get("satellite_id") or sat.get("id") or "").strip()
            if not satellite_id:
                raise RuntimeError(f"Simulation config satellite #{idx + 1} is missing satellite_id.")
            if satellite_id in seen_ids:
                raise RuntimeError(f"Simulation config contains duplicate satellite_id '{satellite_id}'.")
            seen_ids.add(satellite_id)

            name = str(sat.get("name") or satellite_id).strip() or satellite_id
            try:
                priority = int(float(sat.get("priority", 100)))
            except Exception:
                priority = 100
            enabled = bool(sat.get("enabled", True))
            swath_width_km = self._parse_swath_width_km(
                sat.get("swath_width_km"),
                sat.get("swath_km"),
                sat.get("swath_width_m"),
            )

            tle_obj = sat.get("tle") if isinstance(sat.get("tle"), dict) else {}
            line1 = str(tle_obj.get("line1") or sat.get("tle_line1") or "").strip()
            line2 = str(tle_obj.get("line2") or sat.get("tle_line2") or "").strip()
            if not line1 or not line2:
                raise RuntimeError(f"Satellite '{satellite_id}' must include TLE line1 and line2.")
            if not line1.startswith("1 "):
                raise RuntimeError(f"Satellite '{satellite_id}' has invalid TLE line1 format.")
            if not line2.startswith("2 "):
                raise RuntimeError(f"Satellite '{satellite_id}' has invalid TLE line2 format.")

            satellites.append(
                {
                    "satellite_id": satellite_id,
                    "name": name,
                    "priority": int(priority),
                    "enabled": enabled,
                    "swath_width_km": float(swath_width_km),
                    "tle": {
                        "line1": line1,
                        "line2": line2,
                    },
                }
            )

        constellation_name = str(raw.get("constellation_name") or "default").strip() or "default"
        try:
            schema_version = int(float(raw.get("schema_version", self.SCHEMA_VERSION)))
        except Exception:
            schema_version = int(self.SCHEMA_VERSION)

        return {
            "schema_version": int(schema_version),
            "constellation_name": constellation_name,
            "satellites": satellites,
        }

    def _parse_swath_width_km(self, swath_width_km_value, swath_km_value, swath_width_m_value) -> float:
        candidates = [swath_width_km_value, swath_km_value]
        for value in candidates:
            if value is None:
                continue
            try:
                width_km = float(value)
            except Exception:
                raise RuntimeError("Satellite swath width must be a numeric value in kilometers.")
            if width_km <= 0.0:
                raise RuntimeError("Satellite swath width must be > 0 km.")
            return float(width_km)
        if swath_width_m_value is not None:
            try:
                width_m = float(swath_width_m_value)
            except Exception:
                raise RuntimeError("Satellite swath width (meters) must be numeric.")
            if width_m <= 0.0:
                raise RuntimeError("Satellite swath width (meters) must be > 0.")
            return float(width_m) / 1000.0
        return float(self.DEFAULT_SWATH_WIDTH_KM)
