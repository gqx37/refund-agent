# The agent's tools, called directly. (Policy enforcement is the guardrail's job,
# tested in test_guardrail; here we check the tools do their own work.)

from __future__ import annotations

from app.sample_data import ORDER_CLEAN


async def test_order_lookup_summarizes_the_order(tools):
    text = await tools["order_lookup"].ainvoke({"order_id": ORDER_CLEAN})
    assert "refundable" in text
    assert "2000 cents" in text


async def test_order_lookup_unknown_order(tools):
    text = await tools["order_lookup"].ainvoke({"order_id": "SO-00000"})
    assert "No order" in text


async def test_issue_refund_moves_money(tools):
    text = await tools["issue_refund"].ainvoke({"order_id": ORDER_CLEAN, "amount_cents": 500})
    assert "Refunded 5.00 USD" in text
    # the charge now reflects it
    summary = await tools["order_lookup"].ainvoke({"order_id": ORDER_CLEAN})
    assert "500 refunded" in summary
