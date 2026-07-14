# Stripe schemas, translated from https://docs.stripe.com/api (charges, refunds).

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RefundReason(str, Enum):
    """Caller-settable reasons (Stripe also sets expired_uncaptured_charge itself)."""

    DUPLICATE = "duplicate"
    FRAUDULENT = "fraudulent"
    REQUESTED_BY_CUSTOMER = "requested_by_customer"


class RefundStatus(str, Enum):
    PENDING = "pending"
    REQUIRES_ACTION = "requires_action"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class Charge(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    amount: int = Field(..., description="Amount charged, in cents.")
    amount_refunded: int = Field(..., description="Amount already refunded, in cents.")
    currency: str
    disputed: bool
    status: str = Field(..., description="succeeded | pending | failed.")
    customer: Optional[str] = None


class Refund(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    amount: int
    charge: Optional[str] = None
    currency: str
    reason: Optional[str] = None
    status: Optional[RefundStatus] = None


class RefundCreateParams(BaseModel):
    """Refund args / POST /v1/refunds. Exactly one target."""

    model_config = ConfigDict(extra="forbid")

    charge: Optional[str] = None
    payment_intent: Optional[str] = None
    amount: Optional[int] = Field(None, ge=1, description="Cents; omit to refund the full remainder.")
    reason: Optional[RefundReason] = None
    metadata: Optional[Dict[str, str]] = None

    @model_validator(mode="after")
    def _one_target(self) -> "RefundCreateParams":
        if bool(self.charge) == bool(self.payment_intent):
            raise ValueError("Provide exactly one of `charge` or `payment_intent`.")
        return self
