# Typed config, read from the environment once and passed explicitly. Tests build
# these directly against stubs, so no environment is required to run them.

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StripeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STRIPE_", env_file=".env", extra="ignore")

    api_key: str = Field(..., description="Stripe secret (restricted) key.")
    api_base: str = Field("https://api.stripe.com")
    # Pin the version so a Stripe-side upgrade can't reshape responses on their
    # schedule instead of ours. Blank => account default.
    api_version: Optional[str] = None
    timeout_seconds: float = 30.0


class Neo4jConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEO4J_", env_file=".env", extra="ignore")

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = Field(..., description="NEO4J_PASSWORD.")
    database: str = "neo4j"


class LLMConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIREWORKS_", env_file=".env", extra="ignore")

    api_key: str = Field(..., description="FIREWORKS_API_KEY.")
    model: str = "accounts/fireworks/models/nemotron-3-ultra-nvfp4"
    temperature: float = 0.0


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 8080
    env: str = "development"

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache
def app_config() -> AppConfig:
    return AppConfig()
