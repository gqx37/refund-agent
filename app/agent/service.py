# app/agent/service.py

"""Run orchestration around the compiled graph.

Separated from graph construction so the API and CLI share one submit/resolve
surface and one response shape. `thread_id` is the request id, so an escalation
can be resumed later against the same run.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from langgraph.types import Command
from pydantic import BaseModel

from app.agent.graph import RefundAgentDeps, build_graph
from app.domain import PolicyDecision, RefundRequest


class RefundOutcome(BaseModel):
    """The single response shape for both a fresh submit and a resume."""

    request_id: str
    status: Literal["approved", "denied", "escalated", "error"]
    decision: Optional[PolicyDecision] = None
    refund: Optional[dict] = None
    reply: Optional[str] = None
    review: Optional[dict] = None  # the reviewer payload, when escalated
    error: Optional[str] = None


class RefundAgentService:
    def __init__(self, deps: RefundAgentDeps) -> None:
        self._graph = build_graph(deps)

    async def submit(self, request: RefundRequest) -> RefundOutcome:
        config = {"configurable": {"thread_id": request.request_id}}
        result = await self._graph.ainvoke({"request": request}, config)
        return self._interpret(request.request_id, result)

    async def resolve(
        self, request_id: str, *, approve: bool, note: Optional[str] = None
    ) -> RefundOutcome:
        """Resume an escalated run with a human reviewer's decision."""
        config = {"configurable": {"thread_id": request_id}}
        result = await self._graph.ainvoke(
            Command(resume={"approve": approve, "note": note}), config
        )
        return self._interpret(request_id, result)

    @staticmethod
    def _interpret(request_id: str, result: dict[str, Any]) -> RefundOutcome:
        # A pending human review surfaces as a LangGraph interrupt.
        interrupts = result.get("__interrupt__")
        if interrupts:
            payload = interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]
            return RefundOutcome(request_id=request_id, status="escalated", review=payload)

        decision: Optional[PolicyDecision] = result.get("decision")
        refund = result.get("refund")
        error = result.get("error")
        reply = result.get("reply")

        if error and not refund:
            status: Literal["approved", "denied", "escalated", "error"] = "error"
        elif refund is not None:
            status = "approved"
        else:
            status = "denied"

        return RefundOutcome(
            request_id=request_id,
            status=status,
            decision=decision,
            refund=refund,
            reply=reply,
            error=error,
        )
