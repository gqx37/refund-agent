# Policy-Constrained Refund Agent (Stripe)

An agent that handles customer refund requests where the language model reads
intent and writes the reply, but **the decision of whether to refund is made by
deterministic code, and the model can never move money**.

```
intake ──▶ gather_facts ──▶ evaluate_policy ──┬─ approve ─▶ execute_refund ─┐
 (LLM)      (graph+Stripe)     (pure code)     ├─ deny ─────────────────────▶ reply ─▶ done
                                               └─ escalate ─▶ human review ──┘   (LLM)
```

| Layer | Owns | Where |
|---|---|---|
| Guardrails | whether a refund is allowed | `app/agent/policy.py` (pure function) |
| Facts | customer, order, linked accounts | Neo4j (`app/integrations/graph`) |
| Money | the charge and the refund | Stripe (`app/integrations/stripe`) |
| Reasoning | extract intent, phrase the reply | Nemotron 3 Ultra on Fireworks |

`execute_refund` is only reachable from an `approve` decision (policy-clean or a
human's approval). The refund tool is never bound to the LLM.

## Run it, no keys

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

refund-agent demo        # approve / deny / escalate + human resume, on stubs
pytest                   # 29 tests, no keys, no Postgres
```

## Run it for real

```bash
cp .env.example .env      # FIREWORKS_API_KEY, STRIPE_API_KEY, NEO4J_*
python -m app.integrations.graph.seed
refund-agent serve
```

```bash
curl -sX POST localhost:8080/v1/refund-requests -H 'content-type: application/json' \
  -d '{"order_id":"order_alice_ok","customer_message":"arrived broken, refund please"}'

curl -sX POST localhost:8080/v1/refund-requests/req_123/resolve \
  -H 'content-type: application/json' -d '{"approve":true}'
```

`GET /health` (liveness) · `GET /health/ready` (readiness).

## Design choices

- **Hand-rolled httpx Stripe client** (`stripe/client.py`), not the SDK, so the
  form-encoding, version pin, idempotency header, and error envelope are explicit.
  Refunds derive a deterministic idempotency key, so a retry can't double-refund.
- **Ports/adapters**: the graph depends on a `FactStore` protocol, so the Neo4j
  and in-memory adapters are interchangeable — that's why it tests without keys.
- **Fixed lookups are parameterized Cypher**, not Text2Cypher. Rules live in code,
  not in the graph. See `docs/architecture.md` and `docs/design-note-neo4j-vs-code.md`.
- **Escalation is a LangGraph interrupt/resume**: the run pauses and the same run
  resumes once a reviewer answers.

## Layout

```
app/agent/        policy.py · graph.py · service.py · llm.py · prompts.py
app/integrations/
  stripe/         client.py · tools.py · schemas.py
  graph/          client.py · schema.py · seed.py
app/stubs/        fake Stripe transport + in-memory fact store
app/main.py · app/cli.py · app/demo.py
infra/neo4j/      Dockerfile + fly.toml for the private Neo4j instance
tests/            policy (pure) · stripe tools · full graph flow
```

Deploy: `Dockerfile` + `fly.toml` for the service, `infra/neo4j/` for the graph.

MIT. Portfolio project; not affiliated with Stripe, Sierra, or NVIDIA.
