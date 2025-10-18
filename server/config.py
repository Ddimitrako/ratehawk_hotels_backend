"""Configuration models for the FastAPI service."""
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

# Support both Pydantic v1 and v2 (where BaseSettings moved to pydantic-settings)
try:  # Preferred for Pydantic v2
    from pydantic_settings import BaseSettings  # type: ignore
except Exception:  # pragma: no cover - fallback for Pydantic v1
    try:
        from pydantic import BaseSettings  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise ImportError(
            "Install 'pydantic-settings' for Pydantic v2: pip install pydantic-settings"
        ) from exc

from pydantic import Field, SecretStr, validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    papi_auth_key: Optional[SecretStr] = Field(
        None,
        description="Combined `<key_id>:<api_key>` credential pair.",
        env="PAPI_AUTH_KEY",
    )
    papi_key_id: Optional[str] = Field(
        None,
        description="Public identifier of the API key.",
        env="PAPI_KEY_ID",
    )
    papi_key: Optional[SecretStr] = Field(
        None,
        description="Secret token of the API key.",
        env="PAPI_KEY",
    )
    default_language: str = Field("en", env="PAPI_DEFAULT_LANGUAGE")
    default_currency: str = Field("EUR", env="PAPI_DEFAULT_CURRENCY")
    default_residency: Optional[str] = Field(
        None,
        env="PAPI_DEFAULT_RESIDENCY",
        description="Default residency code passed to the PAPI search endpoints.",
    )
    request_timeout: int = Field(
        30,
        env="PAPI_TIMEOUT_SECONDS",
        description="HTTP timeout (seconds) for outgoing requests to RateHawk APIs.",
    )
    info_budget: int = Field(
        25,
        env="PAPI_INFO_BUDGET",
        description="Max Hotel Info calls per search to avoid upstream rate limits.",
    )
    base_path: Optional[str] = Field(
        None,
        env="PAPI_BASE_PATH",
        description="Optional override for the RateHawk API base URL (e.g. sandbox host).",
    )
    frontend_origin: str = Field(
        "http://localhost:3000",
        env="FRONTEND_ORIGIN",
        description="Origin allowed for browser requests (CORS).",
    )
    hotel_cache_path: Optional[str] = Field(
        None,
        env="PAPI_HOTEL_CACHE_PATH",
        description="Optional path to a SQLite file for persisting Hotel Info cache.",
    )

    class Config:
        env_file = Path(__file__).resolve().parent.parent / ".env"
        env_file_encoding = "utf-8"

    @validator("request_timeout")
    def _validate_timeout(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("request_timeout must be positive")
        return value

    @validator("info_budget")
    def _validate_info_budget(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("info_budget must be positive")
        return value

    def auth_tuple(self) -> Tuple[str, str]:
        """Return the key id and secret in a tuple, validating configuration."""

        if self.papi_auth_key:
            try:
                key_id, key = self.papi_auth_key.get_secret_value().split(":", 1)
                return key_id, key
            except ValueError as exc:  # pragma: no cover - defensive programming
                raise ValueError("PAPI_AUTH_KEY must contain `<key_id>:<api_key>`.") from exc

        if self.papi_key_id and self.papi_key:
            return self.papi_key_id, self.papi_key.get_secret_value()

        raise ValueError("PAPI credentials are not configured. Set PAPI_AUTH_KEY or PAPI_KEY_ID/PAPI_KEY.")

    def auth_header(self) -> str:
        """Return the combined `<key_id>:<api_key>` representation."""

        key_id, key = self.auth_tuple()
        return f"{key_id}:{key}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
