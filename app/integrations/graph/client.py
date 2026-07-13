# Neo4j adapter for the FactStore port. Reads only, via parameterized queries.

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from neo4j import AsyncGraphDatabase, RoutingControl

from app.config import Neo4jConfig
from app.domain import CustomerRiskFacts, OrderFacts
from app.integrations.graph.schema import CUSTOMER_RISK, ORDER_FACTS


def _parse_dt(value: Any) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Neo4jFactStore:
    def __init__(self, config: Neo4jConfig) -> None:
        self._database = config.database
        self._driver = AsyncGraphDatabase.driver(config.uri, auth=(config.username, config.password))

    async def order_facts(self, order_id: str) -> Optional[OrderFacts]:
        rows = await self._read(ORDER_FACTS, {"order_id": order_id})
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
        rows = await self._read(CUSTOMER_RISK, {"customer_id": customer_id})
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
        """Readiness check."""
        await self._driver.verify_connectivity()

    async def _read(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        result = await self._driver.execute_query(
            cypher, parameters_=params, database_=self._database, routing_=RoutingControl.READ
        )
        return [record.data() for record in result.records]

    async def aclose(self) -> None:
        await self._driver.close()
