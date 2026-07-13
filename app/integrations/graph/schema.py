# Fixed, parameterized fact queries. Known lookups are hand-written Cypher, not
# Text2Cypher — you don't ask an LLM to regenerate a query whose shape you know.
#
# Graph holds facts only: (:Customer)-[:PLACED]->(:Order)-[:PAID_WITH]->(:Transaction),
# and (:Customer)-[:USED]->(:PaymentMethod) to link accounts by shared card.

ORDER_FACTS = """
MATCH (c:Customer)-[:PLACED]->(o:Order {id: $order_id})-[:PAID_WITH]->(t:Transaction)
RETURN o.id AS order_id, c.id AS customer_id, t.id AS charge_id,
       o.purchased_at AS purchase_date, o.total_cents AS order_total_cents, o.currency AS currency
LIMIT 1
""".strip()

CUSTOMER_RISK = """
MATCH (c:Customer {id: $customer_id})
OPTIONAL MATCH (c)-[:PLACED]->(o:Order)
WITH c, count(o) AS lifetime_order_count,
     sum(CASE WHEN o.refunded THEN 1 ELSE 0 END) AS prior_refund_count
OPTIONAL MATCH (c)-[:USED]->(:PaymentMethod)<-[:USED]-(other:Customer)
WHERE other.id <> c.id
OPTIONAL MATCH (other)-[:PLACED]->(oo:Order)
WITH lifetime_order_count, prior_refund_count,
     count(oo) AS linked_orders, sum(CASE WHEN oo.refunded THEN 1 ELSE 0 END) AS linked_refunds
RETURN lifetime_order_count, prior_refund_count,
       CASE WHEN linked_orders = 0 THEN 0.0
            ELSE toFloat(linked_refunds) / linked_orders END AS linked_account_refund_rate
""".strip()
