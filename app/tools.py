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


async def _order_lines(
    fact_store: Any, stripe: StripeClient, orders: list, *, with_customer: bool = False
) -> list[str]:
    """Render orders with their live Stripe state, fetched concurrently. Set
    with_customer to name the customer on each line (for a flat, ungrouped list)."""
    charges = await asyncio.gather(
        *(stripe.retrieve_charge(o.charge_id) for o in orders), return_exceptions=True
    )
    lines = []
    for order, charge in zip(orders, charges):
        who = f" ({order.customer_name})" if with_customer and order.customer_name else ""
        amount = charge.amount if not isinstance(charge, BaseException) else order.order_total_cents
        state = "state unavailable" if isinstance(charge, BaseException) else _charge_state(charge)
        lines.append(f"- {order.order_id}{who}: {amount} cents, {state}")
    return lines


def build_tools(fact_store: Any, stripe: StripeClient) -> list:
    @tool
    async def find_customer(query: str) -> str:
        """Find customers by name, email, or id, and show each one's orders with
        their live refund state. Use this when the customer identifies themselves by
        name or email rather than giving an order number."""
        customers = await fact_store.find_customers(query)
        if not customers:
            return f"No customer matched '{query}'."
        blocks = []
        for cust in customers:
            orders = await fact_store.orders_for_customer(cust.id)
            lines = await _order_lines(fact_store, stripe, orders)
            header = f"{cust.name} <{cust.email}> ({cust.id})"
            blocks.append(header + ("\n" + "\n".join(lines) if lines else "\n- no orders"))
        return "\n\n".join(blocks)

    @tool
    async def list_orders() -> str:
        """List every known order with its live refund state, so you can see which
        are already refunded, disputed, or still refundable. For a specific person,
        prefer find_customer."""
        orders = await fact_store.all_orders()
        if not orders:
            return "There are no orders on record."
        return "\n".join(await _order_lines(fact_store, stripe, orders, with_customer=True))

    @tool
    async def order_lookup(order_id: str) -> str:
        """Look up an order: the customer, its total, when it was purchased, the charge
        behind it, how much is still refundable, and the customer's refund history."""
        try:
            facts = await gather_facts(fact_store, stripe, order_id)
        except StripeError as exc:
            return f"Could not read the charge for '{order_id}': {exc.message}"
        if facts is None:
            return f"No order '{order_id}' was found."
        c, r = facts.charge, facts.customer_risk
        who = facts.order.customer_name or facts.order.customer_id
        return (
            f"order {facts.order.order_id} for {who}: total {facts.order.order_total_cents} cents, "
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

    return [find_customer, list_orders, order_lookup, issue_refund]
