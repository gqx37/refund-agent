# Policy-Constrained Refund Agent (Stripe)

A real tool-using agent that handles customer refunds, with a **deterministic
policy guardrail wired in as middleware**. The model reasons and acts freely; the
guardrail runs at the moment it tries to move money and can block or escalate the
refund. That's the Sierra split — creative in the conversation, rigid in the
moments that matter.

```
                 ┌──────── create_agent loop ────────┐
  customer ─▶ model ⇄ tools:  find_customer (read)    │
                    │         list_orders  (read)      │
                    │         order_lookup (read)      │
                    │         issue_refund (write) ──┐ │
                    │                                │ │
                    │        RefundGuardrail.wrap_tool_call
                    │        runs policy.evaluate() ─┤ │
                    │          approve → refund      │ │
                    │          deny    → tool blocked│ │
                    │          escalate→ human review┘ │
                 └────────────────────────────────────┘
```

- **The agent** (`app/agent.py`): `create_agent(model, tools, middleware=[RefundGuardrail()])`.
- **The tools** (`app/tools.py`): `find_customer` and `list_orders` (find people / see state),
  `order_lookup`, `issue_refund` — real LangChain tools. The read tools surface live Stripe state.
- **The guardrail** (`app/guardrail.py`): a `wrap_tool_call` middleware that intercepts
  `issue_refund`, independently re-gathers the facts, runs the policy, and allows,
  blocks, or interrupts for a human.
- **The policy** (`app/policy.py`): a pure function — window, amount ceiling,
  no-double-refund, dispute block, fraud-rate escalation.
- **The facts** (`app/integrations/store.py`): embedded **SQLite** (orders, customers,
  shared-card links). Relational lookups, in-process — no separate DB service, so
  the whole agent fits on one small machine. A graph DB here would be over-engineering
  (see `docs/design-note-neo4j-vs-code.md`).
- **The model**: Kimi K2.6 on Fireworks.

The guardrail doesn't trust what the model gathered — it re-verifies against SQLite
and Stripe at the instant of the action.

## Try it live

**[refund-agent.fly.dev](https://refund-agent.fly.dev)** — a hosted chat UI, one URL, no setup.
Every turn shows the agent's tool calls and the guardrail decision (approve / deny /
escalate); on an escalation you get Approve / Deny buttons. Refunds are real Stripe
**test mode**. Try: *"I'm Alice Nguyen, show my orders"*, *"refund SO-10432, it arrived
broken"*, *"refund SO-10440 in full"* (escalates), *"refund SO-10377"* (disputed, blocked).

Runs as one small Fly machine — FastAPI serving both the API and the UI, SQLite on a
tiny volume, suspends to ~$0 when idle.

## Run the tests, no keys

Everything runs on fakes (a scripted model, a fake Stripe transport, an in-memory
store), so the suite needs no keys and no services:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest        # policy, guardrail, tools, Stripe client, SQLite store, full agent
```

## Chat with it for real (LangGraph Studio)

Real model, real Stripe, real SQLite — no fakes. `langgraph dev` serves the agent
and opens LangGraph Studio (a chat + trace UI), so there's no frontend to build.

```bash
cp .env.example .env          # FIREWORKS_API_KEY, STRIPE_API_KEY (test), LANGSMITH_API_KEY
python -m scripts.seed        # builds the SQLite store + creates real Stripe test charges
langgraph dev                 # opens Studio at .../studio/?baseUrl=http://127.0.0.1:2024
```

Try:
- `I'm Alice Nguyen, can you pull up my orders?` — finds her by name, lists live state
- `refund order SO-10432, it arrived broken` — looks it up, issues a real $20 refund
- `refund SO-10440` — escalates (over the ceiling); approve or deny in Studio
- `refund SO-10329` — blocked (already fully refunded)

The store holds ~50 orders across every state (refundable, partially/fully refunded,
disputed), with named customers, so several people can try refunds without re-seeding.
The refunds show up in your Stripe test dashboard. Each turn's trace shows the model
calling the read tools then `issue_refund`, and the guardrail allowing/blocking it.

## HTTP service

`app/main.py` is a FastAPI surface (`POST /v1/chat`, `/v1/chat/{id}/resume`, and the
`/health` split) — one process, SQLite embedded, deployable as a single small machine.

## Layout

```
app/
  agent.py            RefundAgent (create_agent + guardrail)
  guardrail.py        RefundGuardrail — the wrap_tool_call policy middleware
  policy.py           the deterministic guardrails (pure function)
  tools.py            find_customer, list_orders, order_lookup, issue_refund
  facts.py            gather_facts (store + Stripe)
  models.py           domain models
  main.py             FastAPI (chat + resume + health)
  configs/            one settings class per file
  integrations/
    stripe/           schemas.py · client.py
    store.py          SqliteFactStore (embedded)
  sample_data.py
demo/graph.py         langgraph dev entry point
scripts/seed.py       seed SQLite + create real Stripe test charges
tests/                policy · guardrail · tools · stripe · store · full agent · fakes
```

MIT. Portfolio project; not affiliated with Stripe, Sierra, or Fireworks.
