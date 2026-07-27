from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class LimitsConfig(BaseSettings):
    """Bounds on what one visitor can spend. The demo is a public URL in front of a
    paid model, so a single request is capped and every client gets a budget."""

    model_config = SettingsConfigDict(env_prefix="LIMITS_", env_file=".env", extra="ignore")

    max_message_chars: int = 2_000
    max_turns_per_thread: int = 20
    requests_per_hour: int = 20
    burst: int = 8
    max_tracked_clients: int = 10_000
