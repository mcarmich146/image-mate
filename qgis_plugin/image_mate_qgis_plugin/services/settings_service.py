# -*- coding: utf-8 -*-
"""Persistent plugin settings backed by QSettings."""

from dataclasses import dataclass

from qgis.PyQt.QtCore import QSettings


SETTINGS_PREFIX = "image_mate"


@dataclass
class ProviderSettings:
    backend_api_base_url: str = "http://localhost:8000"
    satellogic_auth_mode: str = "oauth_client_credentials"
    satellogic_contract_id: str = ""
    satellogic_stac_url: str = "https://api.satellogic.com/archive/stac"
    satellogic_authcfg_id: str = ""
    cdse_enabled: bool = False
    cdse_stac_url: str = "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0"
    cdse_wmts_base_url: str = "https://sh.dataspace.copernicus.eu/ogc/wmts"
    cdse_wmts_instance_id: str = ""
    cdse_wmts_layer_id: str = "TRUE-COLOR"
    cdse_authcfg_id: str = ""


class SettingsService:
    def __init__(self):
        self._settings = QSettings()

    def load(self):
        return ProviderSettings(
            backend_api_base_url=self._get_str("backend/api_base_url", "http://localhost:8000"),
            satellogic_auth_mode=self._get_str("satellogic/auth_mode", "oauth_client_credentials"),
            satellogic_contract_id=self._get_str("satellogic/contract_id", ""),
            satellogic_stac_url=self._get_str("satellogic/stac_url", "https://api.satellogic.com/archive/stac"),
            satellogic_authcfg_id=self._get_str("satellogic/authcfg_id", ""),
            cdse_enabled=self._get_bool("cdse/enabled", False),
            cdse_stac_url=self._get_str("cdse/stac_url", "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0"),
            cdse_wmts_base_url=self._get_str("cdse/wmts_base_url", "https://sh.dataspace.copernicus.eu/ogc/wmts"),
            cdse_wmts_instance_id=self._get_str("cdse/wmts_instance_id", ""),
            cdse_wmts_layer_id=self._get_str("cdse/wmts_layer_id", "TRUE-COLOR"),
            cdse_authcfg_id=self._get_str("cdse/authcfg_id", ""),
        )

    def save(self, cfg):
        self._settings.setValue(self._k("backend/api_base_url"), cfg.backend_api_base_url)
        self._settings.setValue(self._k("satellogic/auth_mode"), cfg.satellogic_auth_mode)
        self._settings.setValue(self._k("satellogic/contract_id"), cfg.satellogic_contract_id)
        self._settings.setValue(self._k("satellogic/stac_url"), cfg.satellogic_stac_url)
        self._settings.setValue(self._k("satellogic/authcfg_id"), cfg.satellogic_authcfg_id)
        self._settings.setValue(self._k("cdse/enabled"), bool(cfg.cdse_enabled))
        self._settings.setValue(self._k("cdse/stac_url"), cfg.cdse_stac_url)
        self._settings.setValue(self._k("cdse/wmts_base_url"), cfg.cdse_wmts_base_url)
        self._settings.setValue(self._k("cdse/wmts_instance_id"), cfg.cdse_wmts_instance_id)
        self._settings.setValue(self._k("cdse/wmts_layer_id"), cfg.cdse_wmts_layer_id)
        self._settings.setValue(self._k("cdse/authcfg_id"), cfg.cdse_authcfg_id)
        self._settings.sync()

    def _k(self, suffix):
        return f"{SETTINGS_PREFIX}/{suffix}"

    def _get_str(self, key, default):
        value = self._settings.value(self._k(key), default)
        if value is None:
            return default
        return str(value)

    def _get_bool(self, key, default):
        value = self._settings.value(self._k(key), default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
