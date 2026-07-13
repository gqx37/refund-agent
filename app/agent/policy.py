# app/agent/policy.py

"""The deterministic refund policy — the guardrails the agent cannot cross.

This is the core of the Sierra "declarative goals and guardrails" thesis, made
literal: procedural knowledge lives in code, not in a prompt and not in a graph.
`evaluate()` is a pure function of `(request, facts, policy)` — no I/O, no LLM, no
clock except the one you pass in — so it is exhaustively unit-testable and its
verdict is 100% reproducible. The LLM elsewhere in the harness decides what to
*say* and extracts what the customer *meant*; it never decides whether a refund
is allowed. That decision is here, and only here.

Rules are evaluated in order, hard denials before escalations before approval, so
the first rule that fires is decisive and its `rule_id` is recorded for the audit
log and for regression tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.domain import Outcome, PolicyDecision, RefundFacts, RefundRequest


@dataclass(frozen=True)
class RefundPolicy:
    """Declarative, per-merchant refund rules. Change these, change the behavior;
    nothing about *how* the rules are enforced changes."""

    # Refunds are allowed only within this many days of purchase.
    refund_window_days: int = 30
    # A charge status that is not one of these is not refundable.
    refundable_charge_statuses: tuple[str, ...] = ("succeeded",)
    # Above this single-refund amount, a human signs off even if policy-clean.
    auto_approve_ceiling_cents: int = 50_000
    # Escalate to a human when this customer's own refund rate is this high…
    escalate_customer_refund_rate: float = 0.50
    # …or when the refund rate across payment-method/device-linked accounts is
    # this high (the graph-shaped fraud-ring signal).
    escalate_linked_account_refund_rate: float = 0.60


def evaluate(
    request: RefundRequest,
    facts: RefundFacts,
    policy: RefundPolicy,
    *,
    now: Optional[datetime] = None,
) -> PolicyDecision:
    """Run the guardrails and return the single authoritative decision."""
    charge = facts.charge
    passed: list[str] = []

    # --- Hard denials: conditions under which no refund may issue at all. ---

    # A disputed charge is out of our hands — the dispute/chargeback process owns
    # the money. Refunding on top of a dispute double-pays the customer.
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
    passed.append(f"{remaining} cents remain refundable on the charge.")

    days = facts.order.days_since_purchase(now=now)
    if days > policy.refund_window_days:
        return PolicyDecision(
            outcome=Outcome.DENY,
            rule_id="outside_refund_window",
            reasons=[
                f"Purchased {days} days ago; outside the "
                f"{policy.refund_window_days}-day refund window."
            ],
        )
    passed.append(f"Within the {policy.refund_window_days}-day window ({days} days since purchase).")

    # The amount to refund: what was asked, or the full remaining amount.
    amount = request.requested_amount_cents or remaining
    if amount > remaining:
        return PolicyDecision(
            outcome=Outcome.DENY,
            rule_id="amount_exceeds_remaining",
            reasons=[
                f"Requested {amount} cents but only {remaining} cents are refundable."
            ],
        )
    passed.append(f"Requested amount {amount} cents is within the refundable balance.")

    # --- Escalations: policy-clean, but a human should decide. ---

    risk = facts.customer_risk
    if risk.refund_rate >= policy.escalate_customer_refund_rate:
        return PolicyDecision(
            outcome=Outcome.ESCALATE,
            rule_id="high_customer_refund_rate",
            approved_amount_cents=None,
            reasons=passed
            + [
                f"Customer refund rate is {risk.refund_rate:.0%} "
                f"(>= {policy.escalate_customer_refund_rate:.0%}); routing to a human."
            ],
        )

    if risk.linked_account_refund_rate >= policy.escalate_linked_account_refund_rate:
        return PolicyDecision(
            outcome=Outcome.ESCALATE,
            rule_id="linked_account_fraud_signal",
            approved_amount_cents=None,
            reasons=passed
            + [
                f"Linked-account refund rate is {risk.linked_account_refund_rate:.0%} "
                f"(>= {policy.escalate_linked_account_refund_rate:.0%}); possible fraud ring."
            ],
        )

    if amount > policy.auto_approve_ceiling_cents:
        return PolicyDecision(
            outcome=Outcome.ESCALATE,
            rule_id="above_auto_approve_ceiling",
            approved_amount_cents=None,
            reasons=passed
            + [
                f"Amount {amount} cents exceeds the auto-approve ceiling of "
                f"{policy.auto_approve_ceiling_cents} cents; routing to a human."
            ],
        )

    # --- Approval. ---
    return PolicyDecision(
        outcome=Outcome.APPROVE,
        rule_id="policy_clean",
        approved_amount_cents=amount,
        reasons=passed + ["All guardrails passed; refund approved."],
    )
