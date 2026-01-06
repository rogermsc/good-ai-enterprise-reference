"""
Configuration management using pydantic-settings.

Loads configuration from environment variables with sensible defaults
for development and production environments.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Environment
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/goodai"
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # LLM Configuration
    llm_provider: Literal["openai", "azure", "mock"] = "mock"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    model_name: str = "gpt-4"
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 3

    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = ""

    # Security
    cors_origins: list[str] = ["*"]
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    rate_limit_burst: int = 20

    # Redis (for rate limiting and caching)
    redis_url: str = "redis://localhost:6379"

    # JWT Authentication
    jwt_secret_key: str | None = None  # Required for production
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Observability
    otlp_endpoint: str | None = None  # e.g., "http://localhost:4317"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    enable_tracing: bool = True

    # Policy Configuration
    # Policy preset: default, lgpd-br, gdpr-eu, lopd-ec
    policy_preset: str = "default"
    # Path to custom policy config directory (optional)
    policy_config_dir: Path | None = None

    # PII Pattern Configuration
    # Pattern sets to load: default, brazil, ecuador, europe, latam
    # Can be comma-separated for multiple: "default,brazil"
    pii_pattern_sets: str = "default"
    # Path to custom PII pattern config directory (optional)
    pii_pattern_config_dir: Path | None = None

    @property
    def is_mock_mode(self) -> bool:
        """Check if running in mock mode (no real LLM calls)."""
        return self.llm_provider == "mock" or self.openai_api_key is None

    @property
    def async_database_url(self) -> str:
        """Convert database URL to async format."""
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://")
        return self.database_url

    @property
    def pii_pattern_sets_list(self) -> list[str]:
        """Get PII pattern sets as a list."""
        return [s.strip() for s in self.pii_pattern_sets.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
