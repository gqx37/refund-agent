# Sample dataset shared by the Neo4j seed script and the tests. purchased_days_ago
# is resolved relative to "now" when read. IDs look like real Stripe/merchant IDs;
# the scenario constants below give the tests readable names for them.

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
    refunded: bool  # historical flag, for customer risk scoring only


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
    fingerprint: str
    customer_ids: tuple[str, ...]


# Customers (opaque, like Stripe's).
_ALICE = "cus_QiT9fT2Ldm"  # clean history
_BOB = "cus_7Rk2Np4Xa9"  # serial refunder
_CAROL = "cus_Nc0Ht3ZbqP"  # looks clean alone
_DAVE = "cus_Ke5Ub8Wme2"  # shares a card with Carol, refunds heavily

# Scenario order numbers (merchant-defined), named for the tests/CLI.
ORDER_CLEAN = "SO-10432"
ORDER_OUT_OF_WINDOW = "SO-10318"
ORDER_DISPUTED = "SO-10377"
ORDER_FULLY_REFUNDED = "SO-10329"
ORDER_HIGH_VALUE = "SO-10440"
ORDER_PARTIALLY_REFUNDED = "SO-10448"
ORDER_SERIAL_REFUNDER = "SO-10401"
ORDER_FRAUD_RING = "SO-10455"

ORDERS: list[DemoOrder] = [
    # Alice: clean (2 of 6 orders historically refunded => 33%).
    DemoOrder(ORDER_CLEAN, _ALICE, "ch_3PqR7aLZ2kFdE1nY8xVtBcM", 3, 2_000, "usd", refunded=False),
    DemoOrder(ORDER_OUT_OF_WINDOW, _ALICE, "ch_3PqR7aLZ2kFdE1nY0jHsKpQ", 90, 2_000, "usd", refunded=False),
    DemoOrder(ORDER_DISPUTED, _ALICE, "ch_3PqR7aLZ2kFdE1nY4wDgRuT", 5, 2_000, "usd", refunded=False),
    DemoOrder(ORDER_FULLY_REFUNDED, _ALICE, "ch_3PqR7aLZ2kFdE1nY6bNmXe2", 4, 2_000, "usd", refunded=True),
    DemoOrder(ORDER_HIGH_VALUE, _ALICE, "ch_3PqR7aLZ2kFdE1nY9cVpLo5", 2, 60_000, "usd", refunded=False),
    # Partially refunded already: 4000 charged, 1500 refunded => 2500 left.
    DemoOrder(ORDER_PARTIALLY_REFUNDED, _ALICE, "ch_3PqR7aLZ2kFdE1nYqZ7yWs3", 6, 4_000, "usd", refunded=True),
    # Bob: 3 of 4 orders historically refunded => 75%.
    DemoOrder(ORDER_SERIAL_REFUNDER, _BOB, "ch_3PqR7aLZ2kFdE1nY2tGhFa8", 2, 5_000, "usd", refunded=False),
    DemoOrder("SO-10233", _BOB, "ch_bob_hist_1", 40, 5_000, "usd", refunded=True),
    DemoOrder("SO-10251", _BOB, "ch_bob_hist_2", 50, 5_000, "usd", refunded=True),
    DemoOrder("SO-10262", _BOB, "ch_bob_hist_3", 60, 5_000, "usd", refunded=True),
    # Carol + Dave: linked by a shared card; Dave's accounts refund heavily.
    DemoOrder(ORDER_FRAUD_RING, _CAROL, "ch_3PqR7aLZ2kFdE1nY5rKjDn4", 1, 3_000, "usd", refunded=False),
    DemoOrder("SO-10188", _DAVE, "ch_dave_hist_1", 10, 3_000, "usd", refunded=True),
    DemoOrder("SO-10195", _DAVE, "ch_dave_hist_2", 20, 3_000, "usd", refunded=True),
]

# Charges served by Stripe. Scenario charges carry their live state; the history
# charges are fully refunded (they back the customers' refund-rate history).
CHARGES: dict[str, DemoCharge] = {
    "ch_3PqR7aLZ2kFdE1nY8xVtBcM": DemoCharge("ch_3PqR7aLZ2kFdE1nY8xVtBcM", 2_000, 0, False, "succeeded", _ALICE),
    "ch_3PqR7aLZ2kFdE1nY0jHsKpQ": DemoCharge("ch_3PqR7aLZ2kFdE1nY0jHsKpQ", 2_000, 0, False, "succeeded", _ALICE),
    "ch_3PqR7aLZ2kFdE1nY4wDgRuT": DemoCharge("ch_3PqR7aLZ2kFdE1nY4wDgRuT", 2_000, 0, True, "succeeded", _ALICE),
    "ch_3PqR7aLZ2kFdE1nY6bNmXe2": DemoCharge("ch_3PqR7aLZ2kFdE1nY6bNmXe2", 2_000, 2_000, False, "succeeded", _ALICE),
    "ch_3PqR7aLZ2kFdE1nY9cVpLo5": DemoCharge("ch_3PqR7aLZ2kFdE1nY9cVpLo5", 60_000, 0, False, "succeeded", _ALICE),
    "ch_3PqR7aLZ2kFdE1nYqZ7yWs3": DemoCharge("ch_3PqR7aLZ2kFdE1nYqZ7yWs3", 4_000, 1_500, False, "succeeded", _ALICE),
    "ch_3PqR7aLZ2kFdE1nY2tGhFa8": DemoCharge("ch_3PqR7aLZ2kFdE1nY2tGhFa8", 5_000, 0, False, "succeeded", _BOB),
    "ch_3PqR7aLZ2kFdE1nY5rKjDn4": DemoCharge("ch_3PqR7aLZ2kFdE1nY5rKjDn4", 3_000, 0, False, "succeeded", _CAROL),
    "ch_bob_hist_1": DemoCharge("ch_bob_hist_1", 5_000, 5_000, False, "succeeded", _BOB),
    "ch_bob_hist_2": DemoCharge("ch_bob_hist_2", 5_000, 5_000, False, "succeeded", _BOB),
    "ch_bob_hist_3": DemoCharge("ch_bob_hist_3", 5_000, 5_000, False, "succeeded", _BOB),
    "ch_dave_hist_1": DemoCharge("ch_dave_hist_1", 3_000, 3_000, False, "succeeded", _DAVE),
    "ch_dave_hist_2": DemoCharge("ch_dave_hist_2", 3_000, 3_000, False, "succeeded", _DAVE),
}

LINKS: list[DemoLink] = [
    DemoLink("pm_1Nx8fingerprintAbc", (_CAROL, _DAVE)),
]
