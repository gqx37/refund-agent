# app/integrations/graph/client.py

"""Neo4j adapter for the FactStore port.

Reads only. Known lookups go through the parameterized queries in schema.py;
`run_read` is a guarded escape hatch for the Text2Cypher tool that refuses any
statement containing a write clause and forces READ routing at the driver level.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from neo4j import AsyncGraphDatabase, RoutingControl

from app.config import Neo4jConfig
from app.domain import CustomerRiskFacts, OrderFacts
from app.integrations.graph.schema import CUSTOMER_RISK_CYPHER, ORDER_FACTS_CYPHER

# Cypher write/DDL clauses that must never appear in a read query. Matched
# case-insensitively on word boundaries. Belt-and-braces with READ routing:
# routing alone rejects writes server-side, but this fails fast and gives a clear
# message before the query is ever sent.
_WRITE_CLAUSES = re.compile(
    r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|DETACH|CALL\s*\{[^}]*(?:CREATE|MERGE|DELETE|SET)|"
    r"LOAD\s+CSV|FOREACH)\b",
    re.IGNORECASE,
)


class ReadOnlyViolation(ValueError):
    """Raised when a Text2Cypher-generated query is not read-only."""


def _parse_dt(value: Any) -> datetime:
    """Coerce a stored purchase_date into a tz-aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        # Stored as ISO-8601 string. Accept a trailing 'Z'.
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Neo4jFactStore:
    """FactStore backed by a Neo4j graph."""

    def __init__(self, config: Neo4jConfig) -> None:
        self._database = config.database
        self._driver = AsyncGraphDatabase.driver(
            config.uri, auth=(config.username, config.password)
        )

    async def order_facts(self, order_id: str) -> Optional[OrderFacts]:
        rows = await self._read(ORDER_FACTS_CYPHER, {"order_id": order_id})
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
        rows = await self._read(CUSTOMER_RISK_CYPHER, {"customer_id": customer_id})
        if not rows:
            return None
        row = rows[0]
        return CustomerRiskFacts(
            customer_id=customer_id,
            lifetime_order_count=int(row["lifetime_order_count"] or 0),
            prior_refund_count=int(row["prior_refund_count"] or 0),
            linked_account_refund_rate=float(row["linked_account_refund_rate"] or 0.0),
        )

    async def run_read(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if _WRITE_CLAUSES.search(cypher):
            raise ReadOnlyViolation("Query contains a write clause; only reads are permitted.")
        return await self._read(cypher, params)

    async def _read(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        records = await self._driver.execute_query(
            cypher,
            parameters_=params,
            database_=self._database,
            routing_=RoutingControl.READ,  # server-side guarantee: no writes
        )
        return [record.data() for record in records.records]

    async def aclose(self) -> None:
        await self._driver.close()
