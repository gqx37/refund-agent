# The clean-room Stripe client + tools over the fake transport: charge retrieval,
# refund creation, the over-refund error envelope, and idempotency.

from __future__ import annotations

import pytest

from app.demo import ORDER_CLEAN, ORDERS
from app.integrations.stripe.client import StripeError
from app.integrations.stripe.schemas import RefundCreateParams
from app.integrations.stripe.tools import _idempotency_key

# The charge behind the clean demo order (2000, unrefunded).
CLEAN_CHARGE = next(o.charge_id for o in ORDERS if o.order_id == ORDER_CLEAN)


async def test_charge_retrieve_returns_typed_fields(stripe_tools):
    charge = await stripe_tools.charge_retrieve.ainvoke({"charge": CLEAN_CHARGE})
    assert charge["id"] == CLEAN_CHARGE
    assert charge["amount"] == 2_000
    assert charge["amount_refunded"] == 0
    assert charge["disputed"] is False
    assert charge["status"] == "succeeded"


async def test_charge_retrieve_unknown_raises_stripe_error(stripe_tools):
    with pytest.raises(StripeError) as exc:
        await stripe_tools.charge_retrieve.ainvoke({"charge": "ch_nope"})
    assert exc.value.status_code == 404
    assert exc.value.param == "charge"


async def test_refund_create_moves_money(stripe_tools):
    refund = await stripe_tools.refund_create.ainvoke(
        {"charge": CLEAN_CHARGE, "amount": 500, "reason": "requested_by_customer"}
    )
    assert refund["object"] == "refund"
    assert refund["amount"] == 500
    assert refund["status"] == "succeeded"

    charge = await stripe_tools.charge_retrieve.ainvoke({"charge": CLEAN_CHARGE})
    assert charge["amount_refunded"] == 500


async def test_refund_over_remaining_is_rejected(stripe_tools):
    with pytest.raises(StripeError) as exc:
        await stripe_tools.refund_create.ainvoke({"charge": CLEAN_CHARGE, "amount": 999_999})
    assert exc.value.status_code == 400
    assert exc.value.param == "amount"


async def test_refund_is_idempotent(stripe_tools):
    # Same params => same derived key => Stripe replays, no double refund.
    args = {"charge": CLEAN_CHARGE, "amount": 500, "metadata": {"request_id": "req_x"}}
    first = await stripe_tools.refund_create.ainvoke(dict(args))
    second = await stripe_tools.refund_create.ainvoke(dict(args))
    assert first["id"] == second["id"]

    charge = await stripe_tools.charge_retrieve.ainvoke({"charge": CLEAN_CHARGE})
    assert charge["amount_refunded"] == 500  # applied once, not twice


def test_refund_requires_exactly_one_target():
    with pytest.raises(ValueError):
        RefundCreateParams(charge="ch_1", payment_intent="pi_1")
    with pytest.raises(ValueError):
        RefundCreateParams()


def test_idempotency_key_is_stable_and_param_sensitive():
    a = RefundCreateParams(charge="ch_1", amount=500)
    b = RefundCreateParams(charge="ch_1", amount=500)
    c = RefundCreateParams(charge="ch_1", amount=600)
    assert _idempotency_key(a) == _idempotency_key(b)
    assert _idempotency_key(a) != _idempotency_key(c)
