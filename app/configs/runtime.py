from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 8080
    env: str = "development"

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache
def runtime_config() -> RuntimeConfig:
    return RuntimeConfig()
