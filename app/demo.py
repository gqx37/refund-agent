# app/demo.py

"""Canonical demo dataset — one source of truth for three consumers.

The Neo4j seed script writes it into a real graph, the in-memory stubs serve it
in tests, and the README walks through it. Because all three read the same
fixtures, the scenarios a reviewer runs locally are exactly the ones the test
suite asserts on.

Each scenario is engineered to trip a specific policy branch. `purchased_days_ago`
is resolved to a timestamp relative to "now" whenever it's read, so "3 days ago"
stays 3 days ago no matter when you run it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoOrder:
    order_id: str
    customer_id: str
    charge_id: str
    purchased_days_ago: int
    total_cents: int
    currency: str
    refunded: bool  # historical flag, used only for customer risk scoring


@dataclass(frozen=True)
class DemoCharge:
    charge_id: str
    amount_cents: int
    amount_refunded_cents: int
    disputed: bool
    status: str
    customer_id: str | None


@dataclass(frozen=True)
class DemoLink:
    """A payment method shared across accounts (the linked-account edge)."""

    fingerprint: str
    customer_ids: tuple[str, ...]


# --- Orders (drive the graph: customers, orders, transactions) ---------------
ORDERS: list[DemoOrder] = [
    # Alice: clean customer (4 orders, 1 historical refund => 25% refund rate).
    DemoOrder("order_alice_ok", "cus_alice", "ch_alice_ok", 3, 2_000, "usd", refunded=False),
    DemoOrder("order_alice_old", "cus_alice", "ch_alice_old", 90, 2_000, "usd", refunded=False),
    DemoOrder("order_alice_disputed", "cus_alice", "ch_alice_disputed", 5, 2_000, "usd", refunded=False),
    DemoOrder("order_alice_done", "cus_alice", "ch_alice_done", 4, 2_000, "usd", refunded=True),
    DemoOrder("order_alice_big", "cus_alice", "ch_alice_big", 2, 60_000, "usd", refunded=False),
    # Bob: serial refunder (4 orders, 3 historical refunds => 75% refund rate).
    DemoOrder("order_bob", "cus_bob", "ch_bob", 2, 5_000, "usd", refunded=False),
    DemoOrder("order_bob_r1", "cus_bob", "ch_bob_r1", 40, 5_000, "usd", refunded=True),
    DemoOrder("order_bob_r2", "cus_bob", "ch_bob_r2", 50, 5_000, "usd", refunded=True),
    DemoOrder("order_bob_r3", "cus_bob", "ch_bob_r3", 60, 5_000, "usd", refunded=True),
    # Carol + Dave: fraud ring linked by a shared card. Carol looks clean alone,
    # but Dave's accounts refund heavily => linked-account signal fires on Carol.
    DemoOrder("order_carol", "cus_carol", "ch_carol", 1, 3_000, "usd", refunded=False),
    DemoOrder("order_dave_r1", "cus_dave", "ch_dave_r1", 10, 3_000, "usd", refunded=True),
    DemoOrder("order_dave_r2", "cus_dave", "ch_dave_r2", 20, 3_000, "usd", refunded=True),
]

# --- Charges (money state, served by the Stripe stub) ------------------------
CHARGES: dict[str, DemoCharge] = {
    "ch_alice_ok": DemoCharge("ch_alice_ok", 2_000, 0, False, "succeeded", "cus_alice"),
    "ch_alice_old": DemoCharge("ch_alice_old", 2_000, 0, False, "succeeded", "cus_alice"),
    "ch_alice_disputed": DemoCharge("ch_alice_disputed", 2_000, 0, True, "succeeded", "cus_alice"),
    "ch_alice_done": DemoCharge("ch_alice_done", 2_000, 2_000, False, "succeeded", "cus_alice"),
    "ch_alice_big": DemoCharge("ch_alice_big", 60_000, 0, False, "succeeded", "cus_alice"),
    "ch_bob": DemoCharge("ch_bob", 5_000, 0, False, "succeeded", "cus_bob"),
    "ch_carol": DemoCharge("ch_carol", 3_000, 0, False, "succeeded", "cus_carol"),
}

# --- Linked accounts (shared payment method) ---------------------------------
LINKS: list[DemoLink] = [
    DemoLink("pm_fingerprint_shared", ("cus_carol", "cus_dave")),
]
