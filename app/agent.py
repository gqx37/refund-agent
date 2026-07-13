# The refund agent: a LangGraph state machine wrapped in a class.
#
#   intake -> gather_facts -> evaluate_policy -> {execute | escalate | reply}
#
# Invariant: execute_refund runs only after an APPROVE decision (policy-clean or
# human-approved). The LLM has no Stripe capability at all; it fills intake gaps
# (intake) and phrases the reply (compose_reply), nothing more.

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.integrations.graph import GraphStore
from app.integrations.stripe import RefundCreateParams, RefundReason, StripeClient, StripeError
from app.models import (
    ChargeFacts,
    CustomerRiskFacts,
    Outcome,
    OrderFacts,
    PolicyDecision,
    RefundFacts,
    RefundOutcome,
    RefundRequest,
    RefundState,
)
from app.policy import RefundPolicy, evaluate


class _IntakeExtract(BaseModel):
    reason: Optional[RefundReason] = None
    requested_amount_cents: Optional[int] = Field(None, ge=1)


class RefundAgent:
    INTAKE_SYSTEM = (
        "Extract structured fields from a customer's refund message. Return only what the "
        "customer expressed. Do NOT decide whether a refund is allowed, and do NOT invent an "
        "amount. reason: one of duplicate, fraudulent, requested_by_customer, or null if unclear. "
        "requested_amount_cents: an integer only if the customer named a specific partial amount; "
        "otherwise null (the full amount)."
    )
    REPLY_SYSTEM = (
        "Write a short, warm reply about a refund request. You are given a DECISION already made "
        "by a policy engine; phrase it, never contradict it or promise a refund it did not "
        "approve. Approved: confirm the amount. Denied: give the specific reason, without blame. "
        "Escalated: say a teammate is reviewing. Two or three sentences. No em dashes."
    )

    def __init__(
        self,
        *,
        fact_store: Any,
        stripe: StripeClient,
        policy: RefundPolicy,
        llm: Optional[BaseChatModel] = None,
        now: Optional[datetime] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ) -> None:
        self._facts = fact_store
        self._stripe = stripe
        self._policy = policy
        self._llm = llm
        self._now = now
        self._graph = self._compile(checkpointer or self._default_checkpointer())

    @classmethod
    def production(cls, policy: Optional[RefundPolicy] = None) -> "RefundAgent":
        from langchain_fireworks import ChatFireworks

        from app.configs import LLMConfig, Neo4jConfig, StripeConfig

        cfg = LLMConfig()
        llm = ChatFireworks(model=cfg.model, temperature=cfg.temperature, api_key=cfg.api_key)  # type: ignore[call-arg]
        return cls(
            fact_store=GraphStore(Neo4jConfig()),
            stripe=StripeClient(StripeConfig()),
            policy=policy or RefundPolicy(),
            llm=llm,
        )

    # --- public API --------------------------------------------------------

    async def submit(self, request: RefundRequest) -> RefundOutcome:
        config = {"configurable": {"thread_id": request.request_id}}
        result = await self._graph.ainvoke({"request": request}, config)
        return self._interpret(request.request_id, result)

    async def resolve(self, request_id: str, *, approve: bool, note: Optional[str] = None) -> RefundOutcome:
        config = {"configurable": {"thread_id": request_id}}
        result = await self._graph.ainvoke(Command(resume={"approve": approve, "note": note}), config)
        return self._interpret(request_id, result)

    async def verify(self) -> None:
        await self._facts.verify()

    async def aclose(self) -> None:
        await self._stripe.aclose()
        await self._facts.aclose()

    # --- graph nodes -------------------------------------------------------

    async def _intake(self, state: RefundState) -> dict:
        request = state["request"]
        needs = request.reason is None or request.requested_amount_cents is None
        if self._llm and request.customer_message and needs:
            try:
                extractor = self._llm.with_structured_output(_IntakeExtract)
                result = await extractor.ainvoke(
                    [SystemMessage(content=self.INTAKE_SYSTEM), HumanMessage(content=request.customer_message)]
                )
                extracted = result if isinstance(result, _IntakeExtract) else _IntakeExtract()
                request = request.model_copy(update={
                    "reason": request.reason or extracted.reason,
                    "requested_amount_cents": request.requested_amount_cents or extracted.requested_amount_cents,
                })
            except Exception:
                pass  # extraction is best-effort
        return {"request": request}

    async def _gather_facts(self, state: RefundState) -> dict:
        request = state["request"]

        order = await self._facts.order_facts(request.order_id)
        if order is None:
            return {"decision": _deny("order_not_found", f"No order '{request.order_id}' was found.")}

        risk = await self._facts.customer_risk(order.customer_id)
        if risk is None:
            return {"decision": _deny("customer_not_found", f"No customer '{order.customer_id}' was found.")}

        try:
            charge = await self._stripe.retrieve_charge(order.charge_id)
        except StripeError as exc:
            return {"error": str(exc), "decision": _deny("charge_lookup_failed", exc.message)}

        facts = RefundFacts(
            order=order,
            customer_risk=risk,
            charge=ChargeFacts(
                charge_id=charge.id,
                amount_cents=charge.amount,
                amount_refunded_cents=charge.amount_refunded,
                currency=charge.currency,
                disputed=charge.disputed,
                status=charge.status,
            ),
        )
        return {"facts": facts}

    async def _evaluate_policy(self, state: RefundState) -> dict:
        if state.get("decision") is not None:  # gather_facts already decided
            return {}
        return {"decision": evaluate(state["request"], state["facts"], self._policy, now=self._now)}

    async def _escalate(self, state: RefundState) -> dict:
        request, facts, decision = state["request"], state["facts"], state["decision"]
        amount = request.requested_amount_cents or facts.charge.remaining_refundable_cents

        human = interrupt({
            "type": "refund_review",
            "request_id": request.request_id,
            "order_id": request.order_id,
            "customer_id": facts.order.customer_id,
            "amount_cents": amount,
            "currency": facts.charge.currency,
            "policy_reasons": decision.reasons,
            "customer_message": request.customer_message,
        })
        approve = bool(human.get("approve")) if isinstance(human, dict) else bool(human)
        note = human.get("note") if isinstance(human, dict) else None

        if approve:
            resolved = decision.model_copy(update={
                "outcome": Outcome.APPROVE, "approved_amount_cents": amount,
                "rule_id": "human_approved", "reasons": decision.reasons + ["A human reviewer approved."],
            })
        else:
            resolved = decision.model_copy(update={
                "outcome": Outcome.DENY, "approved_amount_cents": None,
                "rule_id": "human_denied", "reasons": decision.reasons + ["A human reviewer declined."],
            })
        return {"decision": resolved, "human_note": note}

    async def _execute_refund(self, state: RefundState) -> dict:
        request, facts, decision = state["request"], state["facts"], state["decision"]
        if decision.outcome is not Outcome.APPROVE or decision.approved_amount_cents is None:
            return {"error": "execute_refund reached without an APPROVE decision"}
        params = RefundCreateParams(
            charge=facts.charge.charge_id,
            amount=decision.approved_amount_cents,
            reason=request.reason,
            metadata={"request_id": request.request_id, "order_id": request.order_id},
        )
        try:
            refund = await self._stripe.create_refund(params)
            return {"refund": refund.model_dump(mode="json")}
        except StripeError as exc:
            return {"error": str(exc)}

    async def _compose_reply(self, state: RefundState) -> dict:
        decision, refund, error = state.get("decision"), state.get("refund"), state.get("error")

        if error and not refund:
            grounded = f"There was a problem processing the refund: {error}."
        elif decision and decision.outcome is Outcome.APPROVE and refund:
            grounded = f"Approved. Refunded {refund['amount'] / 100:.2f} {refund['currency'].upper()}."
        elif decision and decision.outcome is Outcome.DENY:
            grounded = f"Denied. {decision.reasons[-1] if decision.reasons else ''}".strip()
        else:
            grounded = "This request is being reviewed by a teammate."

        if not self._llm:
            return {"reply": grounded}
        try:
            context = f"Outcome: {decision.outcome.value if decision else 'unknown'}\nSummary: {grounded}"
            reply = await self._llm.ainvoke([SystemMessage(content=self.REPLY_SYSTEM), HumanMessage(content=context)])
            return {"reply": str(reply.content).strip() or grounded}
        except Exception:
            return {"reply": grounded}

    # --- wiring ------------------------------------------------------------

    def _compile(self, checkpointer: BaseCheckpointSaver):
        graph = StateGraph(RefundState)
        graph.add_node("intake", self._intake)
        graph.add_node("gather_facts", self._gather_facts)
        graph.add_node("evaluate_policy", self._evaluate_policy)
        graph.add_node("escalate", self._escalate)
        graph.add_node("execute_refund", self._execute_refund)
        graph.add_node("compose_reply", self._compose_reply)

        graph.add_edge(START, "intake")
        graph.add_edge("intake", "gather_facts")
        graph.add_edge("gather_facts", "evaluate_policy")
        graph.add_conditional_edges(
            "evaluate_policy", _route_after_policy,
            {"execute": "execute_refund", "escalate": "escalate", "compose": "compose_reply"},
        )
        graph.add_conditional_edges(
            "escalate", _route_after_escalate,
            {"execute": "execute_refund", "compose": "compose_reply"},
        )
        graph.add_edge("execute_refund", "compose_reply")
        graph.add_edge("compose_reply", END)
        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _interpret(request_id: str, result: dict[str, Any]) -> RefundOutcome:
        interrupts = result.get("__interrupt__")
        if interrupts:
            return RefundOutcome(
                request_id=request_id, status="escalated",
                review=getattr(interrupts[0], "value", interrupts[0]),
            )
        refund, error = result.get("refund"), result.get("error")
        status = "error" if (error and not refund) else ("approved" if refund else "denied")
        return RefundOutcome(
            request_id=request_id, status=status, decision=result.get("decision"),
            refund=refund, reply=result.get("reply"), error=error,
        )

    @staticmethod
    def _default_checkpointer() -> MemorySaver:
        # Domain types are checkpointed as state; allowlist them so the serde
        # round-trips them silently and stays restricted to types we own.
        types = [RefundRequest, RefundFacts, OrderFacts, CustomerRiskFacts, ChargeFacts, PolicyDecision, Outcome]
        allowlist = [(t.__module__, t.__qualname__) for t in types]
        return MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=allowlist))


def _route_after_policy(state: RefundState) -> str:
    outcome = state["decision"].outcome
    return {"approve": "execute", "escalate": "escalate"}.get(outcome.value, "compose")


def _route_after_escalate(state: RefundState) -> str:
    return "execute" if state["decision"].outcome is Outcome.APPROVE else "compose"


def _deny(rule_id: str, reason: str) -> PolicyDecision:
    return PolicyDecision(outcome=Outcome.DENY, rule_id=rule_id, reasons=[reason])
