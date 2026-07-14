# The guardrail is the safety-critical piece, so it's tested directly: build a
# ToolCallRequest for issue_refund, hand it a fake handler, and assert the policy
# lets it through, blocks it, or escalates. No LLM involved.

from __future__ import annotations

import app.guardrail as guardrail_mod
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest

from app.sample_data import (
    ORDER_CLEAN,
    ORDER_DISPUTED,
    ORDER_FRAUD_RING,
    ORDER_OUT_OF_WINDOW,
    ORDER_PARTIALLY_REFUNDED,
    ORDER_SERIAL_REFUNDER,
)


def _request(order_id: str, amount_cents=None, reason=None, name="issue_refund") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": name, "args": {"order_id": order_id, "amount_cents": amount_cents, "reason": reason}, "id": "call_1"},
        tool=None,
        state={},
        runtime=None,
    )


async def _handler(request: ToolCallRequest) -> ToolMessage:
    # Stands in for the real issue_refund tool.
    return ToolMessage(content="EXECUTED", tool_call_id=request.tool_call["id"])


async def test_non_refund_tool_passes_through(guardrail):
    result = await guardrail.awrap_tool_call(_request(ORDER_CLEAN, name="order_lookup"), _handler)
    assert result.content == "EXECUTED"


async def test_clean_refund_is_allowed(guardrail):
    result = await guardrail.awrap_tool_call(_request(ORDER_CLEAN), _handler)
    assert result.content == "EXECUTED"


async def test_disputed_is_blocked(guardrail):
    result = await guardrail.awrap_tool_call(_request(ORDER_DISPUTED), _handler)
    assert "not issued" in result.content
    assert "dispute" in result.content


async def test_out_of_window_is_blocked(guardrail):
    result = await guardrail.awrap_tool_call(_request(ORDER_OUT_OF_WINDOW), _handler)
    assert "not issued" in result.content
    assert "window" in result.content


async def test_over_remaining_is_blocked(guardrail):
    # 2500 remains on the partially-refunded charge; asking for 3000 is refused.
    result = await guardrail.awrap_tool_call(_request(ORDER_PARTIALLY_REFUNDED, amount_cents=3_000), _handler)
    assert "not issued" in result.content


async def test_partial_within_remaining_is_allowed(guardrail):
    result = await guardrail.awrap_tool_call(_request(ORDER_PARTIALLY_REFUNDED, amount_cents=2_500), _handler)
    assert result.content == "EXECUTED"


async def test_unknown_order_is_blocked(guardrail):
    result = await guardrail.awrap_tool_call(_request("SO-00000"), _handler)
    assert "no order" in result.content.lower()


async def test_escalation_approved_by_human_executes(guardrail, monkeypatch):
    monkeypatch.setattr(guardrail_mod, "interrupt", lambda payload: {"approve": True})
    result = await guardrail.awrap_tool_call(_request(ORDER_SERIAL_REFUNDER), _handler)
    assert result.content == "EXECUTED"


async def test_escalation_declined_by_human_blocks(guardrail, monkeypatch):
    monkeypatch.setattr(guardrail_mod, "interrupt", lambda payload: {"approve": False})
    result = await guardrail.awrap_tool_call(_request(ORDER_FRAUD_RING), _handler)
    assert "human reviewer declined" in result.content
