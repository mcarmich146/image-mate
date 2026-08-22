from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import sys
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _split_csv(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _as_bool(value: str, default: bool = False) -> bool:
    raw = (value or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _rooted_path(name: str, default: Path) -> Path:
    value = Path(os.getenv(name, str(default))).expanduser()
    return value if value.is_absolute() else (ROOT_DIR / value).resolve()


def _json_map(value: str) -> dict[str, str]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key).strip(): str(item).strip() for key, item in parsed.items() if str(key).strip()}


@dataclass
class Settings:
    satellogic_bearer_token: str = os.getenv("SATELLOGIC_BEARER_TOKEN", "")
    satellogic_key_id: str = os.getenv("SATELLOGIC_KEY_ID", "")
    satellogic_key_secret: str = os.getenv("SATELLOGIC_KEY_SECRET", "")
    # Supported values: oauth_client_credentials, bearer, key_secret, auto
    satellogic_auth_mode: str = os.getenv("SATELLOGIC_AUTH_MODE", "oauth_client_credentials")
    satellogic_contract_id: str = os.getenv("SATELLOGIC_CONTRACT_ID", "")
    satellogic_collection_id: str = os.getenv("SATELLOGIC_COLLECTION_ID", "l1d-sr")
    satellogic_api_base_url: str = os.getenv("SATELLOGIC_API_BASE_URL", "https://api.satellogic.com")
    satellogic_stac_url: str = os.getenv("SATELLOGIC_STAC_URL", "https://api.satellogic.com/archive/stac")
    satellogic_token_url: str = os.getenv("SATELLOGIC_TOKEN_URL", "https://auth.platform.satellogic.com/oauth/token")
    satellogic_cog_timeout_seconds: int = int(os.getenv("SATELLOGIC_COG_TIMEOUT_SECONDS", "180"))
    satellogic_satellite_generation_map: dict[str, str] = None  # type: ignore[assignment]

    merlin_s2_enabled: bool = _as_bool(os.getenv("MERLIN_S2_ENABLED", "false"), default=False)
    cdse_client_id: str = os.getenv("CDSE_CLIENT_ID", "")
    cdse_client_secret: str = os.getenv("CDSE_CLIENT_SECRET", "")
    cdse_download_client_id: str = os.getenv("CDSE_DOWNLOAD_CLIENT_ID", "cdse-public")
    cdse_download_username: str = os.getenv("CDSE_DOWNLOAD_USERNAME", "")
    cdse_download_password: str = os.getenv("CDSE_DOWNLOAD_PASSWORD", "")
    cdse_download_totp: str = os.getenv("CDSE_DOWNLOAD_TOTP", "")
    cdse_token_url: str = os.getenv(
        "CDSE_TOKEN_URL",
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
    )
    cdse_stac_url: str = os.getenv("CDSE_STAC_URL", "https://sh.dataspace.copernicus.eu/api/v1/catalog/1.0.0")
    cdse_odata_url: str = os.getenv("CDSE_ODATA_URL", "https://catalogue.dataspace.copernicus.eu/odata/v1")
    cdse_subscriptions_url: str = os.getenv("CDSE_SUBSCRIPTIONS_URL", "https://catalogue.dataspace.copernicus.eu/subscriptions/v1")
    cdse_process_url: str = os.getenv("CDSE_PROCESS_URL", "https://sh.dataspace.copernicus.eu/api/v1/process")
    cdse_request_timeout_seconds: int = int(os.getenv("CDSE_REQUEST_TIMEOUT_SECONDS", "60"))
    cdse_sentinel2_collections: list[str] = None  # type: ignore[assignment]
    cdse_wmts_base_url: str = os.getenv("CDSE_WMTS_BASE_URL", "https://sh.dataspace.copernicus.eu/ogc/wmts")
    cdse_wmts_instance_id: str = os.getenv("CDSE_WMTS_INSTANCE_ID", "")
    cdse_wmts_layer_id: str = os.getenv("CDSE_WMTS_LAYER_ID", "TRUE-COLOR")
    cdse_wmts_format: str = os.getenv("CDSE_WMTS_FORMAT", "image/png")
    cdse_wmts_tile_matrix_set: str = os.getenv("CDSE_WMTS_TILE_MATRIX_SET", "PopularWebMercator256")

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1")

    aircraft_detector_model: str = os.getenv("IMAGE_MATE_AIRCRAFT_MODEL", "yolo11n-obb.onnx")
    aircraft_detector_provider: str = os.getenv("IMAGE_MATE_AIRCRAFT_PROVIDER", "auto")
    aircraft_detector_confidence: float = float(os.getenv("IMAGE_MATE_AIRCRAFT_CONFIDENCE", "0.25"))
    aircraft_detector_iou: float = float(os.getenv("IMAGE_MATE_AIRCRAFT_IOU", "0.45"))
    aircraft_detector_max_detections: int = int(os.getenv("IMAGE_MATE_AIRCRAFT_MAX_DETECTIONS", "200"))
    aircraft_detector_window_px: int = int(os.getenv("IMAGE_MATE_AIRCRAFT_WINDOW_PX", "1024"))
    aircraft_detector_window_overlap: float = float(os.getenv("IMAGE_MATE_AIRCRAFT_WINDOW_OVERLAP", "0.20"))
    aircraft_detector_max_image_bytes: int = int(os.getenv("IMAGE_MATE_AIRCRAFT_MAX_IMAGE_BYTES", str(16 * 1024 * 1024)))
    aircraft_detector_max_image_pixels: int = int(os.getenv("IMAGE_MATE_AIRCRAFT_MAX_IMAGE_PIXELS", str(4096 * 4096)))
    aircraft_lab_dir: Path = _rooted_path("IMAGE_MATE_AIRCRAFT_LAB_DIR", ROOT_DIR / "backend" / "output" / "aircraft-lab")
    aircraft_training_dir: Path = _rooted_path("IMAGE_MATE_AIRCRAFT_TRAINING_DIR", ROOT_DIR / "artifacts" / "aircraft-training")
    aircraft_training_python: str = os.getenv("IMAGE_MATE_AIRCRAFT_TRAINING_PYTHON", sys.executable)

    host: str = os.getenv("IMAGE_MATE_HOST", "127.0.0.1")
    port: int = int(os.getenv("IMAGE_MATE_PORT", "8000"))
    cors_origins: list[str] = None  # type: ignore[assignment]
    asset_cache_max_entries: int = int(os.getenv("IMAGE_MATE_ASSET_CACHE_MAX_ENTRIES", "1200"))
    proxy_cache_ttl_seconds: int = int(os.getenv("IMAGE_MATE_PROXY_CACHE_TTL_SECONDS", "1800"))
    proxy_empty_tile_ttl_seconds: int = int(os.getenv("IMAGE_MATE_PROXY_EMPTY_TILE_TTL_SECONDS", "300"))
    proxy_max_asset_bytes: int = int(os.getenv("IMAGE_MATE_PROXY_MAX_ASSET_BYTES", str(64 * 1024 * 1024)))
    proxy_max_zip_bytes: int = int(os.getenv("IMAGE_MATE_PROXY_MAX_ZIP_BYTES", str(512 * 1024 * 1024)))
    proxy_allowed_hosts: list[str] = None  # type: ignore[assignment]
    mosaic_max_output_pixels: int = int(os.getenv("IMAGE_MATE_MOSAIC_MAX_OUTPUT_PIXELS", "500000000"))
    mosaic_max_input_bytes: int = int(os.getenv("IMAGE_MATE_MOSAIC_MAX_INPUT_BYTES", str(512 * 1024 * 1024)))
    mosaic_worker_enabled: bool = _as_bool(os.getenv("IMAGE_MATE_MOSAIC_WORKER_ENABLED", "true"), default=True)
    mosaic_worker_api_base_url: str = os.getenv("IMAGE_MATE_MOSAIC_WORKER_API_BASE_URL", "")
    mosaic_worker_accelerator: str = os.getenv("IMAGE_MATE_MOSAIC_ACCELERATOR", "auto")
    mosaic_worker_python: str = os.getenv("IMAGE_MATE_MOSAIC_WORKER_PYTHON", "")
    mosaic_worker_poll_seconds: float = float(os.getenv("IMAGE_MATE_MOSAIC_WORKER_POLL_SECONDS", "5"))
    mosaic_product_poll_enabled: bool = _as_bool(os.getenv("IMAGE_MATE_MOSAIC_PRODUCT_POLL_ENABLED", "true"), default=True)
    mosaic_product_poll_seconds: int = int(os.getenv("IMAGE_MATE_MOSAIC_PRODUCT_POLL_SECONDS", "300"))

    # Archive-watch delivery. The public base URL is used to build stable
    # Image-Mate links for email; it should be reachable from the recipient's
    # browser when the application is not running only on localhost.
    public_base_url: str = os.getenv("IMAGE_MATE_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    archive_watch_enabled: bool = _as_bool(os.getenv("IMAGE_MATE_ARCHIVE_WATCH_ENABLED", "true"), default=True)
    archive_watch_interval_seconds: int = int(os.getenv("IMAGE_MATE_ARCHIVE_WATCH_INTERVAL_SECONDS", "300"))
    archive_watch_default_lookback_hours: int = int(os.getenv("IMAGE_MATE_ARCHIVE_WATCH_DEFAULT_LOOKBACK_HOURS", "72"))
    alert_email_to: list[str] = None  # type: ignore[assignment]
    smtp_host: str = os.getenv("IMAGE_MATE_SMTP_HOST", "")
    smtp_port: int = int(os.getenv("IMAGE_MATE_SMTP_PORT", "587"))
    smtp_username: str = os.getenv("IMAGE_MATE_SMTP_USERNAME", "")
    smtp_password: str = os.getenv("IMAGE_MATE_SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("IMAGE_MATE_SMTP_FROM", "")
    smtp_use_tls: bool = _as_bool(os.getenv("IMAGE_MATE_SMTP_USE_TLS", "true"), default=True)
    smtp_use_ssl: bool = _as_bool(os.getenv("IMAGE_MATE_SMTP_USE_SSL", "false"), default=False)
    smtp_timeout_seconds: int = int(os.getenv("IMAGE_MATE_SMTP_TIMEOUT_SECONDS", "30"))

    output_dir: Path = ROOT_DIR / "backend" / "output"
    monitoring_db_path: Path = ROOT_DIR / "backend" / "output" / "monitoring.sqlite3"
    frontend_dir: Path = ROOT_DIR / "frontend"

    def __post_init__(self):
        if self.satellogic_satellite_generation_map is None:
            self.satellogic_satellite_generation_map = _json_map(
                os.getenv("SATELLOGIC_SATELLITE_GENERATION_MAP", "{}")
            )
        if self.cors_origins is None:
            self.cors_origins = _split_csv(os.getenv("IMAGE_MATE_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"))
        if self.cdse_sentinel2_collections is None:
            self.cdse_sentinel2_collections = _split_csv(
                os.getenv("CDSE_SENTINEL2_COLLECTIONS", "sentinel-2-l2a,sentinel-2-l1c")
            )
        if self.proxy_allowed_hosts is None:
            self.proxy_allowed_hosts = _split_csv(
                os.getenv(
                    "IMAGE_MATE_PROXY_ALLOWED_HOSTS",
                    "api.satellogic.com,platform.satellogic.com,auth.platform.satellogic.com,"
                    "satellogic-production-eo-backend-catalog.s3.amazonaws.com,"
                    "sh.dataspace.copernicus.eu,catalogue.dataspace.copernicus.eu,"
                    "identity.dataspace.copernicus.eu",
                )
            )
        if self.alert_email_to is None:
            self.alert_email_to = _split_csv(os.getenv("IMAGE_MATE_ALERT_EMAIL_TO", ""))
        self.public_base_url = str(self.public_base_url or "http://127.0.0.1:8000").rstrip("/")
        self.archive_watch_interval_seconds = max(15, int(self.archive_watch_interval_seconds or 300))
        self.archive_watch_default_lookback_hours = max(1, int(self.archive_watch_default_lookback_hours or 72))
        self.mosaic_worker_accelerator = str(self.mosaic_worker_accelerator or "auto").strip().lower()
        if self.mosaic_worker_accelerator not in {"auto", "cpu", "mps", "cuda", "opencl"}:
            self.mosaic_worker_accelerator = "auto"
        self.mosaic_worker_poll_seconds = max(0.5, float(self.mosaic_worker_poll_seconds or 5))
        self.mosaic_product_poll_seconds = max(15, int(self.mosaic_product_poll_seconds or 300))
        if not self.mosaic_worker_api_base_url:
            worker_host = self.host if self.host not in {"0.0.0.0", "::", ""} else "127.0.0.1"
            self.mosaic_worker_api_base_url = f"http://{worker_host}:{self.port}"


settings = Settings()
