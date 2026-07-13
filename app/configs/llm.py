from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseSettings):
    """Nemotron 3 Ultra on Fireworks. temperature 0: the model extracts and phrases,
    it does not decide, so there's no variance worth buying."""

    model_config = SettingsConfigDict(env_prefix="FIREWORKS_", env_file=".env", extra="ignore")

    api_key: str = Field(..., description="FIREWORKS_API_KEY.")
    model: str = "accounts/fireworks/models/nemotron-3-ultra-nvfp4"
    temperature: float = 0.0
