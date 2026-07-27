# Refund agent

Live: **https://refund-agent.fly.dev**

An agent that issues Stripe refunds. The policy check runs as middleware around the
refund tool, so the model can handle the conversation however it wants but can't move
money without passing the check.

## Try it

The link above is a chat UI, nothing to install. Refunds are real, in Stripe test mode.

Things to type:

- `I'm Alice Carter, show my orders`
- `refund SO-10432, it arrived broken` — goes through
- `refund SO-10440 in full` — over the ceiling, asks you to approve or deny
- `refund SO-10377` — disputed, blocked

## How it works

`create_agent` with four tools: `find_customer`, `list_orders`, `order_lookup`,
`issue_refund`. `RefundGuardrail` is a `wrap_tool_call` middleware that catches
`issue_refund`, re-reads the order from SQLite and Stripe, and runs `policy.evaluate`.
That returns approve, deny, or escalate; escalate interrupts and waits for a human.

The re-read is the part that matters. The policy runs on facts the guardrail gathered
itself, not on whatever the model passed into the tool call.

The policy is a pure function in `app/policy.py`: refund window, amount ceiling, no
double refunds, disputed orders blocked, high fraud rate escalates.

Orders and customers are in SQLite, in-process. `docs/design-note-neo4j-vs-code.md` has
the note on why I dropped Neo4j for it. The model is Kimi K2.6 on Fireworks. It deploys
as one Fly machine running FastAPI for both the API and the UI.

## Tests

No keys or services needed — scripted model, fake Stripe transport, in-memory store.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Running it yourself

Real model, real SQLite, real Stripe test mode.

```bash
cp .env.example .env      # FIREWORKS_API_KEY, STRIPE_API_KEY (test), LANGSMITH_API_KEY
python -m scripts.seed    # builds the store, creates Stripe test charges
langgraph dev             # opens LangGraph Studio to chat with it
```

The seed makes ~50 orders across the states worth hitting: refundable, partly refunded,
fully refunded, disputed. Refunds land in your Stripe test dashboard.

## Layout

```
app/
  agent.py          create_agent + the guardrail
  guardrail.py      the wrap_tool_call middleware
  policy.py         the rules, as a pure function
  tools.py          find_customer, list_orders, order_lookup, issue_refund
  facts.py          reads the store + Stripe
  main.py           FastAPI: /v1/chat, /v1/chat/{id}/resume, /health
  integrations/     stripe/, store.py
scripts/seed.py
tests/
```

MIT. Portfolio project, not affiliated with Stripe or Fireworks.
