# Sample dataset shared by the seed script and the tests. purchased_days_ago is
# resolved relative to "now" when read. IDs look like real Stripe/merchant IDs;
# the scenario constants below give the tests readable names for a handful of
# curated cases, and a generated pool fills the store out to ~50 orders across
# every state (refundable, partially refunded, fully refunded, disputed) so
# several people can try refunds without re-seeding.

from __future__ import annotations

import random
import string
from dataclasses import dataclass


@dataclass(frozen=True)
class DemoCustomer:
    id: str
    name: str
    email: str


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


# --- Curated customers (opaque ids, like Stripe's) --------------------------
_ALICE = DemoCustomer("cus_QiT9fT2Ldm", "Alice Carter", "alice.carter@example.com")  # clean history
_BOB = DemoCustomer("cus_7Rk2Np4Xa9", "Bob Petrov", "bob.petrov@example.com")  # serial refunder
_CAROL = DemoCustomer("cus_Nc0Ht3ZbqP", "Carol Diaz", "carol.diaz@example.com")  # looks clean alone
_DAVE = DemoCustomer("cus_Ke5Ub8Wme2", "Dave Okafor", "dave.okafor@example.com")  # shares Carol's card

# Scenario order numbers (merchant-defined), named for the tests.
ORDER_CLEAN = "SO-10432"
ORDER_OUT_OF_WINDOW = "SO-10318"
ORDER_DISPUTED = "SO-10377"
ORDER_FULLY_REFUNDED = "SO-10329"
ORDER_HIGH_VALUE = "SO-10440"
ORDER_PARTIALLY_REFUNDED = "SO-10448"
ORDER_SERIAL_REFUNDER = "SO-10401"
ORDER_FRAUD_RING = "SO-10455"

_CURATED_ORDERS: list[DemoOrder] = [
    # Alice: clean (2 of 6 orders historically refunded => 33%).
    DemoOrder(ORDER_CLEAN, _ALICE.id, "ch_3PqR7aLZ2kFdE1nY8xVtBcM", 3, 2_000, "usd", refunded=False),
    DemoOrder(ORDER_OUT_OF_WINDOW, _ALICE.id, "ch_3PqR7aLZ2kFdE1nY0jHsKpQ", 90, 2_000, "usd", refunded=False),
    DemoOrder(ORDER_DISPUTED, _ALICE.id, "ch_3PqR7aLZ2kFdE1nY4wDgRuT", 5, 2_000, "usd", refunded=False),
    DemoOrder(ORDER_FULLY_REFUNDED, _ALICE.id, "ch_3PqR7aLZ2kFdE1nY6bNmXe2", 4, 2_000, "usd", refunded=True),
    DemoOrder(ORDER_HIGH_VALUE, _ALICE.id, "ch_3PqR7aLZ2kFdE1nY9cVpLo5", 2, 60_000, "usd", refunded=False),
    # Partially refunded already: 4000 charged, 1500 refunded => 2500 left.
    DemoOrder(ORDER_PARTIALLY_REFUNDED, _ALICE.id, "ch_3PqR7aLZ2kFdE1nYqZ7yWs3", 6, 4_000, "usd", refunded=True),
    # Bob: 3 of 4 orders historically refunded => 75%.
    DemoOrder(ORDER_SERIAL_REFUNDER, _BOB.id, "ch_3PqR7aLZ2kFdE1nY2tGhFa8", 2, 5_000, "usd", refunded=False),
    DemoOrder("SO-10233", _BOB.id, "ch_bob_hist_1", 40, 5_000, "usd", refunded=True),
    DemoOrder("SO-10251", _BOB.id, "ch_bob_hist_2", 50, 5_000, "usd", refunded=True),
    DemoOrder("SO-10262", _BOB.id, "ch_bob_hist_3", 60, 5_000, "usd", refunded=True),
    # Carol + Dave: linked by a shared card; Dave's accounts refund heavily.
    DemoOrder(ORDER_FRAUD_RING, _CAROL.id, "ch_3PqR7aLZ2kFdE1nY5rKjDn4", 1, 3_000, "usd", refunded=False),
    DemoOrder("SO-10188", _DAVE.id, "ch_dave_hist_1", 10, 3_000, "usd", refunded=True),
    DemoOrder("SO-10195", _DAVE.id, "ch_dave_hist_2", 20, 3_000, "usd", refunded=True),
]

