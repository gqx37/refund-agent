"""The demo is a public URL in front of a paid model, so the limits are load-bearing.
Time is injected rather than slept, so the refill behaviour is actually asserted."""

from __future__ import annotations

from app.configs import LimitsConfig
from app.limits import Limits, RateLimiter, TurnCounter, client_key

CFG = LimitsConfig(
    max_message_chars=100,
    max_turns_per_thread=3,
    requests_per_hour=3600,  # one token per second, so the maths is readable
    burst=2,
    max_tracked_clients=4,
)


def test_bucket_allows_the_burst_then_refuses():
    bucket = RateLimiter(capacity=2, per_hour=3600, max_keys=10)
    assert bucket.take("a", now=0.0) is None
    assert bucket.take("a", now=0.0) is None
    assert bucket.take("a", now=0.0) == 1


def test_bucket_refills_over_time():
    bucket = RateLimiter(capacity=2, per_hour=3600, max_keys=10)
    bucket.take("a", now=0.0)
    bucket.take("a", now=0.0)
    assert bucket.take("a", now=0.5) == 1, "half a token is not enough"
    assert bucket.take("a", now=1.0) is None, "one second buys one token"


def test_buckets_are_per_client():
    bucket = RateLimiter(capacity=1, per_hour=3600, max_keys=10)
    assert bucket.take("a", now=0.0) is None
    assert bucket.take("b", now=0.0) is None, "b must not pay for a"
    assert bucket.take("a", now=0.0) is not None


def test_bucket_map_stays_bounded_under_unique_clients():
    bucket = RateLimiter(capacity=1, per_hour=3600, max_keys=4)
    for i in range(50):
        bucket.take(f"client-{i}", now=float(i))
    assert len(bucket._buckets) <= 4


def test_turns_are_capped_per_thread():
    turns = TurnCounter(limit=2, max_keys=10)
    assert turns.spend("t1") is True
    assert turns.spend("t1") is True
    assert turns.spend("t1") is False
    assert turns.spend("t2") is True, "a fresh thread starts clean"


def test_long_message_is_refused_before_anything_is_spent():
    limits = Limits(CFG)
    rejected = limits.check(client="ip", thread_id="t", message="x" * 101)
    assert rejected is not None and rejected.status == 413
    # The oversized attempt must not have cost the caller a token.
    assert limits.check(client="ip", thread_id="t", message="hi") is None


def test_rate_limit_reports_a_retry_after():
    limits = Limits(CFG)
    for _ in range(CFG.burst):
        assert limits.check(client="ip", thread_id="t", message="hi", now=0.0) is None
    rejected = limits.check(client="ip", thread_id="t", message="hi", now=0.0)
    assert rejected is not None
    assert rejected.status == 429
    assert rejected.retry_after and rejected.retry_after >= 1


def test_thread_turn_cap_is_enforced():
    limits = Limits(LimitsConfig(max_turns_per_thread=2, requests_per_hour=3600, burst=100))
    assert limits.check(client="ip", thread_id="t", message="hi", now=0.0) is None
    assert limits.check(client="ip", thread_id="t", message="hi", now=0.0) is None
    rejected = limits.check(client="ip", thread_id="t", message="hi", now=0.0)
    assert rejected is not None and rejected.status == 429
    assert limits.check(client="ip", thread_id="other", message="hi", now=0.0) is None


def test_client_key_prefers_the_proxy_headers():
    assert client_key({"fly-client-ip": "1.1.1.1"}, "10.0.0.1") == "1.1.1.1"
    assert client_key({"x-forwarded-for": "2.2.2.2, 10.0.0.1"}, "10.0.0.1") == "2.2.2.2"
    assert client_key({}, "10.0.0.1") == "10.0.0.1"
    assert client_key({}, None) == "unknown"
