from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
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

    host: str = os.getenv("IMAGE_MATE_HOST", "0.0.0.0")
    port: int = int(os.getenv("IMAGE_MATE_PORT", "8000"))
    cors_origins: list[str] = None  # type: ignore[assignment]
    asset_cache_max_entries: int = int(os.getenv("IMAGE_MATE_ASSET_CACHE_MAX_ENTRIES", "1200"))
    proxy_cache_ttl_seconds: int = int(os.getenv("IMAGE_MATE_PROXY_CACHE_TTL_SECONDS", "1800"))
    proxy_empty_tile_ttl_seconds: int = int(os.getenv("IMAGE_MATE_PROXY_EMPTY_TILE_TTL_SECONDS", "300"))

    output_dir: Path = ROOT_DIR / "backend" / "output"
    monitoring_db_path: Path = ROOT_DIR / "backend" / "output" / "monitoring.sqlite3"
    frontend_dir: Path = ROOT_DIR / "frontend"

    def __post_init__(self):
        if self.cors_origins is None:
            self.cors_origins = _split_csv(os.getenv("IMAGE_MATE_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"))
        if self.cdse_sentinel2_collections is None:
            self.cdse_sentinel2_collections = _split_csv(
                os.getenv("CDSE_SENTINEL2_COLLECTIONS", "sentinel-2-l2a,sentinel-2-l1c")
            )


settings = Settings()
