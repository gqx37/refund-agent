# Seed the graph with the sample dataset. Idempotent (all MERGE, a pure function
# of app/sample_data.py). Run from the repo root: python -m scripts.seed_graph

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from neo4j import AsyncGraphDatabase

from app.configs import Neo4jConfig
from app.sample_data import LINKS, ORDERS

_CONSTRAINTS = [
    "CREATE CONSTRAINT customer_id IF NOT EXISTS FOR (c:Customer) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT order_id IF NOT EXISTS FOR (o:Order) REQUIRE o.id IS UNIQUE",
    "CREATE CONSTRAINT transaction_id IF NOT EXISTS FOR (t:Transaction) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT pm_fingerprint IF NOT EXISTS FOR (p:PaymentMethod) REQUIRE p.fingerprint IS UNIQUE",
]

_UPSERT_ORDER = """
MERGE (c:Customer {id: $customer_id})
MERGE (o:Order {id: $order_id})
  SET o.total_cents = $total_cents, o.currency = $currency,
      o.purchased_at = $purchased_at, o.refunded = $refunded
MERGE (t:Transaction {id: $charge_id})
MERGE (c)-[:PLACED]->(o)
MERGE (o)-[:PAID_WITH]->(t)
"""

_UPSERT_LINK = """
MERGE (p:PaymentMethod {fingerprint: $fingerprint})
WITH p
UNWIND $customer_ids AS cid
  MERGE (c:Customer {id: cid})
  MERGE (c)-[:USED]->(p)
"""


async def seed() -> None:
    config = Neo4jConfig()
    driver = AsyncGraphDatabase.driver(config.uri, auth=(config.username, config.password))
    now = datetime.now(timezone.utc)
    try:
        for constraint in _CONSTRAINTS:
            await driver.execute_query(constraint, database_=config.database)
        for order in ORDERS:
            await driver.execute_query(
                _UPSERT_ORDER,
                parameters_={
                    "customer_id": order.customer_id,
                    "order_id": order.order_id,
                    "charge_id": order.charge_id,
                    "total_cents": order.total_cents,
                    "currency": order.currency,
                    "purchased_at": (now - timedelta(days=order.purchased_days_ago)).isoformat(),
                    "refunded": order.refunded,
                },
                database_=config.database,
            )
        for link in LINKS:
            await driver.execute_query(
                _UPSERT_LINK,
                parameters_={"fingerprint": link.fingerprint, "customer_ids": list(link.customer_ids)},
                database_=config.database,
            )
        print(f"Seeded {len(ORDERS)} orders and {len(LINKS)} linked-account group(s).")
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(seed())
