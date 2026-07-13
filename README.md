# Policy-Constrained Refund Agent (Stripe)

An agent that handles customer refund requests where the language model reads
intent and writes the reply, but **the decision of whether to refund is made by
deterministic code, and the model is given no capability to move money**.

```
intake ──▶ gather_facts ──▶ evaluate_policy ──┬─ approve ─▶ execute_refund ─┐
 (LLM)      (graph+Stripe)     (pure code)     ├─ deny ─────────────────────▶ reply ─▶ done
                                               └─ escalate ─▶ human review ──┘   (LLM)
```

| Layer | Owns | Where |
|---|---|---|
| Guardrails | whether a refund is allowed | `app/policy.py` (pure function) |
| Facts | customer, order, linked accounts | Neo4j (`app/integrations/graph.py`) |
| Tools | look up a charge, issue a refund | `app/integrations/stripe/tools.py` |
| Reasoning | extract intent, phrase the reply | Nemotron 3 Ultra on Fireworks |

The agent's tools are `charge_lookup` and `issue_refund`. The graph invokes them;
the LLM is never bound to them, so `issue_refund` runs only after an `approve`
decision (policy-clean or a human's approval).

## Run the tests, no keys

The whole agent runs on fakes (a fake Stripe transport and an in-memory graph),
so the test suite needs no keys, no network, no Postgres:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest        # 31 tests: policy, Stripe client, full agent flow + human resume
```

## Run it for real

```bash
cp .env.example .env      # FIREWORKS_API_KEY, STRIPE_API_KEY, NEO4J_*
python -m scripts.seed_graph
uvicorn app.main:app
```

```bash
curl -sX POST localhost:8080/v1/refund-requests -H 'content-type: application/json' \
  -d '{"order_id":"SO-10432","customer_message":"arrived broken, refund please"}'

curl -sX POST localhost:8080/v1/refund-requests/req_123/resolve \
  -H 'content-type: application/json' -d '{"approve":true}'
```

`GET /health` (liveness) · `GET /health/ready` (readiness).

## Design choices

- **Hand-rolled httpx Stripe client** (`app/integrations/stripe.py`), not the SDK,
  so the form-encoding, version pin, idempotency header, and error envelope are
  explicit. Refunds derive a deterministic idempotency key, so a retry can't
  double-refund.
- **Fixed lookups are parameterized Cypher**, not Text2Cypher. Rules live in code,
  not in the graph. See `docs/architecture.md` and `docs/design-note-neo4j-vs-code.md`.
- **Escalation is a LangGraph interrupt/resume**: the run pauses and the same run
  resumes once a reviewer answers.
- **Tools are visible but code-orchestrated**: `charge_lookup` / `issue_refund` are
  real LangChain tools, but the graph calls them deterministically rather than
  letting the model choose — a refund flow always needs the same facts, so there's
  no LLM nondeterminism to buy. The model is never bound to `issue_refund`.

## Layout

```
app/
  agent.py            RefundAgent: the graph, the nodes, submit/resolve
  policy.py           the deterministic guardrails (pure function)
  models.py           domain models + graph state
  main.py             FastAPI (health split + endpoints)
  configs/            one settings class per file
  integrations/
    stripe/           schemas.py · client.py · tools.py (charge_lookup, issue_refund)
    graph.py          GraphStore (Neo4j, read-only parameterized Cypher)
  sample_data.py      the seed/test dataset
scripts/seed_graph.py
infra/neo4j/          Dockerfile + fly.toml for the private Neo4j instance
tests/                policy · stripe · full agent flow · fakes
```

Deploy: `Dockerfile` + `fly.toml` for the service, `infra/neo4j/` for the graph.

MIT. Portfolio project; not affiliated with Stripe, Sierra, or NVIDIA.
