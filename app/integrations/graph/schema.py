# app/integrations/graph/schema.py

"""The semantic ontology and the parameterized fact queries.

Design rule (the "don't be a cowboy" rule): a query you already know is written
by hand as parameterized Cypher — you never ask an LLM to regenerate a fixed SOP
lookup. Text2Cypher (text2cypher.py) is reserved for open-ended, ad-hoc questions
where the shape of the query genuinely isn't known ahead of time.

The graph holds SEMANTIC facts only — who the customer is, what they ordered,
which charge paid for it, which accounts share a payment method. It never holds
money truth (that's Stripe) and never holds policy rules (those are code).
"""

# Human- and LLM-readable ontology. Also injected into the Text2Cypher prompt so
# generated queries match the real graph.
ONTOLOGY = """
Nodes:
  (:Customer  {id, email})
  (:Order     {id, total_cents, currency, purchased_at, refunded})
  (:Transaction {id})            // id is the Stripe charge id, ch_…
  (:PaymentMethod {fingerprint}) // shared fingerprint links accounts

Relationships:
  (:Customer)-[:PLACED]->(:Order)
  (:Order)-[:PAID_WITH]->(:Transaction)
  (:Customer)-[:USED]->(:PaymentMethod)

Notes:
  - Order.purchased_at is an ISO-8601 UTC string.
  - Order.refunded is a boolean reflecting refund history (for risk scoring).
  - Two customers sharing a (:PaymentMethod) are "linked accounts".
""".strip()

# Fixed lookups. Parameterized (never string-formatted) — injection-proof by
# construction.

ORDER_FACTS_CYPHER = """
MATCH (c:Customer)-[:PLACED]->(o:Order {id: $order_id})-[:PAID_WITH]->(t:Transaction)
RETURN o.id            AS order_id,
       c.id            AS customer_id,
       t.id            AS charge_id,
       o.purchased_at  AS purchase_date,
       o.total_cents   AS order_total_cents,
       o.currency      AS currency
LIMIT 1
""".strip()

CUSTOMER_RISK_CYPHER = """
MATCH (c:Customer {id: $customer_id})
OPTIONAL MATCH (c)-[:PLACED]->(o:Order)
WITH c,
     count(o)                                        AS lifetime_order_count,
     sum(CASE WHEN o.refunded THEN 1 ELSE 0 END)     AS prior_refund_count
OPTIONAL MATCH (c)-[:USED]->(:PaymentMethod)<-[:USED]-(other:Customer)
WHERE other.id <> c.id
OPTIONAL MATCH (other)-[:PLACED]->(oo:Order)
WITH lifetime_order_count, prior_refund_count,
     count(oo)                                       AS linked_orders,
     sum(CASE WHEN oo.refunded THEN 1 ELSE 0 END)    AS linked_refunds
RETURN lifetime_order_count,
       prior_refund_count,
       CASE WHEN linked_orders = 0 THEN 0.0
            ELSE toFloat(linked_refunds) / linked_orders END AS linked_account_refund_rate
""".strip()
