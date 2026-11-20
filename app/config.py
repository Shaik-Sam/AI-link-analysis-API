from functools import lru_cache
from typing import Literal, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["anthropic", "openai", "gemini"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: Provider = "anthropic"
    llm_model: str = "claude-haiku-5-5"
    fallback_provider: Optional[Provider] = "openai"
    fallback_model: Optional[str] = "gpt-6-luna"

    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None

    llm_timeout_seconds: float = 90.0
    llm_max_output_tokens: int = 4096

    fetch_timeout_seconds: float = 15.0
    max_response_bytes: int = 3_000_000
    max_redirects: int = 5
    max_extra_pages: int = 2
    max_content_chars: int = 12000

    cache_ttl_seconds: int = 3600
    cache_max_entries: int = 256
    log_level: str = "INFO"

    @field_validator(
        "fallback_provider",
        "fallback_model",
        "anthropic_api_key",
        "openai_api_key",
        "gemini_api_key",
        mode="before",
    )
    @classmethod
    def empty_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def api_key_for(self, provider: str) -> Optional[str]:
        return {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
        }.get(provider)


@lru_cache
def get_settings() -> Settings:
    return Settings()
