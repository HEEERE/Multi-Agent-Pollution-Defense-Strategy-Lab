from functools import lru_cache

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mimo_api_key: str = Field(default="", validation_alias="MIMO_API_KEY")
    mimo_base_url: HttpUrl = Field(
        default="https://token-plan-cn.xiaomimimo.com/v1",
        validation_alias="MIMO_BASE_URL",
    )
    mimo_model: str = Field(default="MiMo-V2.5-Pro", validation_alias="MIMO_MODEL")
    llm_request_timeout_seconds: float = Field(default=45, validation_alias="LLM_REQUEST_TIMEOUT_SECONDS")
    llm_max_tokens: int = Field(default=700, validation_alias="LLM_MAX_TOKENS")
    llm_temperature: float = Field(default=0.2, validation_alias="LLM_TEMPERATURE")
    llm_enabled: bool = Field(default=False, validation_alias="LLM_ENABLED")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def llm_ready(self) -> bool:
        return self.llm_enabled and bool(self.mimo_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
