# Domain models. Money is integer cents everywhere.

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.integrations.stripe import RefundReason


class RefundRequest(BaseModel):
    request_id: str = Field(..., description="Unique id; used for idempotency and audit.")
    order_id: str
    reason: Optional[RefundReason] = None
    requested_amount_cents: Optional[int] = Field(None, ge=1, description="None = full remaining.")
    customer_message: str = ""


class OrderFacts(BaseModel):
    """From the store."""

    order_id: str
    customer_id: str
    charge_id: str
    purchase_date: datetime
    order_total_cents: int
    currency: str
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None

    def days_since_purchase(self, *, now: Optional[datetime] = None) -> int:
        return ((now or datetime.now(timezone.utc)) - self.purchase_date).days


class CustomerInfo(BaseModel):
    """A customer, for search results (name/email discovery)."""

    id: str
    name: Optional[str] = None
    email: Optional[str] = None


class CustomerRiskFacts(BaseModel):
    """From the graph. linked_account_refund_rate is the refund rate across accounts
    sharing a payment method (the traversal a row store can't do cheaply)."""

    customer_id: str
    lifetime_order_count: int = Field(..., ge=0)
    prior_refund_count: int = Field(..., ge=0)
    linked_account_refund_rate: float = Field(0.0, ge=0.0, le=1.0)

    @property
    def refund_rate(self) -> float:
        return self.prior_refund_count / self.lifetime_order_count if self.lifetime_order_count else 0.0


class ChargeFacts(BaseModel):
    """From Stripe (never the graph)."""

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
    order: OrderFacts
    customer_risk: CustomerRiskFacts
    charge: ChargeFacts


class Outcome(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    ESCALATE = "escalate"


class PolicyDecision(BaseModel):
    outcome: Outcome
    reasons: list[str] = Field(default_factory=list)
    approved_amount_cents: Optional[int] = None  # set only on APPROVE
    rule_id: Optional[str] = None  # the decisive rule, for logs and tests
