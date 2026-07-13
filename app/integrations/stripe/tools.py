# The agent's Stripe tools, bound to a client. The tool IS the capability: each
# owns its args schema and a description, the same shape a model would be given.
#
# The orchestrator (RefundAgent) invokes these via `.ainvoke(...)`. It never binds
# them to the LLM: `issue_refund` moves money, and the decision to call it is the
# policy gate's, not the model's.

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.tools import StructuredTool

from app.integrations.stripe.client import StripeClient
from app.integrations.stripe.schemas import ChargeLookup, RefundCreateParams


@dataclass(frozen=True)
class StripeTools:
    charge_lookup: StructuredTool
    issue_refund: StructuredTool

    @property
    def all(self) -> list[StructuredTool]:
        return [self.charge_lookup, self.issue_refund]


def build_stripe_tools(client: StripeClient) -> StripeTools:
    async def _charge_lookup(charge_id: str) -> dict:
        charge = await client.retrieve_charge(charge_id)
        return charge.model_dump(mode="json")

    async def _issue_refund(**kwargs: object) -> dict:
        refund = await client.create_refund(RefundCreateParams(**kwargs))
        return refund.model_dump(mode="json")

    return StripeTools(
        charge_lookup=StructuredTool.from_function(
            coroutine=_charge_lookup,
            name="charge_lookup",
            description="Look up a Stripe charge: its amount, how much is already refunded, its "
            "status, and whether it is disputed.",
            args_schema=ChargeLookup,
        ),
        issue_refund=StructuredTool.from_function(
            coroutine=_issue_refund,
            name="issue_refund",
            description="Refund a Stripe charge, in full or a partial amount. Moves money.",
            args_schema=RefundCreateParams,
        ),
    )
