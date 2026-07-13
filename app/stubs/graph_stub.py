# app/stubs/graph_stub.py

"""In-memory FactStore over the demo dataset. Implements the same port as the
Neo4j adapter, so the graph nodes can't tell the difference — which is exactly
what lets the whole agent run in tests with no database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.demo import LINKS, ORDERS
from app.domain import CustomerRiskFacts, OrderFacts


class InMemoryFactStore:
    """FactStore backed by app.demo fixtures. Mirrors the Cypher in schema.py."""

    def __init__(self, *, now: Optional[datetime] = None) -> None:
        self._now = now or datetime.now(timezone.utc)

    async def order_facts(self, order_id: str) -> Optional[OrderFacts]:
        for order in ORDERS:
            if order.order_id == order_id:
                return OrderFacts(
                    order_id=order.order_id,
                    customer_id=order.customer_id,
                    charge_id=order.charge_id,
                    purchase_date=self._now - timedelta(days=order.purchased_days_ago),
                    order_total_cents=order.total_cents,
                    currency=order.currency,
                )
        return None

    async def customer_risk(self, customer_id: str) -> Optional[CustomerRiskFacts]:
        own = [o for o in ORDERS if o.customer_id == customer_id]
        if not own:
            return None
        lifetime = len(own)
        prior_refunds = sum(1 for o in own if o.refunded)

        # Linked accounts: customers sharing a payment method with this one.
        linked_ids: set[str] = set()
        for link in LINKS:
            if customer_id in link.customer_ids:
                linked_ids.update(cid for cid in link.customer_ids if cid != customer_id)

        linked_orders = [o for o in ORDERS if o.customer_id in linked_ids]
        linked_refunds = sum(1 for o in linked_orders if o.refunded)
        linked_rate = (linked_refunds / len(linked_orders)) if linked_orders else 0.0

        return CustomerRiskFacts(
            customer_id=customer_id,
            lifetime_order_count=lifetime,
            prior_refund_count=prior_refunds,
            linked_account_refund_rate=linked_rate,
        )

    async def run_read(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError("Text2Cypher requires the real Neo4j adapter.")

    async def aclose(self) -> None:
        return None
