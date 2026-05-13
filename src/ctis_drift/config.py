"""Application configuration (environment-driven)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Runtime settings loaded from environment and optional `.env` file."""

    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    log_level: LogLevel = Field(default="INFO", validation_alias="CTIS_DRIFT_LOG_LEVEL")
    api_base_url: str = Field(
        default="https://euclinicaltrials.eu/ctis-public-api",
        validation_alias="CTIS_API_BASE_URL",
    )
    api_timeout_seconds: float = Field(default=30.0, validation_alias="CTIS_API_TIMEOUT_SECONDS")
    api_token: str | None = Field(default=None, validation_alias="CTIS_API_TOKEN")
    database_url: str = Field(
        default="sqlite:///data/ctis_drift.db",
        validation_alias="CTIS_DRIFT_DATABASE_URL",
    )
    enable_mock_api: bool = Field(default=False, validation_alias="CTIS_DRIFT_ENABLE_MOCK_API")

    @field_validator("api_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("api_timeout_seconds")
    @classmethod
    def positive_timeout(cls, value: float) -> float:
        if value <= 0:
            msg = "api_timeout_seconds must be > 0"
            raise ValueError(msg)
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached `Settings` instance (safe for repeated calls)."""
    return Settings()
