# Stripe tools bound to a client. `refund_create` is invoked only by the
# deterministic execute_refund node, never handed to the LLM.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from langchain_core.tools import StructuredTool

from .client import StripeClient
from .schemas import Charge, ChargeRetrieveParams, Refund, RefundCreateParams


def _idempotency_key(params: RefundCreateParams) -> str:
    # Deterministic key from the args, so a retry replays instead of double-refunding.
    # The graph puts a unique request_id in metadata, so distinct requests differ.
    canonical = json.dumps(
        params.model_dump(exclude_none=True, mode="json"), sort_keys=True, separators=(",", ":")
    )
    return "refund:" + hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class StripeTools:
    charge_retrieve: StructuredTool
    refund_create: StructuredTool


def build_stripe_tools(client: StripeClient) -> StripeTools:
    async def _charge_retrieve(**kwargs: object) -> dict:
        params = ChargeRetrieveParams(**kwargs)
        raw = await client.request(
            "GET",
            f"/v1/charges/{params.charge}",
            params={"expand": params.expand} if params.expand else None,
        )
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

    return StripeTools(
        charge_retrieve=StructuredTool.from_function(
            coroutine=_charge_retrieve,
            name="charge_retrieve",
            description="Retrieve a Stripe charge by id. Read-only.",
            args_schema=ChargeRetrieveParams,
        ),
        refund_create=StructuredTool.from_function(
            coroutine=_refund_create,
            name="refund_create",
            description="Create a refund on a charge or payment_intent.",
            args_schema=RefundCreateParams,
        ),
    )
