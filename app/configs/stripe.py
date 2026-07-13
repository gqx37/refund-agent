from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StripeConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STRIPE_", env_file=".env", extra="ignore")

    api_key: str = Field(..., description="Stripe secret (restricted) key.")
    api_base: str = "https://api.stripe.com"
    # Pin the version so a Stripe-side upgrade can't reshape responses on their
    # schedule instead of ours. Blank => account default.
    api_version: Optional[str] = None
    timeout_seconds: float = 30.0
