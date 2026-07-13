# app/integrations/stripe/types/refund/actions.py

"""Request schema for creating a Refund.

API Reference: https://docs.stripe.com/api/refunds/create
  POST /v1/refunds

When you create a new refund, you must specify a charge or a payment_intent on
which to create it. Creating a new refund will refund a charge that has
previously been created but not yet refunded. Funds will be refunded to the
credit or debit card that was originally charged.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RefundCreateReason(str, Enum):
    """Reason for the refund.

    This is the caller-settable enum (Stripe additionally sets
    `expired_uncaptured_charge` internally; it is not accepted on create).
    """

    DUPLICATE = "duplicate"
    FRAUDULENT = "fraudulent"
    REQUESTED_BY_CUSTOMER = "requested_by_customer"


class RefundCreateParams(BaseModel):
    """Input for `POST /v1/refunds`.

    Exactly one of `charge` or `payment_intent` must be provided.
    """

    model_config = ConfigDict(extra="forbid")

    charge: Optional[str] = Field(
        None, description="The identifier of the charge to refund (ch_…)."
    )
    payment_intent: Optional[str] = Field(
        None, description="The identifier of the PaymentIntent to refund (pi_…)."
    )
    amount: Optional[int] = Field(
        None,
        ge=1,
        description=(
            "A positive integer in cents representing how much of this charge to refund. Can refund "
            "only up to the remaining, unrefunded amount of the charge. Omit to refund the full "
            "remaining amount."
        ),
    )
    reason: Optional[RefundCreateReason] = Field(
        None,
        description=(
            "String indicating the reason for the refund. If set, possible values are `duplicate`, "
            "`fraudulent`, and `requested_by_customer`. If you believe the charge to be fraudulent, "
            "specifying `fraudulent` as the reason will add the associated card and email to your "
            "block lists, and will also help Stripe improve its fraud detection algorithms."
        ),
    )
    metadata: Optional[Dict[str, str]] = Field(
        None,
        description=(
            "Set of key-value pairs that you can attach to an object. This can be useful for storing "
            "additional information about the object in a structured format."
        ),
    )
    reverse_transfer: Optional[bool] = Field(
        None,
        description=(
            "Boolean indicating whether the transfer should be reversed when refunding this charge. "
            "The transfer will be reversed proportionally to the amount being refunded (either the "
            "entire or partial amount). A transfer can be reversed only by the application that "
            "created the charge."
        ),
    )
    refund_application_fee: Optional[bool] = Field(
        None,
        description=(
            "Boolean indicating whether the application fee should be refunded when refunding this "
            "charge. If a full charge refund is given, the full application fee will be refunded. "
            "Otherwise, the application fee will be refunded in an amount proportional to the amount "
            "of the charge refunded."
        ),
    )

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "RefundCreateParams":
        # Stripe requires a charge or a payment_intent; giving both is ambiguous.
        # We enforce it here so a malformed tool call fails before any network I/O.
        if bool(self.charge) == bool(self.payment_intent):
            raise ValueError("Provide exactly one of `charge` or `payment_intent`.")
        return self
