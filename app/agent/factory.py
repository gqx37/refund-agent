# Composition roots: production (real Stripe/Neo4j/Fireworks) and demo (stubs, no keys).

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.agent.graph import RefundAgentDeps
from app.agent.llm import build_llm
from app.agent.policy import RefundPolicy
from app.agent.service import RefundAgentService
from app.config import LLMConfig, Neo4jConfig, StripeConfig
from app.integrations.graph.client import Neo4jFactStore
from app.integrations.stripe.client import StripeClient
from app.integrations.stripe.tools import build_stripe_tools
from app.stubs.graph_stub import InMemoryFactStore
from app.stubs.stripe_stub import FakeStripe


class _Closeable(Protocol):
    async def aclose(self) -> None: ...


@dataclass
class BuiltService:
    service: RefundAgentService
    resources: list[_Closeable]

    async def aclose(self) -> None:
        for resource in self.resources:
            await resource.aclose()


def build_production_service(policy: RefundPolicy | None = None) -> BuiltService:
    stripe_client = StripeClient(StripeConfig())
    fact_store = Neo4jFactStore(Neo4jConfig())
    deps = RefundAgentDeps(
        fact_store=fact_store,
        stripe_tools=build_stripe_tools(stripe_client),
        policy=policy or RefundPolicy(),
        llm=build_llm(LLMConfig()),
    )
    return BuiltService(RefundAgentService(deps), [stripe_client, fact_store])


def build_demo_service(policy: RefundPolicy | None = None) -> BuiltService:
    stripe_client = StripeClient(StripeConfig(api_key="sk_test_stub"), transport=FakeStripe().transport)
    fact_store = InMemoryFactStore()
    deps = RefundAgentDeps(
        fact_store=fact_store,
        stripe_tools=build_stripe_tools(stripe_client),
        policy=policy or RefundPolicy(),
        llm=None,
    )
    return BuiltService(RefundAgentService(deps), [stripe_client, fact_store])
