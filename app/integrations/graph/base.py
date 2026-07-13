# The FactStore port. Graph nodes depend on this, not on Neo4j, so the Neo4j
# adapter and the in-memory test adapter are interchangeable.

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from app.domain import CustomerRiskFacts, OrderFacts


@runtime_checkable
class FactStore(Protocol):
    async def order_facts(self, order_id: str) -> Optional[OrderFacts]: ...

    async def customer_risk(self, customer_id: str) -> Optional[CustomerRiskFacts]: ...

    async def aclose(self) -> None: ...
