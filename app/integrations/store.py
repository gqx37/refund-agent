# Embedded SQLite fact store — orders, customers, and shared-payment-method links.
# Runs in-process (no separate DB service), so the whole agent fits on one small
# machine. The lookups are relational (order -> charge -> customer, and a self-join
# for linked accounts), which is what SQL is for; a graph DB here would be the
# over-engineering the design note warns about.

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from app.models import CustomerRiskFacts, OrderFacts

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (id TEXT PRIMARY KEY, email TEXT);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY, customer_id TEXT, charge_id TEXT,
    purchased_at TEXT, total_cents INTEGER, currency TEXT, refunded INTEGER
);
CREATE TABLE IF NOT EXISTS payment_methods (fingerprint TEXT, customer_id TEXT);
"""

# Forgiving lookup: an exact (case-insensitive) id, or the same digits — so
# "SO-10432", "so-10432", and a bare "10432" all resolve to the same order.
_ORDER = """
SELECT id AS order_id, customer_id, charge_id, purchased_at, total_cents, currency
FROM orders WHERE id = :q COLLATE NOCASE OR digits(id) = digits(:q)
LIMIT 1
"""

_OWN = "SELECT COUNT(*) n, COALESCE(SUM(refunded), 0) r FROM orders WHERE customer_id = ?"

# Orders belonging to any customer that shares a payment method with this one.
_LINKED = """
SELECT COUNT(*) n, COALESCE(SUM(o.refunded), 0) r
FROM payment_methods pm
JOIN payment_methods peer ON peer.fingerprint = pm.fingerprint AND peer.customer_id <> pm.customer_id
JOIN orders o ON o.customer_id = peer.customer_id
WHERE pm.customer_id = ?
"""


class SqliteFactStore:
    def __init__(self, db_path: str) -> None:
        self._path = db_path

    async def order_facts(self, order_id: str) -> Optional[OrderFacts]:
        return await asyncio.to_thread(self._order_facts, order_id)

    async def customer_risk(self, customer_id: str) -> Optional[CustomerRiskFacts]:
        return await asyncio.to_thread(self._customer_risk, customer_id)

    async def verify(self) -> None:
        await asyncio.to_thread(lambda: self._connect().execute("SELECT 1").fetchone())

    async def aclose(self) -> None:
        return None

    # --- sync bodies, run off the event loop ------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.create_function("digits", 1, _digits, deterministic=True)
        return conn

    def _order_facts(self, order_id: str) -> Optional[OrderFacts]:
        with self._connect() as conn:
            row = conn.execute(_ORDER, {"q": order_id}).fetchone()
        if row is None:
            return None
        return OrderFacts(
            order_id=row["order_id"],
            customer_id=row["customer_id"],
            charge_id=row["charge_id"],
            purchase_date=_parse_dt(row["purchased_at"]),
            order_total_cents=row["total_cents"],
            currency=row["currency"],
        )

    def _customer_risk(self, customer_id: str) -> Optional[CustomerRiskFacts]:
        with self._connect() as conn:
            own = conn.execute(_OWN, (customer_id,)).fetchone()
            if own["n"] == 0:
                return None
            linked = conn.execute(_LINKED, (customer_id,)).fetchone()
        linked_rate = (linked["r"] / linked["n"]) if linked["n"] else 0.0
        return CustomerRiskFacts(
            customer_id=customer_id,
            lifetime_order_count=own["n"],
            prior_refund_count=own["r"],
            linked_account_refund_rate=linked_rate,
        )


def _digits(value: Any) -> str:
    return "".join(c for c in str(value) if c.isdigit())


def _parse_dt(value: Any) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
