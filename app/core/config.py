from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Gateway Grok Backend"
    database_url: str = "sqlite:///./storage/gateway_grok.db"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ]
    )
    storage_root: Path = Path("storage")
    profiles_root: Path = Path("storage/profiles")
    browser_headless: bool = True
    default_concurrency: int = 2
    default_timeout_ms: int = 120000
    api_key_header: str = "x-api-key"
    admin_username: str = "admin"
    admin_password: str = "change-me"
    admin_token_secret: str = "change-me-admin-secret"
    admin_token_ttl_seconds: int = 43200
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="GATEWAY_",
        extra="ignore",
    )


settings = Settings()
