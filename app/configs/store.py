from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class StoreConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORE_", env_file=".env", extra="ignore")

    db_path: str = "refund_agent.db"
