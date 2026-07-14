# Entry point for `langgraph dev` (LangGraph server + Studio).
#
# The server provides persistence, so this graph is compiled WITHOUT a
# checkpointer (that's what enables interrupt/resume for the escalation review in
# Studio). It runs on the in-memory graph + a fake Stripe transport over the
# sample dataset, so a demo needs only FIREWORKS_API_KEY and LANGSMITH_API_KEY,
# not real Stripe or Neo4j. Try: "refund order SO-10432", "refund SO-10440"
# (escalates), "refund SO-10377" (disputed, blocked).

from langchain_fireworks import ChatFireworks

from app.agent import build_agent
from app.configs import LLMConfig, StripeConfig
from app.integrations.stripe import StripeClient
from app.policy import RefundPolicy
from tests.fakes import FakeStripe, InMemoryGraphStore

_cfg = LLMConfig()

graph = build_agent(
    model=ChatFireworks(model=_cfg.model, temperature=_cfg.temperature, api_key=_cfg.api_key),  # type: ignore[call-arg]
    fact_store=InMemoryGraphStore(),
    stripe=StripeClient(StripeConfig(api_key="sk_demo_stub"), transport=FakeStripe().transport),
    policy=RefundPolicy(),
)
