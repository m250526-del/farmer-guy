from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.
    All fields are Optional with safe defaults so the app starts without
    any keys present (useful for local dev before secrets are configured).
    """

    model_config = SettingsConfigDict(
        env_file="backend/.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---
    PROJECT_NAME: str = "FarmAI"
    ENVIRONMENT: str = "development"

    # --- Primary Gemini key & models ---
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: Optional[str] = None
    GEMINI_TTS_MODEL: Optional[str] = None

    # --- Rotating chat keys (Stage 2 key-manager) ---
    GEMINI_CHAT_KEY_1: Optional[str] = None
    GEMINI_CHAT_KEY_2: Optional[str] = None
    GEMINI_CHAT_KEY_3: Optional[str] = None

    # --- Rotating STT keys ---
    GEMINI_STT_KEY_1: Optional[str] = None
    GEMINI_STT_KEY_2: Optional[str] = None
    GEMINI_STT_KEY_3: Optional[str] = None

    # --- Rotating TTS keys ---
    GEMINI_TTS_KEY_1: Optional[str] = None
    GEMINI_TTS_KEY_2: Optional[str] = None
    GEMINI_TTS_KEY_3: Optional[str] = None

    # --- External APIs ---
    OPEN_METEO_BASE_URL: str = "https://api.open-meteo.com/v1/forecast"
    N8N_WEBHOOK_BASE_URL: Optional[str] = None

    # --- Gemini request behaviour (Stage 2) ---
    GEMINI_REQUEST_TIMEOUT_SECONDS: int = 30   # Seconds before a Gemini API call times out
    KEY_COOLDOWN_SECONDS: int = 60             # Seconds a rate-limited key is put on cooldown


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance. Call this everywhere instead of
    instantiating Settings directly, so config is read only once."""
    return Settings()

