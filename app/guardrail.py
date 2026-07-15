# The guardrail: deterministic policy enforced at the moment the agent calls
# issue_refund. This is the Sierra split made real — the model reasons freely, but
# the irreversible action passes through a rigid gate.
#
# It intercepts issue_refund via wrap_tool_call, independently re-gathers the
# authoritative facts (never trusting what the model gathered), runs policy.evaluate,
# and then:
#   APPROVE  -> let the tool run (the refund goes through)
#   DENY     -> return a ToolMessage; the tool never runs, the model must explain
#   ESCALATE -> interrupt for a human; on resume, approve runs the tool, deny blocks

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.config import get_stream_writer
from langgraph.types import Command, interrupt

from app.facts import gather_facts
from app.integrations.stripe import RefundReason, StripeClient, StripeError
from app.models import Outcome, RefundRequest
from app.policy import RefundPolicy, evaluate

_Handler = Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]


class RefundGuardrail(AgentMiddleware):
    def __init__(self, fact_store: Any, stripe: StripeClient, policy: RefundPolicy, *, now: Optional[datetime] = None) -> None:
        super().__init__()
        self._facts = fact_store
        self._stripe = stripe
        self._policy = policy
        self._now = now

    async def awrap_tool_call(self, request: ToolCallRequest, handler: _Handler) -> ToolMessage | Command:
        if request.tool_call["name"] != "issue_refund":
            return await handler(request)

        args = request.tool_call["args"]
        tool_call_id = request.tool_call["id"] or ""
        order_id = args.get("order_id", "")

        try:
            facts = await gather_facts(self._facts, self._stripe, order_id)
        except StripeError as exc:
            return self._block(tool_call_id, f"could not verify the charge ({exc.message})")
        if facts is None:
            return self._block(tool_call_id, f"no order '{order_id}' was found")

        decision = evaluate(
            RefundRequest(
                request_id=f"req_{uuid.uuid4().hex[:12]}",
                order_id=order_id,
                requested_amount_cents=args.get("amount_cents"),
                reason=_coerce_reason(args.get("reason")),
            ),
            facts,
            self._policy,
            now=self._now,
        )
        _emit_policy(order_id, decision, facts.charge.remaining_refundable_cents)

        if decision.outcome is Outcome.APPROVE:
            return await handler(request)
        if decision.outcome is Outcome.DENY:
            return self._block(tool_call_id, decision.reasons[-1] if decision.reasons else "policy denied")

        review = interrupt({
            "type": "refund_review",
            "order_id": order_id,
            "amount_cents": decision.approved_amount_cents or facts.charge.remaining_refundable_cents,
            "policy_reasons": decision.reasons,
        })
        if _approved(review):
            return await handler(request)
        return self._block(tool_call_id, "a human reviewer declined the refund")

    @staticmethod
    def _block(tool_call_id: str, reason: str) -> ToolMessage:
        # Fed back to the model, which then explains the outcome to the customer.
        return ToolMessage(content=f"Refund not issued: {reason}.", tool_call_id=tool_call_id)


_APPROVE_WORDS = {"approve", "approved", "approve refund", "yes", "y", "true", "ok", "okay", "accept", "accepted", "confirm", "confirmed"}


def _approved(review: Any) -> bool:
    """Interpret a human's resume value flexibly. A guardrail default: anything not
    clearly affirmative is treated as a decline (never approve on ambiguous input)."""
    if isinstance(review, bool):
        return review
    if isinstance(review, dict):
        if "approve" in review:
            return _approved(review["approve"])
        review = review.get("decision") or review.get("action") or review.get("response") or ""
    return str(review).strip().lower() in _APPROVE_WORDS


def _emit_policy(order_id: str, decision: Any, remaining_cents: int) -> None:
    """Surface the deterministic policy decision on the custom stream channel, so
    the UI can show the guardrail's verdict and the rules that fired. A no-op when
    not streaming (e.g. under ainvoke or in tests)."""
    try:
        writer = get_stream_writer()
        if writer is not None:
            writer({"policy": {
                "order_id": order_id,
                "outcome": decision.outcome.value,
                "reasons": decision.reasons,
                "amount_cents": decision.approved_amount_cents or remaining_cents,
            }})
    except Exception:  # noqa: BLE001 - telemetry only; never break the refund path
        pass


def _coerce_reason(value: Any) -> Optional[RefundReason]:
    try:
        return RefundReason(value) if value else None
    except ValueError:
        return None
