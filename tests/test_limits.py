"""The demo is a public URL in front of a paid model, so the limits are load-bearing.
Time is injected rather than slept, so the refill behaviour is actually asserted.

The /v1 gate is here too: it is the outermost bound on the same thing, and the
rate limiter can only bill the right visitor when the gate says the hop was real.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main
from app.configs import LimitsConfig, ProxyConfig
from app.limits import Limits, RateLimiter, TurnCounter, client_key
from app.main import require_proxy

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


def test_forwarded_client_ip_is_ignored_unless_the_hop_was_authenticated():
    """Anyone can set the header; only the shared secret makes it mean anything."""
    headers = {"x-demo-client-ip": "9.9.9.9", "fly-client-ip": "1.1.1.1"}
    assert client_key(headers, "10.0.0.1") == "1.1.1.1"
    assert client_key(headers, "10.0.0.1", trusted_proxy=True) == "9.9.9.9"


def test_proxied_visitors_do_not_share_one_bucket():
    """The regression the forwarded header exists to prevent: behind a proxy every
    request arrives from the same address, so without it one visitor exhausting the
    bucket would lock out everyone else."""
    limits = Limits(LimitsConfig(requests_per_hour=3600, burst=1, max_turns_per_thread=99))
    proxy_peer = "10.0.0.1"

    def visit(ip: str) -> object:
        key = client_key(
            {"x-demo-client-ip": ip, "fly-client-ip": proxy_peer},
            proxy_peer,
            trusted_proxy=True,
        )
        return limits.check(client=key, thread_id=f"t-{ip}", message="hi", now=0.0)

    assert visit("9.9.9.9") is None
    assert visit("9.9.9.9") is not None, "the same visitor still burns their own budget"
    assert visit("8.8.8.8") is None, "a different visitor must not pay for them"


def test_client_key_falls_back_when_the_proxy_forwards_nothing():
    assert client_key({"fly-client-ip": "1.1.1.1"}, "10.0.0.1", trusted_proxy=True) == "1.1.1.1"
    assert client_key({}, "10.0.0.1", trusted_proxy=True) == "10.0.0.1"


# --- the /v1 gate -----------------------------------------------------------
#
# The config is injected rather than read from the environment, so these run the
# same way on a laptop with a .env sitting next to them and in CI without one.

SECRET = "s3cret-token"


def make_request(**headers: str) -> Request:
    encoded = [(k.replace("_", "-").lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": "/v1/stream", "headers": encoded})


@pytest.fixture
def gated(monkeypatch):
    """The gate armed with a secret."""
    monkeypatch.setattr(main, "proxy_config", lambda: ProxyConfig(shared_secret=SECRET))


def test_the_right_bearer_token_is_let_through_and_marked_trusted(gated):
    request = make_request(authorization=f"Bearer {SECRET}")
    require_proxy(request)
    assert request.state.trusted_proxy is True


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"authorization": "Bearer wrong-token"},
        {"authorization": SECRET},  # right secret, no scheme
        {"authorization": f"Basic {SECRET}"},
        {"authorization": "Bearer "},
    ],
    ids=["missing", "wrong", "no-scheme", "wrong-scheme", "empty"],
)
def test_everything_else_is_refused(gated, headers):
    with pytest.raises(HTTPException) as caught:
        require_proxy(make_request(**headers))
    assert caught.value.status_code == 401


def test_no_secret_configured_leaves_the_service_open_but_untrusted(monkeypatch):
    """Local development: the gate is off, and precisely because it is off, a
    forwarded client IP must not be believed."""
    monkeypatch.setattr(main, "proxy_config", lambda: ProxyConfig(shared_secret=None))
    request = make_request(x_demo_client_ip="9.9.9.9")
    require_proxy(request)
    assert request.state.trusted_proxy is False
