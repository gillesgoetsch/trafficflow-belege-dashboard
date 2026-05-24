"""Centralized settings via pydantic-settings.

Single source of truth for all env-driven configuration. Import `settings`
everywhere instead of reading os.environ directly.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_env: str = "development"
    app_name: str = "Belege-Hub"
    app_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    # Secrets
    secret_key: str = "dev-secret-change-me"
    encryption_key: str = "dev-fernet-key-must-be-32-url-safe-bytes-base64=="
    access_token_minutes: int = 60 * 24 * 7  # 7 days

    # Admin bootstrap
    admin_email: EmailStr = "admin@example.com"
    admin_password: str = "change-me"

    # Database
    database_url: str = "postgresql+psycopg://belege:belege@localhost:5432/belege"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Anthropic
    anthropic_api_key: str = ""
    classifier_model: str = "claude-haiku-4-5-20251001"
    ocr_model: str = "claude-sonnet-4-6"

    # IMAP
    imap_batch_interval_minutes: int = 30

    # Storage
    storage_path: Path = Path("/data/receipts")

    # OneDrive
    onedrive_client_id: str = ""
    onedrive_client_secret: str = ""
    onedrive_redirect_uri: str = ""

    # Inbound cloud folders
    ms_client_id: str = ""           # for OneDrive share connector (app-only)
    ms_client_secret: str = ""
    ms_tenant_id: str = "common"
    google_api_key: str = ""         # for Google Drive share connector

    # Deploy webhook
    deploy_webhook_secret: str = "change-me-webhook-secret"
    deploy_branch: str = "main"
    deploy_repo_path: str = "/srv/belege"

    # Backups
    backup_s3_endpoint: str = ""
    backup_s3_bucket: str = ""
    backup_s3_key: str = ""
    backup_s3_secret: str = ""
    backup_s3_region: str = "auto"

    # Domain/Caddy
    domain: str = "localhost"
    acme_email: EmailStr = "admin@example.com"

    # Limits
    max_upload_mb: int = 25

    @property
    def is_prod(self) -> bool:
        return self.app_env == "production"

    @property
    def async_database_url(self) -> str:
        """psycopg's async dialect (sqlalchemy[asyncio])."""
        # psycopg 3 supports both sync and async with the same +psycopg dialect.
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
