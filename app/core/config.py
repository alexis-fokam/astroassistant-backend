from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AV_", extra="ignore")

    app_name: str = "Astro Assistant API"
    version: str = "0.1.0"
    debug: bool = False

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'astrovitals.db'}"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Intervalle du pipeline IA (secondes) — cahier des charges §8.1
    pipeline_interval_seconds: int = 5
    # Run the risk engine in the background (disabled in tests).
    pipeline_enabled: bool = True

    # Signing key of the session tokens issued after PIN login (spec §7). Override in .env.
    secret_key: str = "dev-only-change-me"
    token_ttl_hours: int = 12

    # NASA open APIs (DONKI). DEMO_KEY works but is rate limited; get a free key at api.nasa.gov.
    nasa_api_key: str = "DEMO_KEY"


@lru_cache
def get_settings() -> Settings:
    return Settings()
