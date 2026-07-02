from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://twitter_x:twitter_x@db:5432/twitter_x"
    redis_url: str = "redis://redis:6379/0"
    app_port: int = 8000


settings = Settings()
