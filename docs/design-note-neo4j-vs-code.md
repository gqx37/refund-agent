If you want to use Neo4j and Text-to-Cypher without looking like an over-engineering cowboy, you should use a **Semantic Memory Graph** for the database layer.

Do **not** put your procedural rules into Neo4j. That is a massive red flag. Text-to-Cypher is designed to query *facts, relationships, and data entities* (Semantic Memory), not to execute logic flows. Trying to force an LLM to generate Cypher queries to read text instructions out of a graph database just to follow an SOP is a textbook example of useless over-engineering.

Instead, map the two layers perfectly to Sierra's explicit product architecture:

### 1. The Code Layer: Procedural Knowledge (The Guardrails)

According to Sierra’s core thesis, **procedural knowledge** (how things should be done) and **deterministic guardrails** should be handled via a declarative structure in code, not hidden in a database.

* **The Implementation:** Keep your procedural logic in **LangGraph** or native code blocks. You define the explicit steps: *Step 1: Check purchase date. Step 2: Check refund status.*
* **Why this hits the Sierra thesis:** Sierra’s Agent SDK relies on developers declaring these behaviors deterministically so that agents don't go rogue. Hardcoding the guardrails ensures 100% compliance.

### 2. The Database Layer: Semantic Knowledge Graph + Text-to-Cypher

This is where you shine with Neo4j. Your graph database should purely hold the **facts about the user and the system**.

* **The Graph Structure:** Nodes for `(:User)`, `(:Order)`, `(:Product)`, and `(:Transaction)`. Relationships like `(:User)-[:PLACED]->(:Order)-[:CONTAINS]->(:Product)`.
* **The Text-to-Cypher Flow:** When the agent hits the "Check purchase date" node in your code, it uses Text-to-Cypher to query Neo4j:
```cypher
MATCH (u:User {id: $userId})-[:PLACED]->(o:Order {id: $orderId}) 
RETURN o.purchaseDate, o.amount

```

* **Why this avoids the red flag:** It uses a graph database exactly for what it is best at—traversing deep, interconnected relational data (e.g., checking if this user has a history of high refund rates across multiple linked accounts, which is a classic fraud detection graph use case).
