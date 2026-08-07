# Spend controls for the public demo. Three bounds, all cheap and all in-process:
# a token bucket per client, a cap on message size, and a cap on turns per thread
# (each turn re-sends the whole history, so a thread nobody stops gets more
# expensive every time it is used).
#
# The buckets live in this process because the service is one machine. The
# algorithm is the one you'd put in Redis if it were more than one.

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

from app.configs import LimitsConfig


@dataclass(frozen=True)
class Rejection:
    """Why a request was refused, as data — main.py turns it into a response."""

    status: int
    message: str
    retry_after: Optional[int] = None


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    """A token bucket per key. Buckets hold `capacity` tokens and refill at
    `per_hour`, so a visitor can burst through the example prompts and then
    settles to the sustained rate."""

    def __init__(self, *, capacity: int, per_hour: int, max_keys: int) -> None:
        self._capacity = float(capacity)
        self._refill = per_hour / 3600.0
        self._max_keys = max_keys
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()

    def take(self, key: str, *, now: Optional[float] = None) -> Optional[int]:
        """Spend a token. None if allowed, else the seconds until the next one."""
        now = time.monotonic() if now is None else now
        bucket = self._buckets.get(key)
        if bucket is None:
            self._evict(now)
            bucket = _Bucket(tokens=self._capacity, updated=now)
        else:
            refilled = bucket.tokens + (now - bucket.updated) * self._refill
            bucket.tokens, bucket.updated = min(self._capacity, refilled), now
        self._buckets[key] = bucket
        self._buckets.move_to_end(key)

        if bucket.tokens < 1.0:
            return max(1, round((1.0 - bucket.tokens) / self._refill))
        bucket.tokens -= 1.0
        return None

    def _evict(self, now: float) -> None:
        """Keep the map bounded: a flood of unique IPs must not grow it forever.
        Buckets that have refilled to full are dropped first — a full bucket is
        indistinguishable from a client we've never seen, so forgetting one costs
        nothing. If that isn't enough, drop least-recently-seen."""
        if len(self._buckets) < self._max_keys:
            return
        for key, bucket in list(self._buckets.items()):
            if bucket.tokens + (now - bucket.updated) * self._refill >= self._capacity:
                del self._buckets[key]
        while len(self._buckets) >= self._max_keys:
            self._buckets.popitem(last=False)


class TurnCounter:
    """Turns spent per thread, least-recently-used out when the map is full."""

    def __init__(self, *, limit: int, max_keys: int) -> None:
        self._limit = limit
        self._max_keys = max_keys
        self._turns: OrderedDict[str, int] = OrderedDict()

    def spend(self, thread_id: str) -> bool:
        spent = self._turns.get(thread_id, 0)
        if spent >= self._limit:
            return False
        while len(self._turns) >= self._max_keys and thread_id not in self._turns:
            self._turns.popitem(last=False)
        self._turns[thread_id] = spent + 1
        self._turns.move_to_end(thread_id)
        return True


class Limits:
    def __init__(self, cfg: Optional[LimitsConfig] = None) -> None:
        self._cfg = cfg or LimitsConfig()
        self._clients = RateLimiter(
            capacity=self._cfg.burst,
            per_hour=self._cfg.requests_per_hour,
            max_keys=self._cfg.max_tracked_clients,
        )
        self._threads = TurnCounter(
            limit=self._cfg.max_turns_per_thread,
            max_keys=self._cfg.max_tracked_clients,
        )

    def check(
        self,
        *,
        client: str,
        thread_id: str,
        message: str = "",
        now: Optional[float] = None,
    ) -> Optional[Rejection]:
        """Cheapest check first, and nothing is spent before the free ones pass."""
        if len(message) > self._cfg.max_message_chars:
            return Rejection(
                status=413,
                message=f"That message is too long. Keep it under {self._cfg.max_message_chars} characters.",
            )
        wait = self._clients.take(client, now=now)
        if wait is not None:
            return Rejection(
                status=429,
                message="You've hit the demo's rate limit. Give it a few minutes and try again.",
                retry_after=wait,
            )
        if not self._threads.spend(thread_id):
            return Rejection(
                status=429,
                message=f"This conversation hit its {self._cfg.max_turns_per_thread}-turn limit. Start a new chat to keep going.",
            )
        return None


def client_key(
    headers: Mapping[str, str],
    peer: Optional[str],
    *,
    trusted_proxy: bool = False,
    forwarded_header: str = "x-demo-client-ip",
) -> str:
    """Who to bill this request to.

    Fly terminates TLS and forwards the caller's address, so the socket peer is
    the edge. Trust Fly-Client-IP, then the first hop of X-Forwarded-For.

    When the UI proxies through its own server, all three of those become the
    *proxy's* address — every visitor on earth would collapse into one bucket and
    the demo would rate-limit itself into a brick. So a proxied request carries
    the real client address in its own header, which we believe only because
    `trusted_proxy` means the shared secret authenticated the hop that set it.
    An unauthenticated caller can set the same header and it is ignored.
    """
    if trusted_proxy:
        proxied = headers.get(forwarded_header, "").split(",")[0].strip()
        if proxied:
            return proxied
    forwarded = headers.get("x-forwarded-for", "").split(",")[0].strip()
    return headers.get("fly-client-ip") or forwarded or peer or "unknown"
