# tests/test_policy.py

"""Exhaustive unit tests for the policy gate — the point of making it a pure
function. No stubs needed here; we build facts directly and assert the outcome
and the decisive rule_id."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from app.agent.policy import RefundPolicy, evaluate
from app.domain import (
    ChargeFacts,
    CustomerRiskFacts,
    Outcome,
    OrderFacts,
    RefundFacts,
    RefundRequest,
)

NOW = datetime(2026, 7, 13, tzinfo=timezone.utc)
POLICY = RefundPolicy()


def make_facts(
    *,
    days: int = 3,
    amount: int = 2_000,
    refunded: int = 0,
    disputed: bool = False,
    status: str = "succeeded",
    lifetime: int = 4,
    prior: int = 1,
    linked_rate: float = 0.0,
) -> RefundFacts:
    return RefundFacts(
        order=OrderFacts(
            order_id="o1",
            customer_id="c1",
            charge_id="ch1",
            purchase_date=NOW - timedelta(days=days),
            order_total_cents=amount,
            currency="usd",
        ),
        customer_risk=CustomerRiskFacts(
            customer_id="c1",
            lifetime_order_count=lifetime,
            prior_refund_count=prior,
            linked_account_refund_rate=linked_rate,
        ),
        charge=ChargeFacts(
            charge_id="ch1",
            amount_cents=amount,
            amount_refunded_cents=refunded,
            currency="usd",
            disputed=disputed,
            status=status,
        ),
    )


def make_request(amount: int | None = None) -> RefundRequest:
    return RefundRequest(request_id="req1", order_id="o1", requested_amount_cents=amount)


def decide(facts: RefundFacts, request: RefundRequest | None = None):
    return evaluate(request or make_request(), facts, POLICY, now=NOW)


def test_clean_request_is_approved_for_full_amount():
    d = decide(make_facts())
    assert d.outcome is Outcome.APPROVE
    assert d.rule_id == "policy_clean"
    assert d.approved_amount_cents == 2_000


def test_partial_amount_is_approved_at_requested_amount():
    d = decide(make_facts(), make_request(amount=1_000))
    assert d.outcome is Outcome.APPROVE
    assert d.approved_amount_cents == 1_000


def test_disputed_charge_is_denied():
    d = decide(make_facts(disputed=True))
    assert d.outcome is Outcome.DENY
    assert d.rule_id == "charge_disputed"


def test_non_succeeded_charge_is_denied():
    d = decide(make_facts(status="pending"))
    assert d.outcome is Outcome.DENY
    assert d.rule_id == "charge_not_refundable"


def test_fully_refunded_charge_is_denied():
    d = decide(make_facts(refunded=2_000))
    assert d.outcome is Outcome.DENY
    assert d.rule_id == "already_refunded"


def test_outside_window_is_denied():
    d = decide(make_facts(days=45))
    assert d.outcome is Outcome.DENY
    assert d.rule_id == "outside_refund_window"


def test_amount_exceeding_remaining_is_denied():
    # 1500 already refunded => 500 remains; asking for 2000 is too much.
    d = decide(make_facts(refunded=1_500), make_request(amount=2_000))
    assert d.outcome is Outcome.DENY
    assert d.rule_id == "amount_exceeds_remaining"


def test_high_customer_refund_rate_escalates():
    d = decide(make_facts(lifetime=4, prior=3))  # 75% >= 50%
    assert d.outcome is Outcome.ESCALATE
    assert d.rule_id == "high_customer_refund_rate"
    assert d.approved_amount_cents is None


def test_linked_account_signal_escalates():
    d = decide(make_facts(linked_rate=0.7))  # >= 60%
    assert d.outcome is Outcome.ESCALATE
    assert d.rule_id == "linked_account_fraud_signal"


def test_high_value_escalates_even_when_clean():
    d = decide(make_facts(amount=60_000))
    assert d.outcome is Outcome.ESCALATE
    assert d.rule_id == "above_auto_approve_ceiling"


def test_hard_denials_take_precedence_over_escalation():
    # Disputed AND a serial refunder: the deny wins (evaluated first).
    d = decide(make_facts(disputed=True, lifetime=4, prior=3))
    assert d.outcome is Outcome.DENY
    assert d.rule_id == "charge_disputed"
