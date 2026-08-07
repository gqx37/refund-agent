# Refund agent

Live: **https://refund-agent.vercel.app** <!-- TODO: replace with the real Vercel URL after the first deploy -->

The agent's API is at `refund-agent.fly.dev`, but it only answers the UI (see Deployment).

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

The demo URL is public and the model isn't free, so `app/limits.py` bounds it: a token
bucket per client IP, a cap on message size, and a cap on turns per thread, since each
turn re-sends the whole history. It's one machine, so the buckets are in-process.

Orders and customers are in SQLite, in-process. `docs/design-note-neo4j-vs-code.md` has
the note on why I dropped Neo4j for it. The model is Kimi K2.6 on Fireworks.

## Deployment

Two pieces. The UI is a static Next.js page on Vercel, so it comes off the CDN and paints
instantly. The agent is one Fly machine running FastAPI.

The machine idles suspended to keep the demo near free, which means the first request after
a deploy pays a full cold boot — Fly discards the suspend snapshot on deploy. Two things
cover that: the page pings `/api/warm` the moment it paints, so the machine is booting
while you read the suggestions, and if it's still waking when you send, the composer says
so instead of blinking at nothing.

The browser never talks to Fly and holds no credential. It calls same-origin `/api/*` on
Vercel, and that Route Handler attaches `PROXY_SHARED_SECRET` server-side and forwards.
`/v1` rejects anything without it, so the Fly URL is inert on its own and the demo can't be
scripted around the UI. `/health` stays open — Fly's load balancer polls it.

That proxy has one non-obvious consequence: every request now reaches Fly from a Vercel
address, so `Fly-Client-IP` is useless for rate limiting and all visitors would share one
token bucket. The proxy forwards the real address in `X-Demo-Client-IP`, and `client_key`
believes it only when the shared secret authenticated that hop.

```bash
# agent
flyctl secrets set FIREWORKS_API_KEY=… STRIPE_API_KEY=… PROXY_SHARED_SECRET="$(openssl rand -hex 32)"
flyctl deploy

# UI — Vercel project root is web/
# set BACKEND_URL and the same PROXY_SHARED_SECRET in the project's env vars
cd web && npm install && npx vercel deploy --prod
```

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
  main.py           FastAPI: /v1/chat, /v1/chat/{id}/resume, /health, the /v1 gate
  limits.py         token bucket, message cap, turns per thread
  integrations/     stripe/, store.py
web/                the UI, on Vercel
  app/page.tsx      static shell — no hydration, ships from the CDN
  app/api/          the authenticated streaming proxy
  public/chat.js    the chat surface
scripts/seed.py
tests/
```

MIT. Portfolio project, not affiliated with Stripe or Fireworks.
