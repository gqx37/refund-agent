# app/integrations/graph/base.py

"""The FactStore port.

The graph nodes depend on this Protocol, not on Neo4j. The production adapter is
Neo4j (`client.py`); the test adapter is an in-memory dict (`app/stubs`). This is
the ports/adapters seam that lets the entire agent run end-to-end in tests with
no database and no keys.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from app.domain import CustomerRiskFacts, OrderFacts


@runtime_checkable
class FactStore(Protocol):
    """Read-only access to the semantic knowledge graph."""

    async def order_facts(self, order_id: str) -> Optional[OrderFacts]:
        """Order-level facts (customer, charge id, purchase date, total)."""
        ...

    async def customer_risk(self, customer_id: str) -> Optional[CustomerRiskFacts]:
        """Refund-history facts, including the linked-account fraud signal."""
        ...

    async def run_read(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute an arbitrary READ-ONLY Cypher query. Used by the Text2Cypher
        tool for open-ended questions; rejects anything that could mutate."""
        ...

    async def aclose(self) -> None:
        ...
