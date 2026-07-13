# Architecture

## The thesis this is built on

Two ideas, one design.

**Sierra — declarative goals and guardrails.** An agent should be creative where
creativity helps and rigid where it must not fail. So procedural knowledge (*how
a refund should be handled*) and hard guardrails (*orders are refundable within
30 days*) are declared **deterministically in code**, abstracted from the model.
The LLM gets flexibility; the business logic gets 100% enforcement.

**Nemotron + LangChain harness.** A near-frontier open model (Nemotron 3 Ultra on
Fireworks) becomes production-useful when you wrap it in a harness: ground it on
domain facts, give it tools, fence it with guardrails. The model is *good enough*;
the value is the harness. This repo is that harness, small and legible.

## The four layers and why they never mix

```
             ┌──────────────────────────────────────────────┐
 customer ──▶│  intake (LLM)  ──▶  gather_facts             │
 message     │                       │  ├─ Neo4j: who/what   │  semantic facts
             │                       │  └─ Stripe: money     │  source of truth
             │                       ▼                       │
             │              evaluate_policy (pure code)      │  guardrails
             │                       │                       │
             │        APPROVE ───────┼──── DENY / ESCALATE   │
             │           │           │        │              │
             │     execute_refund    │   human review        │  money movement
             │        (Stripe)       │   (interrupt/resume)  │  gated on APPROVE
             │           └───────▶ compose_reply (LLM) ─────▶│  phrasing only
             └──────────────────────────────────────────────┘
```

- **Money truth is Stripe's, never the graph's.** The current charge/refund
  balance is always read from Stripe at decision time. The graph never claims to
  know a balance.
- **Rules are code's, never the graph's.** We deliberately do **not** store
  policy in Neo4j and ask an LLM to read it back with Text2Cypher — that's using
  a graph database to execute a control flow, which is the wrong tool. Rules are
  a pure Python function (`app/agent/policy.py`).
- **Facts are the graph's, never code's.** Who the customer is, what they ordered,
  which charge paid for it, and which accounts share a card — relational,
  traversal-shaped data a graph answers well and a policy function shouldn't hold.
- **The model decides nothing it can act on.** It fills intake gaps and phrases
  the reply. It is never bound to the refund tool and never sits on an edge into
  `execute_refund`.

## Why Text2Cypher is guarded and off the decision path

The known lookups the decision needs (order facts, customer risk) are **fixed
parameterized Cypher** in `app/integrations/graph/schema.py`. You never ask an LLM
to regenerate a query whose shape you already know — that adds latency, cost, and
an injection surface for zero benefit.

Text2Cypher earns its place only for **open-ended, read-only** questions where the
query shape genuinely isn't known ahead of time (e.g. a human investigating
"which accounts share a card with this customer and refund more than half their
orders?"). Even then it is doubly guarded: the prompt forbids write clauses, and
the store rejects any statement containing one and forces READ routing at the
driver.

## The refund-authorization invariant

`execute_refund` has exactly two in-edges, both from an `APPROVE` decision:

1. `evaluate_policy` → APPROVE (policy-clean), or
2. `escalate` → a human approved the review.

There is no path from the LLM to `execute_refund`. The refund tool is built but
never handed to the model (`app/integrations/stripe/tools.py`); only the
deterministic node invokes it, and only after checking the decision. This is the
whole safety argument, and it's asserted in `tests/test_graph_flow.py`.

## Human-in-the-loop

An `ESCALATE` decision calls LangGraph's `interrupt()`, which pauses the run and
surfaces a review payload (amount, reasons, customer message). A reviewer answers
via `POST /v1/refund-requests/{id}/resolve`, and the *same run* resumes from the
interrupt with their decision — approve routes to `execute_refund`, deny routes
to `compose_reply`. State is durable in the checkpointer (in-memory here; Postgres
in production).

## Reliability details worth calling out

- **Idempotency:** refunds derive a deterministic `Idempotency-Key` from their
  arguments, so a retried request replays the original response instead of
  double-refunding. Tested against the fake Stripe.
- **API-version pinning:** the Stripe client sends a pinned `Stripe-Version`
  header so a provider-side upgrade can't silently reshape responses on Stripe's
  release schedule instead of ours.
- **Typed errors:** provider errors become a `StripeError` carrying Stripe's own
  `type`/`code`/`param`/`message`, so failures are legible end to end.
- **Health split:** liveness (`/health`) is dependency-free so a Neo4j outage
  never restarts the machine; readiness (`/health/ready`) reports 503 so the load
  balancer stops routing without a restart.

## Testability

The graph depends on a `FactStore` protocol and takes an injected Stripe transport
and an optional LLM. So the production wiring (Neo4j + httpx-to-Stripe + Fireworks)
and the test wiring (in-memory graph + fake Stripe + no model) are the same graph.
The entire agent — intake, facts, policy, refund, escalation, resume — runs in
CI with no API keys and no database.
