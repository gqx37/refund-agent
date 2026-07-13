# The harness: intake -> gather_facts -> evaluate_policy -> {execute | escalate | reply}.
# Invariant: execute_refund is reachable only from an APPROVE decision (policy-clean
# or human-approved). The LLM is never bound to the refund tool.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from app.agent.policy import RefundPolicy, evaluate
from app.agent.prompts import INTAKE_SYSTEM, REPLY_SYSTEM
from app.agent.state import RefundState
from app.domain import (
    ChargeFacts,
    CustomerRiskFacts,
    Outcome,
    OrderFacts,
    PolicyDecision,
    RefundFacts,
    RefundRequest,
)
from app.integrations.graph.base import FactStore
from app.integrations.stripe.client import StripeError
from app.integrations.stripe.schemas import RefundReason
from app.integrations.stripe.tools import StripeTools

# Domain types are checkpointed as graph state; allowlist them so the serde
# round-trips them silently and stays restricted to types we own.
_DOMAIN_TYPES = [
    RefundRequest, RefundFacts, OrderFacts, CustomerRiskFacts, ChargeFacts, PolicyDecision, Outcome,
]


def _default_checkpointer() -> MemorySaver:
    allowlist = [(t.__module__, t.__qualname__) for t in _DOMAIN_TYPES]
    return MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=allowlist))


@dataclass
class RefundAgentDeps:
    fact_store: FactStore
    stripe_tools: StripeTools
    policy: RefundPolicy
    llm: Optional[BaseChatModel] = None  # optional: the graph runs in tests with no model
    now: Optional[datetime] = None  # injectable for deterministic window checks
    checkpointer: Optional[BaseCheckpointSaver] = None


class _IntakeExtract(BaseModel):
    reason: Optional[RefundReason] = None
    requested_amount_cents: Optional[int] = Field(None, ge=1)


def _format_amount(cents: int, currency: str) -> str:
    return f"{cents / 100:.2f} {currency.upper()}"


