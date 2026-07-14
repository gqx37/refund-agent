# Seed the SQLite fact store from the sample dataset. Run from the repo root:
#   python -m scripts.seed
#
# If STRIPE_API_KEY is set (use a TEST key), it also creates real Stripe test
# charges and stores their real ids, so the agent looks up and refunds real
# charges you can see in your Stripe dashboard. Without it, the sample charge ids
# are used (fine for wiring, but issue_refund will 404 against real Stripe).
#
# Idempotent for the DB (drops and rebuilds); each run creates fresh Stripe charges.

from __future__ import annotations

import asyncio
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

from app.configs import StoreConfig
from app.integrations.store import SCHEMA
from app.sample_data import CHARGES, CUSTOMERS, LINKS, ORDERS, DemoCharge

load_dotenv()

# Stripe test mode is fine with bursts, but keep a modest cap so ~50 charges
# don't trip rate limits.
_CONCURRENCY = 6


async def _create_charge(http: httpx.AsyncClient, dc: DemoCharge) -> str:
    """Create a real Stripe test charge matching the sample's target state."""
    if dc.disputed:
        # Dispute test token via the legacy Charges API; the dispute lands a few
        # seconds later, so we poll until charge.disputed is true (deterministic demo).
        charge = await _post(http, "/v1/charges", {
            "amount": dc.amount_cents, "currency": "usd", "source": "tok_createDispute",
        })
        charge_id = charge["id"]
        for _ in range(10):
            await asyncio.sleep(3)
            if (await http.get(f"/v1/charges/{charge_id}")).json().get("disputed"):
                break
        return charge_id

    pi = await _post(http, "/v1/payment_intents", {
        "amount": dc.amount_cents,
        "currency": "usd",
        "payment_method": "pm_card_visa",
        "confirm": "true",
        "automatic_payment_methods[enabled]": "true",
        "automatic_payment_methods[allow_redirects]": "never",
    })
    charge_id = pi["latest_charge"]

    if dc.amount_refunded_cents > 0:
        await _post(http, "/v1/refunds", {"charge": charge_id, "amount": dc.amount_refunded_cents})
    return charge_id


async def _post(http: httpx.AsyncClient, path: str, data: dict) -> dict:
    resp = await http.post(path, data=data)
    body = resp.json()
    if not resp.is_success:
        raise RuntimeError(f"Stripe {path} failed: {body.get('error', {}).get('message', body)}")
    return body


async def seed() -> None:
    stripe_key = os.environ.get("STRIPE_API_KEY")
    charge_map: dict[str, str] = {}

    if stripe_key:
        sem = asyncio.Semaphore(_CONCURRENCY)
        async with httpx.AsyncClient(
            base_url="https://api.stripe.com",
            headers={"Authorization": f"Bearer {stripe_key}"},
            timeout=60.0,
        ) as http:
            async def one(sample_id: str, dc: DemoCharge) -> tuple[str, str]:
                async with sem:
                    real_id = await _create_charge(http, dc)
                print(f"  charge {sample_id} -> {real_id}")
                return sample_id, real_id

            print(f"Creating {len(CHARGES)} real Stripe test charges...")
            charge_map = dict(await asyncio.gather(*(one(sid, dc) for sid, dc in CHARGES.items())))
    else:
        print("STRIPE_API_KEY not set: using sample charge ids (issue_refund won't hit real Stripe).")

    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(StoreConfig().db_path)
    try:
        # Drop and recreate so a re-seed always lands on the current schema.
        for table in ("orders", "customers", "payment_methods"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)

        customers: set[str] = set()
        for o in ORDERS:
            customers.add(o.customer_id)
            conn.execute(
                "INSERT INTO orders VALUES (?,?,?,?,?,?,?)",
                (
                    o.order_id, o.customer_id, charge_map.get(o.charge_id, o.charge_id),
                    (now - timedelta(days=o.purchased_days_ago)).isoformat(),
                    o.total_cents, o.currency, int(o.refunded),
                ),
            )
        conn.executemany(
            "INSERT INTO customers (id, name, email) VALUES (?,?,?)",
            [(CUSTOMERS[c].id, CUSTOMERS[c].name, CUSTOMERS[c].email) for c in customers],
        )
        for link in LINKS:
            conn.executemany(
                "INSERT INTO payment_methods VALUES (?,?)",
                [(link.fingerprint, cid) for cid in link.customer_ids],
            )
        conn.commit()
    finally:
        conn.close()
    print(f"Seeded {len(ORDERS)} orders, {len(customers)} customers into {StoreConfig().db_path}.")


if __name__ == "__main__":
    asyncio.run(seed())
