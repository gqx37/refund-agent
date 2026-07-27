from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseSettings):
    """The reasoning model, on Fireworks. Kimi K2.6 — strong at agentic tool use.
    temperature 0: the model reasons and phrases; the guardrail decides."""

    model_config = SettingsConfigDict(env_prefix="FIREWORKS_", env_file=".env", extra="ignore")

    api_key: str = Field(..., description="FIREWORKS_API_KEY.")
    model: str = "accounts/fireworks/models/kimi-k2p6"
    temperature: float = 0.0
    # A refund reply is a few sentences. Capping output bounds what one turn can
    # cost, and a model that wants more than this has lost the plot anyway.
    max_tokens: int = 1024
