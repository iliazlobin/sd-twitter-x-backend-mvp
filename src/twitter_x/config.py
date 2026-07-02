from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/twitter_x"
    redis_url: str = "redis://localhost:6379/0"
    app_port: int = 8000
    app_host: str = "0.0.0.0"


settings = Settings()
