# app/integrations/stripe/tools.py

"""Stripe tools, declared flat and bound to a StripeClient.

The tool IS the integration: each tool owns its method, path, typed args schema,
and a description lifted straight from the Stripe reference. Nothing here decides
policy — these just move data to and from Stripe.

Two consumers, one definition (the platform's integration pattern):
  - code consumers invoke a tool manually: `await charge_retrieve.ainvoke({...})`.
  - an agent runtime could mount `charge_retrieve` for the model to call.

Deliberately, `refund_create` is NEVER handed to the LLM. It is invoked only by
the deterministic `execute_refund` node, and only after the policy gate returns
APPROVE. That is the whole safety argument: the model cannot move money.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from langchain_core.tools import StructuredTool

from .client import StripeClient
from .types.charge.actions import ChargeRetrieveParams
from .types.charge.models import Charge
from .types.refund.actions import RefundCreateParams
from .types.refund.models import Refund


def _idempotency_key(params: RefundCreateParams) -> str:
    """Derive a deterministic Idempotency-Key from the refund arguments.

    Stripe dedupes POSTs that reuse a key, so retrying an identical request is
    safe (no double refund). The graph stamps a unique `request_id` into metadata,
    so two *different* refund requests get different keys while a retry of the
    *same* request reuses one.

    API Reference: https://docs.stripe.com/api/idempotent_requests
    """
    canonical = json.dumps(
        params.model_dump(exclude_none=True, mode="json"), sort_keys=True, separators=(",", ":")
    )
    return "refund:" + hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class StripeTools:
    """Bundle of the Stripe tools plus the flat `all` list (mount-friendly)."""

    charge_retrieve: StructuredTool
    refund_create: StructuredTool

    @property
    def all(self) -> list[StructuredTool]:
        return [self.charge_retrieve, self.refund_create]


def build_stripe_tools(client: StripeClient) -> StripeTools:
    """Bind the Stripe tools to a live (or stubbed) client."""

    async def _charge_retrieve(**kwargs: object) -> dict:
        params = ChargeRetrieveParams(**kwargs)
        raw = await client.request(
            "GET",
            f"/v1/charges/{params.charge}",
            params={"expand": params.expand} if params.expand else None,
        )
        # Validate the response against our translated schema, then hand back a
        # plain dict so tool output stays JSON-serializable for the graph state.
        return Charge.model_validate(raw).model_dump(mode="json")

    async def _refund_create(**kwargs: object) -> dict:
        params = RefundCreateParams(**kwargs)
        raw = await client.request(
            "POST",
            "/v1/refunds",
            data=params.model_dump(exclude_none=True, mode="json"),
            idempotency_key=_idempotency_key(params),
        )
        return Refund.model_validate(raw).model_dump(mode="json")

    charge_retrieve = StructuredTool.from_function(
        coroutine=_charge_retrieve,
        name="charge_retrieve",
        description=(
            "Retrieve the details of a Stripe charge by its id (ch_…). Returns the amount, "
            "amount_refunded, currency, status, dispute flag, and customer. Read-only."
        ),
        args_schema=ChargeRetrieveParams,
    )

    refund_create = StructuredTool.from_function(
        coroutine=_refund_create,
        name="refund_create",
        description=(
            "Create a refund on a Stripe charge or payment_intent. Refunds up to the remaining "
            "unrefunded amount; omit `amount` to refund in full. Writes money movement."
        ),
        args_schema=RefundCreateParams,
    )

    return StripeTools(charge_retrieve=charge_retrieve, refund_create=refund_create)
