# app/domain.py

"""Domain models shared across the harness.

These are the vocabulary the policy engine, the fact store, and the graph nodes
all speak. Keeping them here (not inside any one module) is what lets the policy
be a pure function of `(RefundRequest, RefundFacts)` and stay testable without a
graph, a Stripe key, or an LLM.

Money is always integer cents, matching Stripe's smallest-currency-unit
convention. There are no floats anywhere near an amount.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.integrations.stripe.types.refund.actions import RefundCreateReason


class RefundRequest(BaseModel):
    """A customer's request, once parsed into structured intent.

    `customer_message` is the raw natural language; the LLM's only job at intake
    is to fill the structured fields from it. `request_id` is a caller-supplied
    unique id that flows into the refund's idempotency key and the audit log.
    """

    request_id: str = Field(..., description="Unique id for this request (idempotency + audit).")
    order_id: str = Field(..., description="The order the customer wants refunded.")
    reason: Optional[RefundCreateReason] = Field(
        None, description="Refund reason, if the customer gave one."
    )
    requested_amount_cents: Optional[int] = Field(
        None, ge=1, description="Requested amount in cents; None means the full remaining amount."
    )
    customer_message: str = Field("", description="The original customer message, verbatim.")


class OrderFacts(BaseModel):
    """Order-level facts. Source of truth: the semantic graph (Neo4j)."""

    order_id: str
    customer_id: str
    charge_id: str = Field(..., description="The Stripe charge (ch_…) this order was paid with.")
    purchase_date: datetime = Field(..., description="When the order was placed (tz-aware, UTC).")
    order_total_cents: int
    currency: str

    def days_since_purchase(self, *, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        return (now - self.purchase_date).days


class CustomerRiskFacts(BaseModel):
    """Customer refund-history facts used for fraud escalation.

    Source of truth: the semantic graph. `linked_account_refund_rate` is the
    classic graph-shaped signal — the refund rate across accounts that share a
    payment method / device / address with this customer, which a row store
    can't cheaply answer but a graph traversal can.
    """

    customer_id: str
    lifetime_order_count: int = Field(..., ge=0)
    prior_refund_count: int = Field(..., ge=0)
    linked_account_refund_rate: float = Field(0.0, ge=0.0, le=1.0)

    @property
    def refund_rate(self) -> float:
        if self.lifetime_order_count == 0:
            return 0.0
        return self.prior_refund_count / self.lifetime_order_count


class ChargeFacts(BaseModel):
    """Money facts. Source of truth: Stripe (never the graph)."""

    charge_id: str
    amount_cents: int
    amount_refunded_cents: int
    currency: str
    disputed: bool
    status: str

    @property
    def remaining_refundable_cents(self) -> int:
        return max(0, self.amount_cents - self.amount_refunded_cents)


class RefundFacts(BaseModel):
    """Everything the policy needs, assembled from the graph and from Stripe."""

    order: OrderFacts
    customer_risk: CustomerRiskFacts
    charge: ChargeFacts


class Outcome(str, Enum):
    """The three deterministic outcomes of the policy gate."""

    APPROVE = "approve"
    DENY = "deny"
    ESCALATE = "escalate"  # hand to a human, do not auto-act


class PolicyDecision(BaseModel):
    """The output of the policy gate — the only thing that authorizes a refund.

    `approved_amount_cents` is set only on APPROVE and is the amount the executor
    is permitted to refund (never more than the remaining refundable amount).
    `reasons` is an ordered, human-readable audit trail of every rule that fired.
    """

    outcome: Outcome
    reasons: list[str] = Field(default_factory=list)
    approved_amount_cents: Optional[int] = None
    rule_id: Optional[str] = Field(
        None, description="Id of the decisive rule, for logging and regression tests."
    )
