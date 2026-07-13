# Everything runs on the fakes: a fake Stripe transport and an in-memory graph,
# both over the sample dataset. No keys, no network, no Postgres. `now` is fixed so
# the refund-window assertions are deterministic.

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agent import RefundAgent
from app.configs import StripeConfig
from app.integrations.stripe import StripeClient
from app.policy import RefundPolicy
from tests.fakes import FakeStripe, InMemoryGraphStore


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 13, tzinfo=timezone.utc)


@pytest.fixture
def stripe_client() -> StripeClient:
    return StripeClient(StripeConfig(api_key="sk_test_stub"), transport=FakeStripe().transport)


@pytest.fixture
def agent(now: datetime, stripe_client: StripeClient) -> RefundAgent:
    return RefundAgent(
        fact_store=InMemoryGraphStore(now=now),
        stripe=stripe_client,
        policy=RefundPolicy(),
        llm=None,  # the whole graph runs with no model
        now=now,
    )
