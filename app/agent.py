# The refund agent: create_agent with two tools and the policy guardrail.
#
# The model drives — it converses, looks orders up, and decides to attempt a
# refund. RefundGuardrail (a wrap_tool_call middleware) enforces the deterministic
# policy at the moment issue_refund is called, so the agent is free to reason but
# cannot issue a refund the policy would reject.

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.guardrail import RefundGuardrail
from app.integrations.graph import GraphStore
from app.integrations.stripe import StripeClient
from app.policy import RefundPolicy
from app.tools import build_tools

_SYSTEM_PROMPT = (
    "You are a refund assistant for an online store. Help the customer with their refund "
    "request in a warm, plain way.\n"
    "- Use order_lookup to understand an order before acting; never guess amounts or dates.\n"
    "- To refund, call issue_refund with the order id (and an amount_cents for a partial refund).\n"
    "- A refund policy vets every issue_refund call and may block or escalate it. If a refund is "
    "not issued, explain the reason to the customer honestly and do not promise it anyway.\n"
    "- Never claim a refund happened unless the tool confirms it. No em dashes."
)


class RefundAgent:
    def __init__(
        self,
        *,
        fact_store: Any,
        stripe: StripeClient,
        policy: RefundPolicy,
        model: BaseChatModel,
        now: Optional[datetime] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
    ) -> None:
        self._facts = fact_store
        self._stripe = stripe
        self._agent = create_agent(
            model=model,
            tools=build_tools(fact_store, stripe),
            system_prompt=_SYSTEM_PROMPT,
            middleware=[RefundGuardrail(fact_store, stripe, policy, now=now)],
            checkpointer=checkpointer or InMemorySaver(),
        )

    @classmethod
    def production(cls, policy: Optional[RefundPolicy] = None) -> "RefundAgent":
        from langchain_fireworks import ChatFireworks

        from app.configs import LLMConfig, Neo4jConfig, StripeConfig

        cfg = LLMConfig()
        return cls(
            fact_store=GraphStore(Neo4jConfig()),
            stripe=StripeClient(StripeConfig()),
            policy=policy or RefundPolicy(),
            model=ChatFireworks(model=cfg.model, temperature=cfg.temperature, api_key=cfg.api_key),  # type: ignore[call-arg]
        )

    async def chat(self, thread_id: str, message: str) -> dict:
        payload = {"messages": [{"role": "user", "content": message}]}
        result = await self._agent.ainvoke(payload, self._thread(thread_id))  # type: ignore[call-overload]
        return self._interpret(result)

    async def resolve(self, thread_id: str, *, approve: bool) -> dict:
        resume: Command = Command(resume={"approve": approve})
        result = await self._agent.ainvoke(resume, self._thread(thread_id))
        return self._interpret(result)

    def astream(self, thread_id: str, message: str):
        """Token/tool-event stream for the chat endpoint."""
        payload = {"messages": [{"role": "user", "content": message}]}
        return self._agent.astream(payload, self._thread(thread_id), stream_mode="messages")  # type: ignore[call-overload]

    async def verify(self) -> None:
        await self._facts.verify()

    async def aclose(self) -> None:
        await self._stripe.aclose()
        await self._facts.aclose()

    @staticmethod
    def _thread(thread_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _interpret(result: dict) -> dict:
        interrupts = result.get("__interrupt__")
        if interrupts:
            return {"status": "escalated", "review": getattr(interrupts[0], "value", interrupts[0])}
        messages = result.get("messages", [])
        reply = messages[-1].content if messages else ""
        return {"status": "replied", "reply": reply}
