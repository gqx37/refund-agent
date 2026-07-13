# Graph state. total=False: keys fill in as the run progresses.

from __future__ import annotations

from typing import TypedDict

from app.domain import PolicyDecision, RefundFacts, RefundRequest


class RefundState(TypedDict, total=False):
    request: RefundRequest
    facts: RefundFacts
    decision: PolicyDecision
    refund: dict
    error: str
    reply: str
    human_note: str
