"""Policy-constrained refund agent for Stripe.

The Sierra split, made literal:
  - procedural knowledge + guardrails  -> deterministic code (app/agent/policy.py)
  - semantic facts                     -> Neo4j graph (app/integrations/graph)
  - money state (source of truth)      -> Stripe (app/integrations/stripe)
  - reasoning core                     -> Nemotron 3 Ultra inside a LangGraph harness
"""

__version__ = "0.1.0"
