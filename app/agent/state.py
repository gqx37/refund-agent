# app/agent/state.py

"""The graph's working memory.

Deliberately small and explicit: each node reads the fields it needs and returns
only the fields it sets. `total=False` because the state fills in as the run
progresses (facts, then decision, then refund/reply)."""

from __future__ import annotations

from typing import TypedDict

from app.domain import PolicyDecision, RefundFacts, RefundRequest


class RefundState(TypedDict, total=False):
    # total=False: keys fill in as the run progresses. A subscript (state["facts"])
    # is the bare type; use state.get(...) where a key may legitimately be absent.
    request: RefundRequest
    facts: RefundFacts
    decision: PolicyDecision
    refund: dict  # the Stripe Refund object, on success
    error: str  # a StripeError message, if the refund call failed
    reply: str  # the customer-facing message
    human_note: str  # note left by the human reviewer on an escalation
