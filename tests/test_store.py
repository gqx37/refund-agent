# The SQLite fact store must return the same facts as the in-memory fake the rest
# of the suite runs on. Seed a temp DB from the sample data and compare.

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.integrations.store import SCHEMA, SqliteFactStore
from app.sample_data import (
    CUSTOMERS,
    LINKS,
    ORDER_CLEAN,
    ORDER_FRAUD_RING,
    ORDER_SERIAL_REFUNDER,
    ORDERS,
)
from tests.fakes import InMemoryGraphStore

NOW = datetime(2026, 7, 14, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path) -> SqliteFactStore:
    path = str(tmp_path / "t.db")
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    customers: set[str] = set()
    for o in ORDERS:
        customers.add(o.customer_id)
        conn.execute(
            "INSERT INTO orders VALUES (?,?,?,?,?,?,?)",
            (o.order_id, o.customer_id, o.charge_id,
             (NOW - timedelta(days=o.purchased_days_ago)).isoformat(),
             o.total_cents, o.currency, int(o.refunded)),
        )
    conn.executemany(
        "INSERT INTO customers (id, name, email) VALUES (?,?,?)",
        [(CUSTOMERS[c].id, CUSTOMERS[c].name, CUSTOMERS[c].email) for c in customers],
    )
    for link in LINKS:
        conn.executemany("INSERT INTO payment_methods VALUES (?,?)",
                         [(link.fingerprint, cid) for cid in link.customer_ids])
    conn.commit()
    conn.close()
    return SqliteFactStore(path)


async def test_order_facts_match_the_fake(store):
    mem = InMemoryGraphStore(now=NOW)
    sql_o = await store.order_facts(ORDER_CLEAN)
    mem_o = await mem.order_facts(ORDER_CLEAN)
    assert (sql_o.customer_id, sql_o.charge_id, sql_o.order_total_cents) == (
        mem_o.customer_id, mem_o.charge_id, mem_o.order_total_cents
    )


async def test_serial_refunder_history(store):
    bob = next(o.customer_id for o in ORDERS if o.order_id == ORDER_SERIAL_REFUNDER)
    risk = await store.customer_risk(bob)
    assert (risk.lifetime_order_count, risk.prior_refund_count) == (4, 3)


async def test_linked_account_rate(store):
    carol = next(o.customer_id for o in ORDERS if o.order_id == ORDER_FRAUD_RING)
    risk = await store.customer_risk(carol)
    assert risk.linked_account_refund_rate > 0.6


@pytest.mark.parametrize("typed", [ORDER_CLEAN, ORDER_CLEAN.lower(), ORDER_CLEAN.split("-")[-1]])
async def test_order_lookup_is_forgiving(store, typed):
    order = await store.order_facts(typed)
    assert order is not None and order.order_id == ORDER_CLEAN


async def test_order_carries_customer_identity(store):
    order = await store.order_facts(ORDER_CLEAN)
    assert order.customer_name == "Alice Nguyen"
    assert order.customer_email == "alice.nguyen@example.com"


async def test_find_customers_by_name_and_email(store):
    by_name = await store.find_customers("alice")
    assert any(c.email == "alice.nguyen@example.com" for c in by_name)
    by_email = await store.find_customers("bob.petrov@example.com")
    assert [c.name for c in by_email] == ["Bob Petrov"]
    orders = await store.orders_for_customer(by_email[0].id)
    assert ORDER_SERIAL_REFUNDER in {o.order_id for o in orders}


async def test_unknown_ids_return_none(store):
    assert await store.order_facts("SO-00000") is None
    assert await store.customer_risk("cus_nope") is None
