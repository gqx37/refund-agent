# app/agent/factory.py

"""Composition roots. Two ways to build the service:

  - production: real Stripe (httpx), real Neo4j, real Nemotron on Fireworks.
  - demo: the in-memory stubs + a fake Stripe transport + no LLM, so anyone can
    run the full agent end-to-end with zero keys and zero infra.
"""

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
    resources: list[_Closeable]  # closed on shutdown

    async def aclose(self) -> None:
        for resource in self.resources:
            await resource.aclose()


def build_production_service(policy: RefundPolicy | None = None) -> BuiltService:
    stripe_client = StripeClient(StripeConfig())
    fact_store = Neo4jFactStore(Neo4jConfig())
    llm = build_llm(LLMConfig())
    deps = RefundAgentDeps(
        fact_store=fact_store,
        stripe_tools=build_stripe_tools(stripe_client),
        policy=policy or RefundPolicy(),
        llm=llm,
    )
    return BuiltService(service=RefundAgentService(deps), resources=[stripe_client, fact_store])


def build_demo_service(policy: RefundPolicy | None = None) -> BuiltService:
    """No keys, no infra: in-memory graph + fake Stripe transport, no LLM."""
    stripe_client = StripeClient(
        StripeConfig(api_key="sk_test_stub"), transport=FakeStripe().transport
    )
    fact_store = InMemoryFactStore()
    deps = RefundAgentDeps(
        fact_store=fact_store,
        stripe_tools=build_stripe_tools(stripe_client),
        policy=policy or RefundPolicy(),
        llm=None,
    )
    return BuiltService(service=RefundAgentService(deps), resources=[stripe_client, fact_store])
