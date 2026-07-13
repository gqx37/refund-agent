# tests/conftest.py

"""Shared fixtures. Everything runs on stubs: a fake Stripe transport and an
in-memory graph, both over the app.demo dataset. No keys, no network, no Postgres.
`now` is fixed so the refund-window assertions are deterministic."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.agent.graph import RefundAgentDeps
from app.agent.policy import RefundPolicy
from app.agent.service import RefundAgentService
from app.config import StripeConfig
from app.integrations.stripe.client import StripeClient
from app.integrations.stripe.tools import build_stripe_tools
from app.stubs.graph_stub import InMemoryFactStore
from app.stubs.stripe_stub import FakeStripe


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 13, tzinfo=timezone.utc)


@pytest.fixture
def fake_stripe() -> FakeStripe:
    return FakeStripe()


@pytest.fixture
def stripe_tools(fake_stripe: FakeStripe):
    client = StripeClient(StripeConfig(api_key="sk_test_stub"), transport=fake_stripe.transport)
    return build_stripe_tools(client)


@pytest.fixture
def service(now: datetime, stripe_tools) -> RefundAgentService:
    deps = RefundAgentDeps(
        fact_store=InMemoryFactStore(now=now),
        stripe_tools=stripe_tools,
        policy=RefundPolicy(),
        llm=None,  # the whole graph runs with no model
        now=now,
    )
    return RefundAgentService(deps)
