# The clean-room Stripe client over the fake transport: charge retrieval, refund
# creation, the over-refund error envelope, and idempotency.

from __future__ import annotations

import pytest

from app.integrations.stripe import RefundCreateParams, StripeError, build_stripe_tools
from app.sample_data import ORDER_CLEAN, ORDERS

# The charge behind the clean sample order (2000, unrefunded).
CLEAN_CHARGE = next(o.charge_id for o in ORDERS if o.order_id == ORDER_CLEAN)


async def test_retrieve_charge_returns_typed_fields(stripe_client):
    charge = await stripe_client.retrieve_charge(CLEAN_CHARGE)
    assert charge.id == CLEAN_CHARGE
    assert charge.amount == 2_000
    assert charge.amount_refunded == 0
    assert charge.disputed is False
    assert charge.status == "succeeded"


async def test_retrieve_unknown_charge_raises(stripe_client):
    with pytest.raises(StripeError) as exc:
        await stripe_client.retrieve_charge("ch_nope")
    assert exc.value.status_code == 404
    assert exc.value.param == "charge"


async def test_create_refund_moves_money(stripe_client):
    refund = await stripe_client.create_refund(
        RefundCreateParams(charge=CLEAN_CHARGE, amount=500, reason="requested_by_customer")
    )
    assert refund.amount == 500
    assert refund.status.value == "succeeded"
    charge = await stripe_client.retrieve_charge(CLEAN_CHARGE)
    assert charge.amount_refunded == 500


async def test_refund_over_remaining_is_rejected(stripe_client):
    with pytest.raises(StripeError) as exc:
        await stripe_client.create_refund(RefundCreateParams(charge=CLEAN_CHARGE, amount=999_999))
    assert exc.value.status_code == 400
    assert exc.value.param == "amount"


async def test_refund_is_idempotent(stripe_client):
    # Same params => same derived key => Stripe replays, no double refund.
    params = RefundCreateParams(charge=CLEAN_CHARGE, amount=500, metadata={"request_id": "req_x"})
    first = await stripe_client.create_refund(params)
    second = await stripe_client.create_refund(params)
    assert first.id == second.id
    charge = await stripe_client.retrieve_charge(CLEAN_CHARGE)
    assert charge.amount_refunded == 500  # applied once, not twice


async def test_tools_are_callable(stripe_client):
    tools = build_stripe_tools(stripe_client)
    assert [t.name for t in tools.all] == ["charge_lookup", "issue_refund"]
    charge = await tools.charge_lookup.ainvoke({"charge_id": CLEAN_CHARGE})
    assert charge["amount"] == 2_000


def test_refund_requires_exactly_one_target():
    with pytest.raises(ValueError):
        RefundCreateParams(charge="ch_1", payment_intent="pi_1")
    with pytest.raises(ValueError):
        RefundCreateParams()
