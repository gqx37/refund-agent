# app/integrations/graph/text2cypher.py

"""A guarded Text2Cypher tool for open-ended questions about the graph.

This is the semantic layer's escape hatch: a human or an agent asks a question in
English ("does this customer share a card with any account that has a >50% refund
rate?"), the LLM writes a single read-only Cypher query grounded in the ontology,
and we run it under READ routing with a write-clause guard on top.

It is intentionally NOT on the refund decision path. The decision uses fixed
parameterized queries (schema.py); you don't hand an LLM the job of regenerating
a lookup you already know. Text2Cypher earns its keep only where the query shape
is genuinely unknown ahead of time.
"""

from __future__ import annotations

import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.integrations.graph.base import FactStore
from app.integrations.graph.schema import ONTOLOGY

_PROMPT = f"""You translate a question into ONE read-only Neo4j Cypher query.

Graph ontology:
{ONTOLOGY}

Rules:
- Return ONLY the Cypher query, no prose, no code fences.
- It MUST be read-only: MATCH / OPTIONAL MATCH / WITH / RETURN / WHERE / ORDER BY / LIMIT only.
- Never use CREATE, MERGE, SET, DELETE, REMOVE, or any write clause.
- Always include a LIMIT (<= 50).
"""

_FENCE = re.compile(r"^```(?:cypher)?|```$", re.IGNORECASE | re.MULTILINE)


class GraphQuestion(BaseModel):
    question: str = Field(..., description="A natural-language question about customers, orders, "
                          "transactions, or linked accounts in the graph.")


def build_text2cypher_tool(fact_store: FactStore, llm: BaseChatModel) -> StructuredTool:
    async def _arun(question: str) -> dict:
        drafted = await llm.ainvoke(
            [SystemMessage(content=_PROMPT), HumanMessage(content=question)]
        )
        cypher = _FENCE.sub("", str(drafted.content)).strip()
        # run_read enforces read-only again at the store; defense in depth.
        rows = await fact_store.run_read(cypher, {})
        return {"cypher": cypher, "rows": rows}

    return StructuredTool.from_function(
        coroutine=_arun,
        name="graph_query",
        description=(
            "Answer an open-ended question about customers, orders, transactions, and linked "
            "accounts by querying the knowledge graph. Read-only."
        ),
        args_schema=GraphQuestion,
    )
