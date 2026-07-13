# refund-agent-neo4j — Semantic Fact Store on Fly.io

The refund agent's semantic knowledge graph: customers, orders, transactions, and
the shared-payment-method edges that power linked-account fraud detection. Holds
*facts only* — never money truth (that's Stripe) and never policy rules (those
are code).

- **Image:** `neo4j:5.26-community` (LTS) + APOC core baked in at build time
- **Access:** private-only (6PN). The service uses `bolt://refund-agent-neo4j.internal:7687`
- **Auth:** `NEO4J_AUTH` secret, format `neo4j/<password>`
- **Storage:** `neo4j_data` volume at `/data`

## First-time provisioning

```bash
flyctl apps create refund-agent-neo4j
flyctl volumes create neo4j_data -a refund-agent-neo4j --region iad --size 1 --yes
flyctl secrets set NEO4J_AUTH="neo4j/<password>" -a refund-agent-neo4j --stage
flyctl deploy infra/neo4j -c infra/neo4j/fly.toml --ha=false
```

`--ha=false` because the single volume pins a single machine.

## Seeding

With a proxy tunnel in one terminal:

```bash
flyctl proxy 7688:7687 -a refund-agent-neo4j
```

and in another (from the repo root):

```bash
NEO4J_URI=bolt://localhost:7688 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=<password> \
  python -m app.integrations.graph.seed
```

The seed is idempotent (all MERGE, a pure function of `app/demo.py`) — re-run
freely after editing the fixtures.

## Ontology

```
(:Customer {id, email})
(:Order {id, total_cents, currency, purchased_at, refunded})
(:Transaction {id})            // id is the Stripe charge id
(:PaymentMethod {fingerprint}) // shared fingerprint links accounts

(:Customer)-[:PLACED]->(:Order)
(:Order)-[:PAID_WITH]->(:Transaction)
(:Customer)-[:USED]->(:PaymentMethod)
```
