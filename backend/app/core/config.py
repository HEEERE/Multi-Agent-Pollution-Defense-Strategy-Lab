import os
from functools import lru_cache

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    majd_api_key: str = Field(default="", validation_alias="MAJD_API_KEY")
    auth_session_ttl_seconds: int = Field(
        default=28800,
        ge=300,
        le=604800,
        validation_alias="AUTH_SESSION_TTL_SECONDS",
    )
    mimo_api_key: str = Field(default="", validation_alias="MIMO_API_KEY")
    mimo_base_url: HttpUrl = Field(
        default="https://token-plan-cn.xiaomimimo.com/v1",
        validation_alias="MIMO_BASE_URL",
    )
    mimo_model: str = Field(default="mimo-v2.5-pro", validation_alias="MIMO_MODEL")
    llm_request_timeout_seconds: float = Field(default=45, validation_alias="LLM_REQUEST_TIMEOUT_SECONDS")
    llm_max_tokens: int = Field(default=700, validation_alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(default=0.2, validation_alias="LLM_TEMPERATURE")
    llm_enabled: bool = Field(default=False, validation_alias="LLM_ENABLED")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def llm_ready(self) -> bool:
        return self.llm_enabled and bool(self.mimo_api_key)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.majd_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_cors_origins() -> list[str]:
    from app.settings_manager import get_settings_manager
    mgr = get_settings_manager()
    origins_str = mgr.get_value_sync("system", "system.cors_allowed_origins", None)
    if origins_str and isinstance(origins_str, str) and origins_str.strip():
        return [o.strip() for o in origins_str.split(",") if o.strip()]
    env_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    if env_origins:
        return [o.strip() for o in env_origins.split(",") if o.strip()]
    return []
