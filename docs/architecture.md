# Architecture

## Layers

Four concerns, kept separate:

- **Guardrails** (`app/policy.py`): whether a refund is allowed. A pure
  function of `(request, facts, policy)` — no I/O, no LLM, no clock except the one
  passed in — so it's fully unit-testable and its verdict is reproducible.
- **Facts** (Neo4j): who the customer is, what they ordered, which charge paid for
  it, which accounts share a payment method. Traversal-shaped data.
- **Money** (Stripe): the current charge and refund balances, read at decision time.
- **Reasoning** (Nemotron 3 Ultra on Fireworks): fills intake gaps and phrases the
  reply. Nothing it produces authorizes an action.

Boundaries that don't move: money truth is Stripe's, never the graph's; rules are
code's, never the graph's; facts are the graph's, never the policy's.

## The refund-authorization invariant

`execute_refund` has two in-edges, both from an `approve` decision:

1. `evaluate_policy` → approve (policy-clean), or
2. `escalate` → a human approved.

There is no path from the LLM to `execute_refund`. The model is never given the
`StripeClient`; only the deterministic node calls `create_refund`, after checking
the decision. Asserted in `tests/test_agent.py`.

## Fixed lookups vs Text2Cypher

The lookups the decision needs (order facts, customer risk) are parameterized
Cypher in `app/integrations/graph.py`. You don't ask an LLM to regenerate a query
whose shape you already know — it adds latency, cost, and an injection surface for
nothing. See `design-note-neo4j-vs-code.md`.

## Human-in-the-loop

An `escalate` decision calls LangGraph's `interrupt()`, pausing the run with a
review payload. A reviewer answers via `POST /v1/refund-requests/{id}/resolve` and
the same run resumes from the interrupt — approve routes to `execute_refund`, deny
to the reply. State is durable in the checkpointer (in-memory here; Postgres in
production).

## Reliability

- **Idempotency**: refunds derive a deterministic key from their args, so a retry
  replays instead of double-refunding.
- **Version pin**: the client sends a pinned `Stripe-Version` so a provider upgrade
  can't reshape responses on Stripe's schedule.
- **Typed errors**: provider errors become a `StripeError` carrying Stripe's
  type/code/param/message.
- **Health split**: liveness is dependency-free (a Neo4j outage won't restart the
  machine); readiness returns 503 so the load balancer stops routing.

## Testability

`RefundAgent` takes its fact store, Stripe client, and LLM as constructor args, so
production wiring (Neo4j + httpx + Fireworks) and test wiring (in-memory graph +
fake Stripe transport + no model) build the same agent. The whole thing runs in CI
with no keys and no database.
