# app/config.py

"""Typed, fail-fast configuration.

Every setting is read from the environment once, validated by Pydantic, and
passed explicitly to the components that need it. Nothing reaches for os.environ
at call time, so the same objects drive the app, the CLI, and the tests (where
they're constructed directly against stubs, no environment required).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StripeConfig(BaseSettings):
    """Credentials + version pin for the Stripe REST API."""

    model_config = SettingsConfigDict(env_prefix="STRIPE_", env_file=".env", extra="ignore")

    api_key: str = Field(..., description="Stripe secret (restricted) key: sk_… / rk_…")
    api_base: str = Field(
        "https://api.stripe.com",
        description="Stripe API host. Overridable so tests can point at a stub.",
    )
    # Pinning the version is a deliberate reliability choice: a Stripe-side API
    # upgrade renames params and reshapes objects, and an unpinned client would
    # silently inherit that on their release schedule, not ours. Blank => account
    # default (fine for a first run; pin before production).
    api_version: Optional[str] = Field(
        None, description="Value for the Stripe-Version header, e.g. 2026-07-29."
    )
    timeout_seconds: float = Field(30.0, description="Per-request HTTP timeout.")


class Neo4jConfig(BaseSettings):
    """Connection to the semantic fact store."""

    model_config = SettingsConfigDict(env_prefix="NEO4J_", env_file=".env", extra="ignore")

    uri: str = Field("bolt://localhost:7687", description="Bolt URI of the Neo4j instance.")
    username: str = Field("neo4j")
    password: str = Field(..., description="Neo4j password (NEO4J_PASSWORD).")
    database: str = Field("neo4j")


class LLMConfig(BaseSettings):
    """Fireworks-hosted Nemotron 3 Ultra — the reasoning core of the harness."""

    model_config = SettingsConfigDict(env_prefix="FIREWORKS_", env_file=".env", extra="ignore")

    api_key: str = Field(..., description="Fireworks API key (FIREWORKS_API_KEY).")
    model: str = Field(
        "accounts/fireworks/models/nemotron-3-ultra-nvfp4",
        description="Fireworks model slug. Pinned; override to swap models.",
    )
    temperature: float = Field(
        0.0,
        description="0.0: the LLM extracts and phrases, it does not decide policy. "
        "Determinism belongs to the code, so we don't buy variance we can't use.",
    )


class AppConfig(BaseSettings):
    """Service-level settings not tied to a single integration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = Field(8080, description="HTTP port the FastAPI app binds to.")
    env: str = Field("development", description="'development' or 'production'.")

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"


@lru_cache
def app_config() -> AppConfig:
    return AppConfig()
