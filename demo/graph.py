# Entry point for `langgraph dev` (LangGraph server + Studio).
#
# The server provides persistence, so this graph is compiled WITHOUT a
# checkpointer (that's what enables interrupt/resume for the escalation review).
# Real everything: SQLite fact store (seed it with `python -m scripts.seed`),
# real Stripe, real model. Try "refund order SO-10432", "refund SO-10440"
# (escalates), "refund SO-10329" (already refunded, blocked).

from langchain_fireworks import ChatFireworks

from app.agent import build_agent
from app.configs import LLMConfig, StoreConfig, StripeConfig
from app.integrations.store import SqliteFactStore
from app.integrations.stripe import StripeClient
from app.policy import RefundPolicy

_cfg = LLMConfig()

graph = build_agent(
    model=ChatFireworks(model=_cfg.model, temperature=_cfg.temperature, api_key=_cfg.api_key),  # type: ignore[call-arg]
    fact_store=SqliteFactStore(StoreConfig().db_path),
    stripe=StripeClient(StripeConfig()),
    policy=RefundPolicy(),
)
