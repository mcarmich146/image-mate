from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

try:
    from dotenv import load_dotenv as _load_dotenv_lib
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


def _manual_load_env(env_path: Path) -> bool:
    """Manually parse and load .env file."""
    try:
        text = env_path.read_text(encoding="utf-8")
    except Exception:
        return False
    
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        # Remove quotes
        if value and len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
    return True


def _find_and_load_env() -> Path | None:
    """Find .env file in various locations and load it."""
    candidates = [
        # Explicit path override
        Path(os.getenv("IMAGE_MATE_ENV_PATH", "")).expanduser() if os.getenv("IMAGE_MATE_ENV_PATH") else None,
        # Current directory
        Path.cwd() / ".env",
        # User home variants
        Path.home() / ".image-mate" / ".env",
        Path.home() / ".env",
        # Common development locations
        Path.home() / "Documents" / "Personal" / "dev" / "image-mate" / ".env",
        Path.home() / "dev" / "image-mate" / ".env",
        Path.home() / "code" / "image-mate" / ".env",
        Path.home() / "projects" / "image-mate" / ".env",
    ]
    
    # Try to find image-mate root if available
    plugin_dir = Path(__file__).resolve().parent.parent
    candidates.extend([
        plugin_dir.parent.parent / ".env",  # If in qgis_plugin subfolder during dev
        plugin_dir / ".env",  # Next to plugin
    ])
    
    # Try each candidate
    for candidate in candidates:
        if candidate is None or not candidate.exists():
            continue
        
        # Try dotenv first, fall back to manual parsing
        try:
            if HAS_DOTENV:
                _load_dotenv_lib(candidate, override=False)
            else:
                _manual_load_env(candidate)
            return candidate
        except Exception:
            # If one method fails, try manual parsing
            try:
                _manual_load_env(candidate)
                return candidate
            except Exception:
                continue
    
    return None


# Load .env file on module import
env_file = _find_and_load_env()


def get_config_diagnostics() -> dict:
    """Get diagnostic information about configuration loading."""
    import os
    return {
        "env_file_loaded": str(env_file) if env_file else None,
        "env_file_exists": env_file.exists() if env_file else False,
        "has_dotenv": HAS_DOTENV,
        "bearer_token_in_env": bool(os.getenv("SATELLOGIC_BEARER_TOKEN", "").strip()),
        "key_id_in_env": bool(os.getenv("SATELLOGIC_KEY_ID", "").strip()),
        "key_secret_in_env": bool(os.getenv("SATELLOGIC_KEY_SECRET", "").strip()),
        "bearer_token_in_settings": bool(settings.satellogic_bearer_token.strip()),
        "key_id_in_settings": bool(settings.satellogic_key_id.strip()),
        "key_secret_in_settings": bool(settings.satellogic_key_secret.strip()),
    }


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

    # Plugin-specific paths (not used in QGIS context, but kept for compatibility)
    output_dir: Path = Path.home() / ".image-mate" / "output"
    monitoring_db_path: Path = Path.home() / ".image-mate" / "output" / "monitoring.sqlite3"
    frontend_dir: Path = Path.home() / ".image-mate" / "frontend"

    def __post_init__(self):
        if self.cors_origins is None:
            self.cors_origins = _split_csv(os.getenv("IMAGE_MATE_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"))
        if self.cdse_sentinel2_collections is None:
            self.cdse_sentinel2_collections = _split_csv(
                os.getenv("CDSE_SENTINEL2_COLLECTIONS", "sentinel-2-l2a,sentinel-2-l1c")
            )


settings = Settings()
