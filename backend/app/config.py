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


@dataclass
class Settings:
    satellogic_bearer_token: str = os.getenv("SATELLOGIC_BEARER_TOKEN", "")
    satellogic_key_id: str = os.getenv("SATELLOGIC_KEY_ID", "")
    satellogic_key_secret: str = os.getenv("SATELLOGIC_KEY_SECRET", "")
    satellogic_contract_id: str = os.getenv("SATELLOGIC_CONTRACT_ID", "")
    satellogic_collection_id: str = os.getenv("SATELLOGIC_COLLECTION_ID", "l1d-sr")
    satellogic_stac_url: str = os.getenv("SATELLOGIC_STAC_URL", "https://api.satellogic.com/archive/stac")
    satellogic_token_url: str = os.getenv("SATELLOGIC_TOKEN_URL", "https://auth.platform.satellogic.com/oauth/token")

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1")

    host: str = os.getenv("IMAGE_MATE_HOST", "0.0.0.0")
    port: int = int(os.getenv("IMAGE_MATE_PORT", "8000"))
    cors_origins: list[str] = None  # type: ignore[assignment]

    annotations_file: Path = ROOT_DIR / "backend" / "data" / "annotations.json"
    output_dir: Path = ROOT_DIR / "backend" / "output"
    frontend_dir: Path = ROOT_DIR / "frontend"

    def __post_init__(self):
        if self.cors_origins is None:
            self.cors_origins = _split_csv(os.getenv("IMAGE_MATE_CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"))


settings = Settings()
