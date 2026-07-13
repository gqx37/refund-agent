# Run orchestration: submit a request, resolve an escalation. thread_id is the
# request_id, so an escalated run resumes against the same checkpoint.

from __future__ import annotations

from typing import Any, Literal, Optional

from langgraph.types import Command
from pydantic import BaseModel

from app.agent.graph import RefundAgentDeps, build_graph
from app.domain import PolicyDecision, RefundRequest

Status = Literal["approved", "denied", "escalated", "error"]


class RefundOutcome(BaseModel):
    request_id: str
    status: Status
    decision: Optional[PolicyDecision] = None
    refund: Optional[dict] = None
    reply: Optional[str] = None
    review: Optional[dict] = None  # reviewer payload when escalated
    error: Optional[str] = None


class RefundAgentService:
    def __init__(self, deps: RefundAgentDeps) -> None:
        self._graph = build_graph(deps)

    async def submit(self, request: RefundRequest) -> RefundOutcome:
        config = {"configurable": {"thread_id": request.request_id}}
        result = await self._graph.ainvoke({"request": request}, config)
        return self._interpret(request.request_id, result)

    async def resolve(self, request_id: str, *, approve: bool, note: Optional[str] = None) -> RefundOutcome:
        config = {"configurable": {"thread_id": request_id}}
        result = await self._graph.ainvoke(Command(resume={"approve": approve, "note": note}), config)
        return self._interpret(request_id, result)

    @staticmethod
    def _interpret(request_id: str, result: dict[str, Any]) -> RefundOutcome:
        interrupts = result.get("__interrupt__")
        if interrupts:
            payload = getattr(interrupts[0], "value", interrupts[0])
            return RefundOutcome(request_id=request_id, status="escalated", review=payload)

        refund = result.get("refund")
        error = result.get("error")
        status: Status = "error" if (error and not refund) else ("approved" if refund else "denied")
        return RefundOutcome(
            request_id=request_id,
            status=status,
            decision=result.get("decision"),
            refund=refund,
            reply=result.get("reply"),
            error=error,
        )
