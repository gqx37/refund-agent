# The agent's tools, called directly. (Policy enforcement is the guardrail's job,
# tested in test_guardrail; here we check the tools do their own work.)

from __future__ import annotations

from app.sample_data import ORDER_CLEAN, ORDER_DISPUTED, ORDER_FULLY_REFUNDED


async def test_find_customer_lists_their_orders(tools):
    text = await tools["find_customer"].ainvoke({"query": "alice"})
    assert "Alice Nguyen" in text and "alice.nguyen@example.com" in text
    assert ORDER_CLEAN in text


async def test_find_customer_no_match(tools):
    text = await tools["find_customer"].ainvoke({"query": "nobody-here"})
    assert "No customer matched" in text


async def test_list_orders_shows_each_state(tools):
    text = await tools["list_orders"].ainvoke({})
    assert f"- {ORDER_CLEAN}:" in text and "refundable" in text
    assert f"- {ORDER_FULLY_REFUNDED}:" in text and "fully refunded" in text
    assert f"- {ORDER_DISPUTED}:" in text and "disputed" in text


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
