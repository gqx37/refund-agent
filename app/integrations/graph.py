# Neo4j semantic fact store. Reads only, via parameterized queries. Known lookups
# are hand-written Cypher, not Text2Cypher — you don't ask an LLM to regenerate a
# query whose shape you know.
#
# Facts only: (:Customer)-[:PLACED]->(:Order)-[:PAID_WITH]->(:Transaction), and
# (:Customer)-[:USED]->(:PaymentMethod) to link accounts by shared card.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from neo4j import AsyncGraphDatabase, RoutingControl

from app.configs import Neo4jConfig
from app.models import CustomerRiskFacts, OrderFacts


class GraphStore:
    _ORDER_FACTS = """
    MATCH (c:Customer)-[:PLACED]->(o:Order {id: $order_id})-[:PAID_WITH]->(t:Transaction)
    RETURN o.id AS order_id, c.id AS customer_id, t.id AS charge_id,
           o.purchased_at AS purchase_date, o.total_cents AS order_total_cents, o.currency AS currency
    LIMIT 1
    """

    _CUSTOMER_RISK = """
    MATCH (c:Customer {id: $customer_id})
    OPTIONAL MATCH (c)-[:PLACED]->(o:Order)
    WITH c, count(o) AS lifetime_order_count,
         sum(CASE WHEN o.refunded THEN 1 ELSE 0 END) AS prior_refund_count
    OPTIONAL MATCH (c)-[:USED]->(:PaymentMethod)<-[:USED]-(other:Customer)
    WHERE other.id <> c.id
    OPTIONAL MATCH (other)-[:PLACED]->(oo:Order)
    WITH lifetime_order_count, prior_refund_count,
         count(oo) AS linked_orders, sum(CASE WHEN oo.refunded THEN 1 ELSE 0 END) AS linked_refunds
    RETURN lifetime_order_count, prior_refund_count,
           CASE WHEN linked_orders = 0 THEN 0.0
                ELSE toFloat(linked_refunds) / linked_orders END AS linked_account_refund_rate
    """

    def __init__(self, config: Neo4jConfig) -> None:
        self._database = config.database
        self._driver = AsyncGraphDatabase.driver(config.uri, auth=(config.username, config.password))

    async def order_facts(self, order_id: str) -> Optional[OrderFacts]:
        rows = await self._read(self._ORDER_FACTS, {"order_id": order_id})
        if not rows:
            return None
        row = rows[0]
        return OrderFacts(
            order_id=row["order_id"],
            customer_id=row["customer_id"],
            charge_id=row["charge_id"],
            purchase_date=_parse_dt(row["purchase_date"]),
            order_total_cents=int(row["order_total_cents"]),
            currency=row["currency"],
        )

    async def customer_risk(self, customer_id: str) -> Optional[CustomerRiskFacts]:
        rows = await self._read(self._CUSTOMER_RISK, {"customer_id": customer_id})
        if not rows:
            return None
        row = rows[0]
        return CustomerRiskFacts(
            customer_id=customer_id,
            lifetime_order_count=int(row["lifetime_order_count"] or 0),
            prior_refund_count=int(row["prior_refund_count"] or 0),
            linked_account_refund_rate=float(row["linked_account_refund_rate"] or 0.0),
        )

    async def verify(self) -> None:
        await self._driver.verify_connectivity()

    async def _read(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        result = await self._driver.execute_query(
            cypher, parameters_=params, database_=self._database, routing_=RoutingControl.READ
        )
        return [record.data() for record in result.records]

    async def aclose(self) -> None:
        await self._driver.close()


def _parse_dt(value: Any) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
