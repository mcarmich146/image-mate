# -*- coding: utf-8 -*-
"""Persistent plugin settings backed by QSettings."""

from dataclasses import dataclass
from pathlib import Path
import os

from qgis.PyQt.QtCore import QSettings


SETTINGS_PREFIX = "image_mate"
DEFAULT_CAMPAIGN_BASE_DIR = str((Path.home() / "ImageMateCampaigns").resolve())
CDSE_CLIENT_ID_ENV_KEY = "CDSE_CLIENT_ID"
CDSE_CLIENT_SECRET_ENV_KEY = "CDSE_CLIENT_SECRET"
BACKEND_API_BASE_URL_ENV_KEY = "BACKEND_API_BASE_URL"
VESSEL_MODEL_DEFAULT_PATH_ENV_KEY = "VESSEL_MODEL_DEFAULT_PATH"
VESSEL_OBB_MODEL_DEFAULT_PATH_ENV_KEY = "VESSEL_OBB_MODEL_DEFAULT_PATH"
VESSEL_CONF_THRESHOLD_ENV_KEY = "VESSEL_CONF_THRESHOLD"
VESSEL_IOU_THRESHOLD_ENV_KEY = "VESSEL_IOU_THRESHOLD"
VESSEL_MAX_DETECTIONS_ENV_KEY = "VESSEL_MAX_DETECTIONS"


@dataclass
class ProviderSettings:
    backend_api_base_url: str = "http://localhost:8000"
    satellogic_auth_mode: str = "oauth_client_credentials"
    satellogic_contract_id: str = ""
    satellogic_stac_url: str = "https://api.satellogic.com/archive/stac"
    satellogic_authcfg_id: str = ""
    cdse_enabled: bool = True
    cdse_stac_url: str = "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0"
    cdse_client_id: str = ""
    cdse_client_secret: str = ""
    cdse_wmts_base_url: str = "https://sh.dataspace.copernicus.eu/ogc/wmts"
    cdse_wmts_instance_id: str = ""
    cdse_wmts_layer_id: str = "TRUE-COLOR"
    cdse_wmts_use_backend_proxy: bool = True
    cdse_authcfg_id: str = ""
    campaign_managed_storage: bool = True
    campaign_base_dir: str = DEFAULT_CAMPAIGN_BASE_DIR
    campaign_uid: str = "default-campaign"
    campaign_name: str = "Default Campaign"
    asset_intel_db_path: str = ""
    vessel_model_default_path: str = ""
    vessel_obb_model_default_path: str = ""
    vessel_conf_threshold_default: float = 0.25
    vessel_iou_threshold_default: float = 0.45
    vessel_max_detections_default: int = 20


