# End-to-end runs through the agent, on fakes, with no LLM.

from __future__ import annotations

from app.models import Outcome, RefundRequest
from app.sample_data import (
    ORDER_CLEAN,
    ORDER_DISPUTED,
    ORDER_FRAUD_RING,
    ORDER_FULLY_REFUNDED,
    ORDER_HIGH_VALUE,
    ORDER_OUT_OF_WINDOW,
    ORDER_PARTIALLY_REFUNDED,
    ORDER_SERIAL_REFUNDER,
)


def req(order_id: str, **kw) -> RefundRequest:
    return RefundRequest(request_id=f"req_{order_id}", order_id=order_id, **kw)


async def test_clean_request_is_approved_and_refunded(agent):
    out = await agent.submit(req(ORDER_CLEAN))
    assert out.status == "approved"
    assert out.decision.rule_id == "policy_clean"
    assert out.refund["amount"] == 2_000
    assert "Refunded" in out.reply


async def test_out_of_window_is_denied(agent):
    out = await agent.submit(req(ORDER_OUT_OF_WINDOW))
    assert out.status == "denied"
    assert out.decision.rule_id == "outside_refund_window"
    assert out.refund is None


async def test_disputed_is_denied(agent):
    out = await agent.submit(req(ORDER_DISPUTED))
    assert out.decision.rule_id == "charge_disputed"


async def test_already_refunded_is_denied(agent):
    out = await agent.submit(req(ORDER_FULLY_REFUNDED))
    assert out.decision.rule_id == "already_refunded"


async def test_unknown_order_is_denied(agent):
    out = await agent.submit(req("SO-00000"))
    assert out.decision.rule_id == "order_not_found"


async def test_high_value_escalates(agent):
    out = await agent.submit(req(ORDER_HIGH_VALUE))
    assert out.status == "escalated"
    assert out.review["amount_cents"] == 60_000
    assert out.refund is None


async def test_serial_refunder_escalates(agent):
    assert (await agent.submit(req(ORDER_SERIAL_REFUNDER))).status == "escalated"


async def test_linked_account_escalates(agent):
    assert (await agent.submit(req(ORDER_FRAUD_RING))).status == "escalated"


async def test_partial_refund_uses_remaining_balance_not_charge_total(agent):
    # Charge is 4000 with 1500 already refunded; asking for the 2500 that remains
    # refunds exactly that, never the 4000 total.
    out = await agent.submit(req(ORDER_PARTIALLY_REFUNDED, requested_amount_cents=2_500))
    assert out.status == "approved"
    assert out.decision.approved_amount_cents == 2_500
    assert out.refund["amount"] == 2_500


async def test_partial_refund_over_remaining_balance_is_denied(agent):
    out = await agent.submit(req(ORDER_PARTIALLY_REFUNDED, requested_amount_cents=3_000))
    assert out.status == "denied"
    assert out.decision.rule_id == "amount_exceeds_remaining"
    assert out.refund is None


async def test_escalation_resumed_with_approval_refunds(agent):
    request = req(ORDER_HIGH_VALUE)
    assert (await agent.submit(request)).status == "escalated"
    resolved = await agent.resolve(request.request_id, approve=True)
    assert resolved.status == "approved"
    assert resolved.decision.rule_id == "human_approved"
    assert resolved.refund["amount"] == 60_000


async def test_escalation_resumed_with_denial_does_not_refund(agent):
    request = req(ORDER_SERIAL_REFUNDER)
    assert (await agent.submit(request)).status == "escalated"
    resolved = await agent.resolve(request.request_id, approve=False)
    assert resolved.status == "denied"
    assert resolved.decision.rule_id == "human_denied"
    assert resolved.refund is None


async def test_decision_authorizes_before_any_refund_exists(agent):
    out = await agent.submit(req(ORDER_CLEAN))
    assert out.decision.outcome is Outcome.APPROVE
    assert out.decision.approved_amount_cents == 2_000
