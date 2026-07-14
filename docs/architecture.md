# Architecture

## The shape

A real tool-using agent (`create_agent`) with a deterministic guardrail injected
as middleware. Two ideas:

- **Sierra — declarative guardrails.** The agent is creative in the conversation,
  but the moments that matter (moving money) pass through rigid, deterministic
  business logic. Here that logic is `app/policy.py`, enforced by a `wrap_tool_call`
  middleware at the instant `issue_refund` is called.
- **Model + harness.** A capable open model (Kimi K2.6 on Fireworks) becomes useful
  when you wrap it in tools, grounding, and guardrails. The model drives; the harness
  constrains.

## Components

- **`app/agent.py`** — `create_agent(model, tools=[order_lookup, issue_refund],
  middleware=[RefundGuardrail(...)])`. The model converses, looks orders up, and
  decides when to refund.
- **`app/tools.py`** — the tools. `order_lookup` (read) gives the model situational
  awareness; `issue_refund` (write) performs the refund.
- **`app/guardrail.py`** — `RefundGuardrail(AgentMiddleware)`. Its `awrap_tool_call`
  intercepts `issue_refund`, re-gathers the authoritative facts, runs
  `policy.evaluate`, and returns:
  - **APPROVE** → `await handler(request)` (the refund tool runs)
  - **DENY** → a `ToolMessage` back to the model (the tool never runs; the model
    explains to the customer)
  - **ESCALATE** → `interrupt()` for a human; on resume, approve runs the tool,
    deny blocks it
- **`app/policy.py`** — a pure function of `(request, facts, policy)`: window,
  amount ceiling, no-double-refund, dispute block, customer/linked-account refund
  rate. No I/O, no LLM, fully unit-testable.
- **`app/facts.py`** — `gather_facts(graph, stripe, order_id)`, shared by the tools
  and the guardrail.

## Why the guardrail re-verifies

The guardrail does not trust the context the model gathered. When `issue_refund` is
called it independently reads the order and customer history from SQLite and the
charge from Stripe, then runs the policy against *those* facts. The model can be
wrong, confused, or adversarially prompted; the deterministic gate still holds.

Money truth is Stripe's, never the graph's; the rules are code's, never the model's;
the facts are the graph's, never the policy's.

## Why SQLite, not a graph

The fact lookups are relational — order → charge → customer, and a self-join over a
shared payment-method fingerprint for linked accounts. That's what SQL is for.
Embedded SQLite keeps the whole agent in one process (one small machine, no DB
service to operate); a graph database here would be over-engineering. See
`design-note-neo4j-vs-code.md`, which makes the same argument.

## Reliability

- **Idempotency**: refunds derive a deterministic key from their args, so a retry
  replays instead of double-refunding.
- **Version pin**: the Stripe client sends a pinned `Stripe-Version`.
- **Typed errors**: provider errors become a `StripeError` carrying Stripe's
  type/code/param/message.
- **Health split**: liveness is dependency-free; readiness checks the fact store.

## Testability

`RefundAgent` takes its fact store, Stripe client, and model as constructor args.
Tests build it with an in-memory graph, a fake Stripe transport, and a scripted
model, so the full `create_agent` graph runs end-to-end in CI with no keys. The
guardrail is also tested in isolation by constructing a `ToolCallRequest` and a fake
handler — the safety-critical logic is verified without an LLM at all.
