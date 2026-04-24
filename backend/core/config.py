from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FBV1_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "FBV1 Backend"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8010
    log_level: str = "INFO"
    database_url: str = "sqlite:///./backend/data/fbv1.db"
    max_workers: int = 5
    default_job_delay_seconds: float = 0.2
    frontend_origin: str = "http://127.0.0.1:3000"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
