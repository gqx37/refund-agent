# End-to-end through create_agent with a scripted model (no real LLM). Proves the
# full wiring: model calls issue_refund -> guardrail runs the policy -> the refund
# executes or is blocked -> the agent replies.

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage

from app.agent import RefundAgent
from app.configs import StripeConfig
from app.integrations.stripe import StripeClient
from app.policy import RefundPolicy
from app.sample_data import ORDER_CLEAN, ORDER_DISPUTED, ORDERS
from tests.fakes import FakeStripe, InMemoryGraphStore, ScriptedModel

NOW = datetime(2026, 7, 14, tzinfo=timezone.utc)
CLEAN_CHARGE = next(o.charge_id for o in ORDERS if o.order_id == ORDER_CLEAN)


def _refund_call(order_id: str):
    return AIMessage(content="", tool_calls=[{"name": "issue_refund", "args": {"order_id": order_id}, "id": "c1"}])


@pytest.fixture
def stripe_client() -> StripeClient:
    return StripeClient(StripeConfig(api_key="sk_stub"), transport=FakeStripe().transport)


def _agent(stripe_client: StripeClient, script: list) -> RefundAgent:
    return RefundAgent(
        fact_store=InMemoryGraphStore(now=NOW),
        stripe=stripe_client,
        policy=RefundPolicy(),
        model=ScriptedModel(responses=script),
        now=NOW,
    )


async def test_agent_refunds_a_clean_order(stripe_client):
    agent = _agent(stripe_client, [_refund_call(ORDER_CLEAN), AIMessage(content="Done, you're refunded.")])
    out = await agent.chat("t1", "refund my order please")
    assert out["status"] == "replied"
    assert (await stripe_client.retrieve_charge(CLEAN_CHARGE)).amount_refunded == 2_000


async def test_agent_is_blocked_on_a_disputed_order(stripe_client):
    agent = _agent(stripe_client, [_refund_call(ORDER_DISPUTED), AIMessage(content="Sorry, it's disputed.")])
    out = await agent.chat("t2", "refund my disputed order")
    assert out["status"] == "replied"
    # The guardrail blocked it: the disputed charge was never refunded.
    disputed_charge = next(o.charge_id for o in ORDERS if o.order_id == ORDER_DISPUTED)
    assert (await stripe_client.retrieve_charge(disputed_charge)).amount_refunded == 0
