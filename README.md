# Policy-Constrained Refund Agent (Stripe)

A real tool-using agent that handles customer refunds, with a **deterministic
policy guardrail wired in as middleware**. The model reasons and acts freely; the
guardrail runs at the moment it tries to move money and can block or escalate the
refund. That's the Sierra split — creative in the conversation, rigid in the
moments that matter.

```
                 ┌──────── create_agent loop ────────┐
  customer ─▶ model ⇄ tools:  order_lookup (read)     │
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
- **The tools** (`app/tools.py`): `order_lookup`, `issue_refund` — real LangChain tools.
- **The guardrail** (`app/guardrail.py`): a `wrap_tool_call` middleware that
  intercepts `issue_refund`, independently re-gathers the authoritative facts, runs
  the deterministic policy, and lets the refund through, blocks it, or interrupts
  for a human.
- **The policy** (`app/policy.py`): a pure function — refund window, amount ceiling,
  no-double-refund, dispute block, fraud-rate escalation.
- **The model**: Nemotron 3 Ultra on Fireworks.

The guardrail doesn't trust what the model gathered — it re-verifies against Neo4j
(order + customer history) and Stripe (money) at the instant of the action.

## Run the tests, no keys

The agent runs on fakes (a scripted model, a fake Stripe transport, an in-memory
graph), so the suite needs no keys, no network, no Postgres:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest        # 31 tests: policy, guardrail, tools, Stripe client, full agent flow
```

`test_guardrail.py` exercises the safety-critical path directly (allow / block /
escalate); `test_agent.py` drives the real `create_agent` graph end-to-end with a
scripted model and asserts a disputed charge is never refunded.

## Run it for real

```bash
cp .env.example .env      # FIREWORKS_API_KEY, STRIPE_API_KEY, NEO4J_*
python -m scripts.seed_graph
uvicorn app.main:app
```

```bash
curl -sX POST localhost:8080/v1/chat -H 'content-type: application/json' \
  -d '{"message":"I want a refund on order SO-10432, it arrived broken"}'

# answer an escalation (human in the loop)
curl -sX POST localhost:8080/v1/chat/THREAD_ID/resume \
  -H 'content-type: application/json' -d '{"approve":true}'
```

`GET /health` (liveness) · `GET /health/ready` (readiness).

## Design choices

- **The policy is enforced, not orchestrated.** Rather than a hand-wired graph
  that calls the LLM only for text, the LLM is a real agent; the deterministic
  policy is injected as `wrap_tool_call` middleware. Agentic where it helps,
  rigid where it must be.
- **Independent verification.** The guardrail re-fetches facts and never trusts the
  model's gathered context before allowing a refund.
- **Hand-rolled httpx Stripe client** (`app/integrations/stripe/`), not the SDK —
  form-encoding, version pin, idempotency header, and error envelope stay explicit.
- **Fixed graph lookups are parameterized Cypher**, not Text2Cypher.

## Layout

```
app/
  agent.py            RefundAgent (create_agent + guardrail)
  guardrail.py        RefundGuardrail — the wrap_tool_call policy middleware
  policy.py           the deterministic guardrails (pure function)
  tools.py            order_lookup, issue_refund
  facts.py            gather_facts (graph + Stripe)
  models.py           domain models
  main.py             FastAPI (chat + resume + health)
  configs/            one settings class per file
  integrations/
    stripe/           schemas.py · client.py
    graph.py          GraphStore (Neo4j, read-only parameterized Cypher)
  sample_data.py
scripts/seed_graph.py
infra/neo4j/          Dockerfile + fly.toml for the private Neo4j instance
tests/                policy · guardrail · tools · stripe · full agent · fakes
```

Deploy: `Dockerfile` + `fly.toml` for the service, `infra/neo4j/` for the graph.

MIT. Portfolio project; not affiliated with Stripe, Sierra, or NVIDIA.
