from __future__ import annotations

from functools import lru_cache
from typing import Optional

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


class ProxyConfig(BaseSettings):
    """The other bound on the demo: who may reach /v1 at all.

    The UI is served from Vercel and never talks to this service directly; its
    Route Handler holds the secret and forwards. That makes the public Fly URL
    inert on its own, so the demo cannot be scripted around the UI.

    Unset means the gate is open, which is what you want running locally.
    """

    model_config = SettingsConfigDict(env_prefix="PROXY_", env_file=".env", extra="ignore")

    shared_secret: Optional[str] = None

    # The proxy is the only hop that may claim who the caller is. See client_key.
    client_ip_header: str = "x-demo-client-ip"


@lru_cache
def proxy_config() -> ProxyConfig:
    return ProxyConfig()
