# Policy-Constrained Refund Agent (Stripe)

An AI agent that handles customer refund requests the way you'd actually trust
one to: the **language model reads intent and phrases the reply, but it never
decides whether a refund is allowed, and it can never move money**. Those
decisions live in deterministic code and behind a human's approval.

It's a small, self-contained demonstration of the
[Sierra "declarative goals and guardrails"](docs/architecture.md) thesis and the
[Nemotron + LangChain harness](docs/architecture.md) idea: the model is *good
enough*; the engineering value is the harness around it.

```
intake ──▶ gather_facts ──▶ evaluate_policy ──┬─ APPROVE ─▶ execute_refund ─┐
 (LLM)      (graph+Stripe)     (pure code)     ├─ DENY ─────────────────────▶ compose_reply ─▶ done
                                               └─ ESCALATE ─▶ human review ──┘        (LLM)
```

## The three layers (and why they're separate)

| Layer | Owns | Lives in | Source of truth for |
|---|---|---|---|
| **Procedural / guardrails** | *Whether* a refund is allowed | `app/agent/policy.py` (pure function) | the rules |
| **Semantic facts** | *Who/what*: customer, order, linked accounts | Neo4j (`app/integrations/graph`) | identity + history |
| **Money** | The actual charge and refund | Stripe (`app/integrations/stripe`) | balances |
| **Reasoning** | Extract intent, phrase the reply | Nemotron 3 Ultra on Fireworks | nothing it can act on |

The one invariant everything turns on: **`execute_refund` is reachable only from
an `APPROVE` decision** (policy-clean, or a human's approval). The LLM is never
bound to the refund tool.

## Run it with zero setup

The whole agent runs on in-memory stubs — no Stripe, Neo4j, or Fireworks key:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

refund-agent demo        # runs every scenario: approve / deny / escalate + resume
pytest                   # 30+ tests, all on stubs, no keys, no Postgres
```

`refund-agent demo` walks the [canonical dataset](app/demo.py): a clean refund
(approved), an out-of-window order (denied), a disputed charge (denied), an
already-refunded charge (denied), a high-value refund (escalated), a serial
refunder (escalated), and a fraud-ring account linked by a shared card
(escalated) — each engineered to trip one specific policy branch.

## Run it for real

```bash
cp .env.example .env      # fill in FIREWORKS_API_KEY, STRIPE_API_KEY, NEO4J_*
python -m app.integrations.graph.seed        # seed the demo graph into Neo4j
refund-agent serve                           # or: uvicorn app.main:app
```

```bash
# Submit a request
curl -sX POST localhost:8080/v1/refund-requests \
  -H 'content-type: application/json' \
  -d '{"order_id":"order_alice_ok","customer_message":"it arrived broken, refund please"}'

# Resolve an escalation (human in the loop)
curl -sX POST localhost:8080/v1/refund-requests/req_123/resolve \
  -H 'content-type: application/json' -d '{"approve":true}'
```

Health: `GET /health` (liveness) and `GET /health/ready` (readiness, 503 if the
graph is unreachable).

## Notable engineering choices

- **Clean-room Stripe client** (`app/integrations/stripe`): a hand-rolled async
  httpx client, not the `stripe` SDK, so the wire contract is explicit —
  form-encoding, the `Stripe-Version` pin, the `Idempotency-Key` header, and
  Stripe's error envelope. Schemas are translated field-for-field from the API
  reference, descriptions verbatim, so the tool never drifts from the docs.
- **Idempotency, for real**: refunds derive a deterministic idempotency key from
  their arguments, so a retried request can't double-refund. Tested.
- **Ports/adapters**: the graph depends on a `FactStore` protocol, so the Neo4j
  adapter and the in-memory test adapter are interchangeable — that's what makes
  the whole thing keyless-testable.
- **Text2Cypher is guarded and off the decision path**: known lookups are fixed
  parameterized Cypher; the LLM only writes Cypher for open-ended, read-only
  fraud questions. See [docs/architecture.md](docs/architecture.md).
- **Human-in-the-loop via LangGraph interrupt/resume**: an escalation pauses the
  run and resumes the *same* run once a reviewer answers.

## Layout

```
app/
  agent/        policy.py (guardrails) · graph.py (harness) · service.py · llm.py
  integrations/
    stripe/     client.py · tools.py · types/{charge,refund}/{actions,models}.py
    graph/      client.py (Neo4j) · schema.py (ontology) · text2cypher.py · seed.py
  stubs/        fake Stripe transport + in-memory fact store
  main.py       FastAPI (health split + endpoints)   cli.py   demo.py (fixtures)
infra/neo4j/    Dockerfile + fly.toml for the private Neo4j instance
tests/          policy (pure) · stripe tools (transport) · full graph flow
```

## Deploy

The service is a single container (`Dockerfile`) with a `fly.toml`; the graph is
a private Neo4j instance under `infra/neo4j/`. See `docs/architecture.md`.

MIT licensed. Built as a portfolio piece; not affiliated with Stripe, Sierra, or NVIDIA.
