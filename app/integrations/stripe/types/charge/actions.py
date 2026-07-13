# app/integrations/stripe/types/charge/actions.py

"""Request schema for retrieving a Charge.

API Reference: https://docs.stripe.com/api/charges/retrieve
  GET /v1/charges/{charge}
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChargeRetrieveParams(BaseModel):
    """Input for `GET /v1/charges/{charge}`.

    Retrieves the details of a charge that has previously been created. Supply the
    unique charge ID that was returned from your previous request, and Stripe will
    return the corresponding charge information.
    """

    model_config = ConfigDict(extra="forbid")

    # Path parameter.
    charge: str = Field(..., description="The identifier of the charge to be retrieved (ch_…).")

    # Query parameter.
    expand: Optional[List[str]] = Field(
        None, description="Specifies which fields in the response should be expanded."
    )
