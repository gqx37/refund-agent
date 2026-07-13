# app/integrations/stripe/types/charge/models.py

"""Response schema for the Stripe Charge object.

Translated field-for-field from the Stripe API reference. Descriptions are the
provider's own wording, kept verbatim so the schema never drifts from the docs.
We model the fields this agent reasons about; `extra="allow"` preserves every
other field Stripe returns rather than silently dropping it.

API Reference: https://docs.stripe.com/api/charges/object
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Charge(BaseModel):
    """A Charge object represents an attempt to move money into your Stripe account."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Unique identifier for the object.")
    object: str = Field(
        "charge",
        description="String representing the object's type. Objects of the same type share the same value.",
    )
    amount: int = Field(
        ...,
        description=(
            "Amount intended to be collected by this payment. A positive integer representing how "
            "much to charge in the smallest currency unit (e.g., 100 cents to charge $1.00)."
        ),
    )
    amount_captured: int = Field(
        ...,
        description="Amount in cents (or local equivalent) captured (can be less than the amount attribute on the charge if a partial capture was made).",
    )
    amount_refunded: int = Field(
        ...,
        description=(
            "Amount in cents (or local equivalent) refunded (can be less than the amount attribute "
            "on the charge if a partial refund was issued)."
        ),
    )
    currency: str = Field(
        ...,
        description="Three-letter ISO currency code, in lowercase. Must be a supported currency.",
    )
    created: int = Field(
        ...,
        description="Time at which the object was created. Measured in seconds since the Unix epoch.",
    )
    customer: Optional[str] = Field(
        None, description="ID of the customer this charge is for if one exists."
    )
    captured: bool = Field(
        ...,
        description="If the charge was created without capturing, this Boolean represents whether it is still uncaptured or has since been captured.",
    )
    disputed: bool = Field(
        ..., description="Whether the charge has been disputed."
    )
    paid: bool = Field(
        ...,
        description="True if the charge succeeded, or was successfully authorized for later capture.",
    )
    refunded: bool = Field(
        ...,
        description="Whether the charge has been fully refunded. If the charge is only partially refunded, this attribute will still be false.",
    )
    status: str = Field(
        ...,
        description="The status of the payment is either `succeeded`, `pending`, or `failed`.",
    )
    payment_intent: Optional[str] = Field(
        None, description="ID of the PaymentIntent associated with this charge, if one exists."
    )
    receipt_email: Optional[str] = Field(
        None, description="This is the email address that the receipt for this charge was sent to."
    )