# Charges served by Stripe. Scenario charges carry their live state; the history
# charges are fully refunded (they back the customers' refund-rate history).
_CURATED_CHARGES: dict[str, DemoCharge] = {
    "ch_3PqR7aLZ2kFdE1nY8xVtBcM": DemoCharge("ch_3PqR7aLZ2kFdE1nY8xVtBcM", 2_000, 0, False, "succeeded", _ALICE.id),
    "ch_3PqR7aLZ2kFdE1nY0jHsKpQ": DemoCharge("ch_3PqR7aLZ2kFdE1nY0jHsKpQ", 2_000, 0, False, "succeeded", _ALICE.id),
    "ch_3PqR7aLZ2kFdE1nY4wDgRuT": DemoCharge("ch_3PqR7aLZ2kFdE1nY4wDgRuT", 2_000, 0, True, "succeeded", _ALICE.id),
    "ch_3PqR7aLZ2kFdE1nY6bNmXe2": DemoCharge("ch_3PqR7aLZ2kFdE1nY6bNmXe2", 2_000, 2_000, False, "succeeded", _ALICE.id),
    "ch_3PqR7aLZ2kFdE1nY9cVpLo5": DemoCharge("ch_3PqR7aLZ2kFdE1nY9cVpLo5", 60_000, 0, False, "succeeded", _ALICE.id),
    "ch_3PqR7aLZ2kFdE1nYqZ7yWs3": DemoCharge("ch_3PqR7aLZ2kFdE1nYqZ7yWs3", 4_000, 1_500, False, "succeeded", _ALICE.id),
    "ch_3PqR7aLZ2kFdE1nY2tGhFa8": DemoCharge("ch_3PqR7aLZ2kFdE1nY2tGhFa8", 5_000, 0, False, "succeeded", _BOB.id),
    "ch_3PqR7aLZ2kFdE1nY5rKjDn4": DemoCharge("ch_3PqR7aLZ2kFdE1nY5rKjDn4", 3_000, 0, False, "succeeded", _CAROL.id),
    "ch_bob_hist_1": DemoCharge("ch_bob_hist_1", 5_000, 5_000, False, "succeeded", _BOB.id),
    "ch_bob_hist_2": DemoCharge("ch_bob_hist_2", 5_000, 5_000, False, "succeeded", _BOB.id),
    "ch_bob_hist_3": DemoCharge("ch_bob_hist_3", 5_000, 5_000, False, "succeeded", _BOB.id),
    "ch_dave_hist_1": DemoCharge("ch_dave_hist_1", 3_000, 3_000, False, "succeeded", _DAVE.id),
    "ch_dave_hist_2": DemoCharge("ch_dave_hist_2", 3_000, 3_000, False, "succeeded", _DAVE.id),
}

LINKS: list[DemoLink] = [
    DemoLink("pm_1Nx8fingerprintAbc", (_CAROL.id, _DAVE.id)),
]

# --- Generated pool: many single-order customers across every state ---------
_FIRST = [
    "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason", "Isabella", "Lucas",
    "Mia", "Oliver", "Amelia", "Elijah", "Harper", "James", "Evelyn", "Benjamin", "Abigail", "Henry",
    "Emily", "Alexander", "Ella", "Sebastian", "Grace", "Jack", "Chloe", "Owen", "Victoria", "Daniel",
    "Aria", "Matthew", "Scarlett", "Samuel", "Zoe", "David", "Lily", "Joseph", "Hannah", "Leo",
]
_LAST = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Reed", "Hill", "Flores",
]

# How many generated orders land in each state. Weighted toward refundable so
# there is always plenty to refund.
_STATE_PLAN = ["refundable"] * 22 + ["partial"] * 7 + ["fully"] * 4 + ["disputed"] * 4
_AMOUNTS = [1_500, 2_000, 2_500, 3_000, 3_500, 4_500, 6_000, 7_500, 9_000, 12_000]


def _generate(start_order_no: int) -> tuple[list[DemoOrder], dict[str, DemoCharge], dict[str, DemoCustomer]]:
    rng = random.Random(28)  # fixed seed => same pool every run
    states = list(_STATE_PLAN)
    rng.shuffle(states)
    orders: list[DemoOrder] = []
    charges: dict[str, DemoCharge] = {}
    customers: dict[str, DemoCustomer] = {}

    for i, state in enumerate(states):
        first = _FIRST[i % len(_FIRST)]
        last = _LAST[(i * 7 + 3) % len(_LAST)]
        cus_id = "cus_" + "".join(rng.choices(string.ascii_letters + string.digits, k=10))
        customers[cus_id] = DemoCustomer(cus_id, f"{first} {last}", f"{first}.{last}@example.com".lower())

        order_id = f"SO-{start_order_no + i}"
        charge_id = f"ch_gen_{i:04d}"
        amount = rng.choice(_AMOUNTS)
        days = rng.randint(1, 25)

        if state == "partial":
            refunded_cents = (amount * 2 // 5 // 100) * 100  # ~40%, rounded to the dollar
            disputed, refunded_flag = False, False
        elif state == "fully":
            refunded_cents, disputed, refunded_flag = amount, False, True
        elif state == "disputed":
            refunded_cents, disputed, refunded_flag = 0, True, False
        else:  # refundable
            refunded_cents, disputed, refunded_flag = 0, False, False

        orders.append(DemoOrder(order_id, cus_id, charge_id, days, amount, "usd", refunded=refunded_flag))
        charges[charge_id] = DemoCharge(charge_id, amount, refunded_cents, disputed, "succeeded", cus_id)

    return orders, charges, customers


_gen_orders, _gen_charges, _gen_customers = _generate(start_order_no=10_500)

ORDERS: list[DemoOrder] = _CURATED_ORDERS + _gen_orders
CHARGES: dict[str, DemoCharge] = {**_CURATED_CHARGES, **_gen_charges}
CUSTOMERS: dict[str, DemoCustomer] = {
    c.id: c for c in (_ALICE, _BOB, _CAROL, _DAVE)
} | _gen_customers