class SettingsService:
    def __init__(self):
        self._settings = QSettings()
        self._env_values = self._load_env_values()

    def load(self):
        return ProviderSettings(
            backend_api_base_url=self._get_str_with_env(
                "backend/api_base_url",
                "http://localhost:8000",
                env_keys=(BACKEND_API_BASE_URL_ENV_KEY,),
            ),
            satellogic_auth_mode=self._get_str("satellogic/auth_mode", "oauth_client_credentials"),
            satellogic_contract_id=self._get_str("satellogic/contract_id", ""),
            satellogic_stac_url=self._get_str("satellogic/stac_url", "https://api.satellogic.com/archive/stac"),
            satellogic_authcfg_id=self._get_str("satellogic/authcfg_id", ""),
            cdse_enabled=True,
            cdse_stac_url=self._get_str("cdse/stac_url", "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0"),
            cdse_client_id=self._get_str("cdse/client_id", ""),
            cdse_client_secret=self._get_str("cdse/client_secret", ""),
            cdse_wmts_base_url=self._get_str("cdse/wmts_base_url", "https://sh.dataspace.copernicus.eu/ogc/wmts"),
            cdse_wmts_instance_id=self._get_str("cdse/wmts_instance_id", ""),
            cdse_wmts_layer_id=self._get_str("cdse/wmts_layer_id", "TRUE-COLOR"),
            cdse_wmts_use_backend_proxy=self._get_bool("cdse/wmts_use_backend_proxy", True),
            cdse_authcfg_id=self._get_str("cdse/authcfg_id", ""),
            campaign_managed_storage=self._get_bool("campaign/managed_storage", True),
            campaign_base_dir=self._get_str("campaign/base_dir", DEFAULT_CAMPAIGN_BASE_DIR),
            campaign_uid=self._get_str("campaign/uid", "default-campaign"),
            campaign_name=self._get_str("campaign/name", "Default Campaign"),
            asset_intel_db_path=self._get_str("asset_intel/db_path", ""),
            vessel_model_default_path=self._get_str_with_env(
                "vessel/model_default_path",
                "",
                env_keys=(VESSEL_MODEL_DEFAULT_PATH_ENV_KEY,),
                resolve_relative_path=True,
            ),
            vessel_obb_model_default_path=self._get_str_with_env(
                "vessel/obb_model_default_path",
                "",
                env_keys=(VESSEL_OBB_MODEL_DEFAULT_PATH_ENV_KEY,),
                resolve_relative_path=True,
            ),
            vessel_conf_threshold_default=self._get_float_with_env(
                "vessel/conf_threshold",
                0.25,
                env_keys=(VESSEL_CONF_THRESHOLD_ENV_KEY,),
            ),
            vessel_iou_threshold_default=self._get_float_with_env(
                "vessel/iou_threshold",
                0.45,
                env_keys=(VESSEL_IOU_THRESHOLD_ENV_KEY,),
            ),
            vessel_max_detections_default=self._get_int_with_env(
                "vessel/max_detections",
                20,
                env_keys=(VESSEL_MAX_DETECTIONS_ENV_KEY,),
            ),
        )

    def save(self, cfg):
        self._settings.setValue(self._k("backend/api_base_url"), cfg.backend_api_base_url)
        self._settings.setValue(self._k("satellogic/auth_mode"), cfg.satellogic_auth_mode)
        self._settings.setValue(self._k("satellogic/contract_id"), cfg.satellogic_contract_id)
        self._settings.setValue(self._k("satellogic/stac_url"), cfg.satellogic_stac_url)
        self._settings.setValue(self._k("satellogic/authcfg_id"), cfg.satellogic_authcfg_id)
        self._settings.setValue(self._k("cdse/enabled"), bool(cfg.cdse_enabled))
        self._settings.setValue(self._k("cdse/stac_url"), cfg.cdse_stac_url)
        self._settings.setValue(self._k("cdse/client_id"), cfg.cdse_client_id)
        self._settings.setValue(self._k("cdse/client_secret"), cfg.cdse_client_secret)
        self._settings.setValue(self._k("cdse/wmts_base_url"), cfg.cdse_wmts_base_url)
        self._settings.setValue(self._k("cdse/wmts_instance_id"), cfg.cdse_wmts_instance_id)
        self._settings.setValue(self._k("cdse/wmts_layer_id"), cfg.cdse_wmts_layer_id)
        self._settings.setValue(self._k("cdse/wmts_use_backend_proxy"), bool(cfg.cdse_wmts_use_backend_proxy))
        self._settings.setValue(self._k("cdse/authcfg_id"), cfg.cdse_authcfg_id)
        self._settings.setValue(self._k("campaign/managed_storage"), bool(cfg.campaign_managed_storage))
        self._settings.setValue(self._k("campaign/base_dir"), str(cfg.campaign_base_dir or DEFAULT_CAMPAIGN_BASE_DIR))
        self._settings.setValue(self._k("campaign/uid"), str(cfg.campaign_uid or "default-campaign"))
        self._settings.setValue(self._k("campaign/name"), str(cfg.campaign_name or "Default Campaign"))
        self._settings.setValue(self._k("asset_intel/db_path"), str(cfg.asset_intel_db_path or ""))
        self._settings.setValue(self._k("vessel/model_default_path"), str(cfg.vessel_model_default_path or ""))
        self._settings.setValue(
            self._k("vessel/obb_model_default_path"),
            str(getattr(cfg, "vessel_obb_model_default_path", "") or ""),
        )
        self._settings.setValue(self._k("vessel/conf_threshold"), float(cfg.vessel_conf_threshold_default or 0.25))
        self._settings.setValue(self._k("vessel/iou_threshold"), float(cfg.vessel_iou_threshold_default or 0.45))
        self._settings.setValue(self._k("vessel/max_detections"), int(cfg.vessel_max_detections_default or 20))
        self._settings.sync()
        self._sync_cdse_credentials_to_env(cfg)
        self._sync_vessel_settings_to_env(cfg)

    def _k(self, suffix):
        return f"{SETTINGS_PREFIX}/{suffix}"

    def _get_str(self, key, default):
        value = self._settings.value(self._k(key), default)
        if value is None:
            return default
        return str(value)

    def _get_str_with_env(self, key, default, *, env_keys=(), resolve_relative_path=False):
        qsettings_key = self._k(key)
        has_qsettings_value = self._settings.contains(qsettings_key)
        if has_qsettings_value:
            current = str(self._get_str(key, default) or "").strip()
            if current:
                return current
        for env_key in env_keys or ():
            env_value = self._get_env_value(env_key, "")
            if not env_value:
                continue
            if resolve_relative_path:
                return self._resolve_path_from_env(env_value)
            return env_value
        if has_qsettings_value:
            return str(self._get_str(key, default) or "").strip()
        return str(default or "").strip()

    def _get_bool(self, key, default):
        value = self._settings.value(self._k(key), default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _get_float(self, key, default):
        value = self._settings.value(self._k(key), default)
        try:
            return float(value)
        except Exception:
            return float(default)

    def _get_float_with_env(self, key, default, *, env_keys=()):
        qsettings_key = self._k(key)
        if self._settings.contains(qsettings_key):
            return self._get_float(key, default)
        for env_key in env_keys or ():
            raw = self._get_env_value(env_key, "")
            if not raw:
                continue
            try:
                return float(raw)
            except Exception:
                continue
        return float(default)

    def _get_int(self, key, default):
        value = self._settings.value(self._k(key), default)
        try:
            return int(float(value))
        except Exception:
            return int(default)

    def _get_int_with_env(self, key, default, *, env_keys=()):
        qsettings_key = self._k(key)
        if self._settings.contains(qsettings_key):
            return self._get_int(key, default)
        for env_key in env_keys or ():
            raw = self._get_env_value(env_key, "")
            if not raw:
                continue
            try:
                return int(float(raw))
            except Exception:
                continue
        return int(default)

    def _sync_cdse_credentials_to_env(self, cfg):
        client_id = str(getattr(cfg, "cdse_client_id", "") or "").strip()
        client_secret = str(getattr(cfg, "cdse_client_secret", "") or "").strip()
        updates = {}
        if client_id:
            updates[CDSE_CLIENT_ID_ENV_KEY] = client_id
        if client_secret:
            updates[CDSE_CLIENT_SECRET_ENV_KEY] = client_secret
        if not updates:
            return

        env_path = self._resolve_env_file_path()
        if env_path is None:
            return

        try:
            self._upsert_env_values(env_path, updates)
            for key, value in updates.items():
                os.environ[key] = value
        except Exception:
            # Keep QSettings persistence as the primary save path.
            return

    def _sync_vessel_settings_to_env(self, cfg):
        model_path = str(getattr(cfg, "vessel_model_default_path", "") or "").strip()
        conf = float(getattr(cfg, "vessel_conf_threshold_default", 0.25) or 0.25)
        iou = float(getattr(cfg, "vessel_iou_threshold_default", 0.45) or 0.45)
        max_det = int(getattr(cfg, "vessel_max_detections_default", 20) or 20)

        updates = {
            VESSEL_CONF_THRESHOLD_ENV_KEY: f"{conf:.2f}",
            VESSEL_IOU_THRESHOLD_ENV_KEY: f"{iou:.2f}",
            VESSEL_MAX_DETECTIONS_ENV_KEY: str(max_det),
        }
        if model_path:
            updates[VESSEL_MODEL_DEFAULT_PATH_ENV_KEY] = model_path
        obb_model_path = str(getattr(cfg, "vessel_obb_model_default_path", "") or "").strip()
        if obb_model_path:
            updates[VESSEL_OBB_MODEL_DEFAULT_PATH_ENV_KEY] = obb_model_path
        if not updates:
            return

        env_path = self._resolve_env_file_path()
        if env_path is None:
            return

        try:
            self._upsert_env_values(env_path, updates)
            for key, value in updates.items():
                os.environ[key] = str(value)
        except Exception:
            return

    def _resolve_path_from_env(self, value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        path_obj = Path(raw).expanduser()
        if path_obj.is_absolute():
            return str(path_obj)
        env_path = self._resolve_env_file_path()
        if env_path is not None:
            try:
                return str((env_path.parent / path_obj).resolve())
            except Exception:
                pass
        try:
            return str((Path.cwd() / path_obj).resolve())
        except Exception:
            return str(path_obj)

    def _load_env_values(self):
        values = {}
        env_path = self._resolve_env_file_path()
        if env_path is None or not env_path.exists():
            return values
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return values
        for line in lines:
            key = self._parse_env_key(line)
            if not key:
                continue
            raw = str(line or "").strip()
            if raw.startswith("export "):
                raw = raw[len("export ") :].strip()
            if "=" not in raw:
                continue
            value = raw.split("=", 1)[1].strip()
            if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[key] = value
        return values

    def _get_env_value(self, key, default=""):
        env_key = str(key or "").strip()
        if not env_key:
            return str(default or "").strip()
        raw = str(os.getenv(env_key, "") or "").strip()
        if raw:
            return raw
        cached = str(self._env_values.get(env_key, "") or "").strip()
        if cached:
            return cached
        return str(default or "").strip()

    def _resolve_env_file_path(self):
        try:
            from ..clients import config as client_config

            loaded_env_file = getattr(client_config, "env_file", None)
            if loaded_env_file:
                return Path(loaded_env_file)
        except Exception:
            pass

        explicit = str(os.getenv("IMAGE_MATE_ENV_PATH", "") or "").strip()
        if explicit:
            return Path(explicit).expanduser()

        for candidate in self._env_candidates():
            if candidate.exists():
                return candidate

        # Deterministic fallback when no .env exists yet.
        return Path.home() / ".image-mate" / ".env"

    @staticmethod
    def _env_candidates():
        plugin_dir = Path(__file__).resolve().parent.parent
        return [
            Path.home() / ".image-mate" / ".env",
            Path.home() / ".env",
            Path.home() / "Documents" / "Personal" / "dev" / "image-mate" / ".env",
            Path.home() / "dev" / "image-mate" / ".env",
            Path.home() / "code" / "image-mate" / ".env",
            Path.home() / "projects" / "image-mate" / ".env",
            plugin_dir.parent.parent / ".env",
            plugin_dir / ".env",
        ]

    @staticmethod
    def _upsert_env_values(env_path, updates):
        env_path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        replaced = set()
        output = []
        for line in lines:
            key = SettingsService._parse_env_key(line)
            if key in updates:
                if key in replaced:
                    continue
                output.append(f"{key}={SettingsService._sanitize_env_value(updates[key])}")
                replaced.add(key)
                continue
            output.append(line)

        for key, value in updates.items():
            if key not in replaced:
                output.append(f"{key}={SettingsService._sanitize_env_value(value)}")

        env_path.write_text("\n".join(output) + ("\n" if output else ""), encoding="utf-8")

    @staticmethod
    def _parse_env_key(line):
        stripped = str(line or "").strip().lstrip("\ufeff")
        if not stripped or stripped.startswith("#"):
            return ""
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            return ""
        return stripped.split("=", 1)[0].strip().lstrip("\ufeff")

    @staticmethod
    def _sanitize_env_value(value):
        return str(value or "").replace("\r", "").replace("\n", "")
