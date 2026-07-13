# The deterministic refund policy. evaluate() is a pure function of
# (request, facts, policy) — no I/O, no LLM, no clock except the one passed in.
# The LLM never runs this; it only extracts intent and phrases the reply.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.models import Outcome, PolicyDecision, RefundFacts, RefundRequest


@dataclass(frozen=True)
class RefundPolicy:
    refund_window_days: int = 30
    refundable_charge_statuses: tuple[str, ...] = ("succeeded",)
    auto_approve_ceiling_cents: int = 50_000  # above this, a human signs off
    escalate_customer_refund_rate: float = 0.50
    escalate_linked_account_refund_rate: float = 0.60  # fraud-ring signal


def evaluate(
    request: RefundRequest,
    facts: RefundFacts,
    policy: RefundPolicy,
    *,
    now: Optional[datetime] = None,
) -> PolicyDecision:
    """Rules run in order: hard denials, then escalations, then approve. The first
    rule to fire is decisive and names itself in rule_id."""
    charge = facts.charge
    passed: list[str] = []

    # A disputed charge is owned by the dispute process; refunding double-pays.
    if charge.disputed:
        return PolicyDecision(
            outcome=Outcome.DENY,
            rule_id="charge_disputed",
            reasons=["The charge is under dispute; refunds are handled by the dispute process."],
        )

    if charge.status not in policy.refundable_charge_statuses:
        return PolicyDecision(
            outcome=Outcome.DENY,
            rule_id="charge_not_refundable",
            reasons=[f"Charge status is '{charge.status}', which is not refundable."],
        )

    remaining = charge.remaining_refundable_cents
    if remaining <= 0:
        return PolicyDecision(
            outcome=Outcome.DENY,
            rule_id="already_refunded",
            reasons=["The charge has already been fully refunded."],
        )
    passed.append(f"{remaining} cents remain refundable.")

    days = facts.order.days_since_purchase(now=now)
    if days > policy.refund_window_days:
        return PolicyDecision(
            outcome=Outcome.DENY,
            rule_id="outside_refund_window",
            reasons=[f"Purchased {days} days ago; outside the {policy.refund_window_days}-day window."],
        )
    passed.append(f"Within the {policy.refund_window_days}-day window ({days} days).")

    amount = request.requested_amount_cents or remaining
    if amount > remaining:
        return PolicyDecision(
            outcome=Outcome.DENY,
            rule_id="amount_exceeds_remaining",
            reasons=[f"Requested {amount} cents but only {remaining} cents are refundable."],
        )

    risk = facts.customer_risk
    if risk.refund_rate >= policy.escalate_customer_refund_rate:
        return PolicyDecision(
            outcome=Outcome.ESCALATE,
            rule_id="high_customer_refund_rate",
            reasons=passed + [f"Customer refund rate is {risk.refund_rate:.0%}; routing to a human."],
        )

    if risk.linked_account_refund_rate >= policy.escalate_linked_account_refund_rate:
        return PolicyDecision(
            outcome=Outcome.ESCALATE,
            rule_id="linked_account_fraud_signal",
            reasons=passed
            + [f"Linked-account refund rate is {risk.linked_account_refund_rate:.0%}; possible fraud ring."],
        )

    if amount > policy.auto_approve_ceiling_cents:
        return PolicyDecision(
            outcome=Outcome.ESCALATE,
            rule_id="above_auto_approve_ceiling",
            reasons=passed + [f"Amount {amount} cents exceeds the auto-approve ceiling; routing to a human."],
        )

    return PolicyDecision(
        outcome=Outcome.APPROVE,
        rule_id="policy_clean",
        approved_amount_cents=amount,
        reasons=passed + ["All guardrails passed."],
    )