def build_graph(deps: RefundAgentDeps):
    async def intake(state: RefundState) -> dict:
        request = state["request"]
        needs = request.reason is None or request.requested_amount_cents is None
        if deps.llm and request.customer_message and needs:
            try:
                extractor = deps.llm.with_structured_output(_IntakeExtract)
                result = await extractor.ainvoke(
                    [SystemMessage(content=INTAKE_SYSTEM), HumanMessage(content=request.customer_message)]
                )
                extracted = result if isinstance(result, _IntakeExtract) else _IntakeExtract()
                request = request.model_copy(
                    update={
                        "reason": request.reason or extracted.reason,
                        "requested_amount_cents": request.requested_amount_cents
                        or extracted.requested_amount_cents,
                    }
                )
            except Exception:
                pass  # extraction is best-effort
        return {"request": request}

    async def gather_facts(state: RefundState) -> dict:
        request = state["request"]

        order = await deps.fact_store.order_facts(request.order_id)
        if order is None:
            return {"decision": _deny("order_not_found", f"No order '{request.order_id}' was found.")}

        risk = await deps.fact_store.customer_risk(order.customer_id)
        if risk is None:
            return {"decision": _deny("customer_not_found", f"No customer '{order.customer_id}' was found.")}

        try:
            charge_json = await deps.stripe_tools.charge_retrieve.ainvoke({"charge": order.charge_id})
        except StripeError as exc:
            return {"error": str(exc), "decision": _deny("charge_lookup_failed", exc.message)}

        charge = ChargeFacts(
            charge_id=charge_json["id"],
            amount_cents=charge_json["amount"],
            amount_refunded_cents=charge_json["amount_refunded"],
            currency=charge_json["currency"],
            disputed=charge_json["disputed"],
            status=charge_json["status"],
        )
        return {"facts": RefundFacts(order=order, customer_risk=risk, charge=charge)}

    async def evaluate_policy(state: RefundState) -> dict:
        if state.get("decision") is not None:  # gather_facts already decided (not found / lookup failed)
            return {}
        return {"decision": evaluate(state["request"], state["facts"], deps.policy, now=deps.now)}

    async def escalate(state: RefundState) -> dict:
        request, facts, decision = state["request"], state["facts"], state["decision"]
        amount = request.requested_amount_cents or facts.charge.remaining_refundable_cents

        human = interrupt(
            {
                "type": "refund_review",
                "request_id": request.request_id,
                "order_id": request.order_id,
                "customer_id": facts.order.customer_id,
                "amount_cents": amount,
                "currency": facts.charge.currency,
                "policy_reasons": decision.reasons,
                "customer_message": request.customer_message,
            }
        )
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

    async def execute_refund(state: RefundState) -> dict:
        request, facts, decision = state["request"], state["facts"], state["decision"]
        if decision.outcome is not Outcome.APPROVE or decision.approved_amount_cents is None:
            return {"error": "execute_refund reached without an APPROVE decision"}

        args: dict = {
            "charge": facts.charge.charge_id,
            "amount": decision.approved_amount_cents,
            "metadata": {"request_id": request.request_id, "order_id": request.order_id},
        }
        if request.reason is not None:
            args["reason"] = request.reason.value
        try:
            return {"refund": await deps.stripe_tools.refund_create.ainvoke(args)}
        except StripeError as exc:
            return {"error": str(exc)}

    async def compose_reply(state: RefundState) -> dict:
        return {"reply": await _compose(state)}

    async def _compose(state: RefundState) -> str:
        decision = state.get("decision")
        refund = state.get("refund")
        error = state.get("error")

        if error and not refund:
            grounded = f"There was a problem processing the refund: {error}."
        elif decision and decision.outcome is Outcome.APPROVE and refund:
            grounded = f"Approved. Refunded {_format_amount(refund['amount'], refund['currency'])}."
        elif decision and decision.outcome is Outcome.DENY:
            grounded = f"Denied. {decision.reasons[-1] if decision.reasons else ''}".strip()
        else:
            grounded = "This request is being reviewed by a teammate."

        if not deps.llm:
            return grounded
        try:
            context = f"Outcome: {decision.outcome.value if decision else 'unknown'}\nSummary: {grounded}"
            reply = await deps.llm.ainvoke([SystemMessage(content=REPLY_SYSTEM), HumanMessage(content=context)])
            return str(reply.content).strip() or grounded
        except Exception:
            return grounded

    def route_after_policy(state: RefundState) -> str:
        outcome = state["decision"].outcome
        return {"approve": "execute", "escalate": "escalate"}.get(outcome.value, "compose")

    def route_after_escalate(state: RefundState) -> str:
        return "execute" if state["decision"].outcome is Outcome.APPROVE else "compose"

    graph = StateGraph(RefundState)
    graph.add_node("intake", intake)
    graph.add_node("gather_facts", gather_facts)
    graph.add_node("evaluate_policy", evaluate_policy)
    graph.add_node("escalate", escalate)
    graph.add_node("execute_refund", execute_refund)
    graph.add_node("compose_reply", compose_reply)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "gather_facts")
    graph.add_edge("gather_facts", "evaluate_policy")
    graph.add_conditional_edges(
        "evaluate_policy", route_after_policy,
        {"execute": "execute_refund", "escalate": "escalate", "compose": "compose_reply"},
    )
    graph.add_conditional_edges(
        "escalate", route_after_escalate,
        {"execute": "execute_refund", "compose": "compose_reply"},
    )
    graph.add_edge("execute_refund", "compose_reply")
    graph.add_edge("compose_reply", END)

    return graph.compile(checkpointer=deps.checkpointer or _default_checkpointer())


def _deny(rule_id: str, reason: str) -> PolicyDecision:
    return PolicyDecision(outcome=Outcome.DENY, rule_id=rule_id, reasons=[reason])
