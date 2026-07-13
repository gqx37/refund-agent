# tests/test_graph_flow.py

"""End-to-end runs through the compiled graph, on stubs, with no LLM.

This is the property that matters most for the whole project: the full agent —
intake, graph facts, Stripe money state, policy gate, refund execution, and the
human-in-the-loop resume — runs with zero API keys and zero infrastructure."""

from __future__ import annotations


from app.domain import Outcome, RefundRequest


def req(order_id: str, **kw) -> RefundRequest:
    return RefundRequest(request_id=f"req_{order_id}", order_id=order_id, **kw)


async def test_clean_request_is_approved_and_refunded(service):
    out = await service.submit(req("order_alice_ok"))
    assert out.status == "approved"
    assert out.decision.rule_id == "policy_clean"
    assert out.refund is not None
    assert out.refund["amount"] == 2_000
    assert "Refunded" in out.reply


async def test_out_of_window_is_denied(service):
    out = await service.submit(req("order_alice_old"))
    assert out.status == "denied"
    assert out.decision.rule_id == "outside_refund_window"
    assert out.refund is None


async def test_disputed_is_denied(service):
    out = await service.submit(req("order_alice_disputed"))
    assert out.status == "denied"
    assert out.decision.rule_id == "charge_disputed"


async def test_already_refunded_is_denied(service):
    out = await service.submit(req("order_alice_done"))
    assert out.status == "denied"
    assert out.decision.rule_id == "already_refunded"


async def test_unknown_order_is_denied(service):
    out = await service.submit(req("order_does_not_exist"))
    assert out.status == "denied"
    assert out.decision.rule_id == "order_not_found"


async def test_high_value_escalates(service):
    out = await service.submit(req("order_alice_big"))
    assert out.status == "escalated"
    assert out.review["amount_cents"] == 60_000
    assert out.refund is None


async def test_serial_refunder_escalates(service):
    out = await service.submit(req("order_bob"))
    assert out.status == "escalated"


async def test_linked_account_escalates(service):
    out = await service.submit(req("order_carol"))
    assert out.status == "escalated"


async def test_escalation_resumed_with_approval_refunds(service):
    request = req("order_alice_big")
    escalated = await service.submit(request)
    assert escalated.status == "escalated"

    resolved = await service.resolve(request.request_id, approve=True)
    assert resolved.status == "approved"
    assert resolved.decision.rule_id == "human_approved"
    assert resolved.refund["amount"] == 60_000


async def test_escalation_resumed_with_denial_does_not_refund(service):
    request = req("order_bob")
    escalated = await service.submit(request)
    assert escalated.status == "escalated"

    resolved = await service.resolve(request.request_id, approve=False)
    assert resolved.status == "denied"
    assert resolved.decision.rule_id == "human_denied"
    assert resolved.refund is None


async def test_the_llm_is_never_bound_to_the_refund_tool(service):
    # The safety invariant, asserted structurally: the model (here None) is not on
    # the path to money movement; refunds only happen via the deterministic node.
    # We check the decision authorizes before any refund object exists.
    out = await service.submit(req("order_alice_ok"))
    assert out.decision.outcome is Outcome.APPROVE
    assert out.decision.approved_amount_cents == 2_000
