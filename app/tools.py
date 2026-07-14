# The agent's tools. order_lookup lets it understand a request; issue_refund is
# the action. issue_refund is guarded by RefundGuardrail (app/guardrail.py) — the
# policy runs at the moment it's called, so the model can attempt a refund but
# can't make one the policy would reject.

from __future__ import annotations

import asyncio
from typing import Any, Optional

from langchain.tools import tool

from app.facts import gather_facts
from app.integrations.stripe import Charge, RefundCreateParams, StripeClient, StripeError


def _charge_state(charge: Charge) -> str:
    if charge.disputed:
        return "disputed"
    if charge.amount_refunded >= charge.amount:
        return "fully refunded"
    if charge.amount_refunded > 0:
        return f"partially refunded ({charge.amount_refunded} of {charge.amount} cents)"
    return "refundable"


def build_tools(fact_store: Any, stripe: StripeClient) -> list:
    @tool
    async def list_orders() -> str:
        """List every known order with its live refund state, so the customer can
        see which are already refunded, disputed, or still refundable."""
        orders = await fact_store.all_orders()
        if not orders:
            return "There are no orders on record."
        charges = await asyncio.gather(
            *(stripe.retrieve_charge(o.charge_id) for o in orders), return_exceptions=True
        )
        lines = []
        for order, charge in zip(orders, charges):
            if isinstance(charge, BaseException):
                lines.append(f"- {order.order_id}: {order.order_total_cents} cents, state unavailable")
            else:
                lines.append(f"- {order.order_id}: {charge.amount} cents, {_charge_state(charge)}")
        return "\n".join(lines)

    @tool
    async def order_lookup(order_id: str) -> str:
        """Look up an order: its total, when it was purchased, the charge behind it,
        how much is still refundable, and the customer's refund history."""
        try:
            facts = await gather_facts(fact_store, stripe, order_id)
        except StripeError as exc:
            return f"Could not read the charge for '{order_id}': {exc.message}"
        if facts is None:
            return f"No order '{order_id}' was found."
        c, r = facts.charge, facts.customer_risk
        return (
            f"order {facts.order.order_id}: total {facts.order.order_total_cents} cents, "
            f"purchased {facts.order.days_since_purchase()} days ago. "
            f"charge {c.charge_id}: {c.amount_cents} cents, {c.amount_refunded_cents} refunded, "
            f"{c.remaining_refundable_cents} refundable, disputed={c.disputed}, status={c.status}. "
            f"customer: {r.prior_refund_count}/{r.lifetime_order_count} orders refunded "
            f"({r.refund_rate:.0%}), linked-account refund rate {r.linked_account_refund_rate:.0%}."
        )

    @tool
    async def issue_refund(order_id: str, amount_cents: Optional[int] = None, reason: Optional[str] = None) -> str:
        """Refund an order, in full or a partial amount_cents. A policy engine vets
        every refund and may block or escalate it before it goes through."""
        facts = await gather_facts(fact_store, stripe, order_id)
        if facts is None:
            return f"No order '{order_id}' was found."
        try:
            refund = await stripe.create_refund(RefundCreateParams(
                charge=facts.charge.charge_id,
                amount=amount_cents,
                reason=reason,  # pydantic coerces the string to RefundReason
                metadata={"order_id": order_id},
            ))
        except StripeError as exc:
            return f"Stripe rejected the refund: {exc.message}"
        return f"Refunded {refund.amount / 100:.2f} {refund.currency.upper()} (refund {refund.id})."

    return [list_orders, order_lookup, issue_refund]
