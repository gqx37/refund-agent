# Assemble the facts a refund decision needs, from the graph (order + customer
# history) and Stripe (authoritative money state). Shared by the tools and the
# guardrail so both read the same picture.

from __future__ import annotations

from typing import Any, Optional

from app.integrations.stripe import StripeClient
from app.models import ChargeFacts, RefundFacts


async def gather_facts(fact_store: Any, stripe: StripeClient, order_id: str) -> Optional[RefundFacts]:
    order = await fact_store.order_facts(order_id)
    if order is None:
        return None
    risk = await fact_store.customer_risk(order.customer_id)
    if risk is None:
        return None
    charge = await stripe.retrieve_charge(order.charge_id)
    return RefundFacts(
        order=order,
        customer_risk=risk,
        charge=ChargeFacts(
            charge_id=charge.id,
            amount_cents=charge.amount,
            amount_refunded_cents=charge.amount_refunded,
            currency=charge.currency,
            disputed=charge.disputed,
            status=charge.status,
        ),
    )
