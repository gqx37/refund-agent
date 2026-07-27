# Fixtures over the fakes: a fake Stripe transport and an in-memory graph, both
# over the sample dataset. `now` is fixed so window checks are deterministic.

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.configs import StripeConfig
from app.guardrail import RefundGuardrail
from app.integrations.stripe import StripeClient
from app.policy import RefundPolicy
from app.tools import build_tools
from tests.fakes import FakeStripe, InMemoryFactStore


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 14, tzinfo=timezone.utc)


@pytest.fixture
def stripe_client() -> StripeClient:
    return StripeClient(StripeConfig(api_key="sk_test_stub"), transport=FakeStripe().transport)


@pytest.fixture
def fact_store(now: datetime) -> InMemoryFactStore:
    return InMemoryFactStore(now=now)


@pytest.fixture
def policy() -> RefundPolicy:
    return RefundPolicy()


@pytest.fixture
def guardrail(fact_store, stripe_client, policy, now) -> RefundGuardrail:
    return RefundGuardrail(fact_store, stripe_client, policy, now=now)


@pytest.fixture
def tools(fact_store, stripe_client) -> dict:
    return {t.name: t for t in build_tools(fact_store, stripe_client)}
