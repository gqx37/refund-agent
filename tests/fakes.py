# Test doubles over the sample dataset: an in-memory graph store and a fake Stripe
# transport. These are what let the whole agent run in tests with no keys.

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, TypedDict
from urllib.parse import parse_qsl

import httpx
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from app.models import CustomerRiskFacts, OrderFacts
from app.sample_data import CHARGES, LINKS, ORDERS


class ScriptedModel(FakeMessagesListChatModel):
    """A fake chat model that replays scripted AIMessages (including tool calls),
    so the full agent can be driven end-to-end without an LLM. bind_tools is a
    no-op: the tool calls are already baked into the script."""

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ARG002
        return self


class InMemoryGraphStore:
    """Mirrors GraphStore's Cypher against the sample fixtures."""

    def __init__(self, *, now: Optional[datetime] = None) -> None:
        self._now = now or datetime.now(timezone.utc)

    async def order_facts(self, order_id: str) -> Optional[OrderFacts]:
        want = "".join(c for c in order_id if c.isdigit())
        for order in ORDERS:
            same_digits = "".join(c for c in order.order_id if c.isdigit()) == want
            if order.order_id.lower() == order_id.lower() or same_digits:
                return OrderFacts(
                    order_id=order.order_id,
                    customer_id=order.customer_id,
                    charge_id=order.charge_id,
                    purchase_date=self._now - timedelta(days=order.purchased_days_ago),
                    order_total_cents=order.total_cents,
                    currency=order.currency,
                )
        return None

    async def customer_risk(self, customer_id: str) -> Optional[CustomerRiskFacts]:
        own = [o for o in ORDERS if o.customer_id == customer_id]
        if not own:
            return None
        linked_ids: set[str] = set()
        for link in LINKS:
            if customer_id in link.customer_ids:
                linked_ids.update(cid for cid in link.customer_ids if cid != customer_id)
        linked_orders = [o for o in ORDERS if o.customer_id in linked_ids]
        linked_refunds = sum(1 for o in linked_orders if o.refunded)
        return CustomerRiskFacts(
            customer_id=customer_id,
            lifetime_order_count=len(own),
            prior_refund_count=sum(1 for o in own if o.refunded),
            linked_account_refund_rate=(linked_refunds / len(linked_orders)) if linked_orders else 0.0,
        )

    async def verify(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _ChargeState(TypedDict):
    amount: int
    amount_refunded: int
    disputed: bool
    status: str
    currency: str
    customer: Optional[str]


class FakeStripe:
    """Stateful fake Stripe over an httpx.MockTransport. Honors Idempotency-Key."""

    def __init__(self) -> None:
        self._charges: dict[str, _ChargeState] = {
            cid: _ChargeState(
                amount=c.amount_cents, amount_refunded=c.amount_refunded_cents,
                disputed=c.disputed, status=c.status, currency="usd", customer=c.customer_id,
            )
            for cid, c in CHARGES.items()
        }
        self._idempotency: dict[str, tuple[int, dict]] = {}

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.startswith("/v1/charges/"):
            return self._get_charge(path.rsplit("/", 1)[-1])
        if request.method == "POST" and path == "/v1/refunds":
            return self._create_refund(request)
        return _error(404, "invalid_request_error", f"Unknown route {request.method} {path}")

    def _get_charge(self, charge_id: str) -> httpx.Response:
        charge = self._charges.get(charge_id)
        if charge is None:
            return _error(404, "invalid_request_error", f"No such charge: {charge_id}", param="charge")
        return httpx.Response(200, json={
            "id": charge_id, "object": "charge", "amount": charge["amount"],
            "amount_refunded": charge["amount_refunded"], "currency": charge["currency"],
            "customer": charge["customer"], "disputed": charge["disputed"], "status": charge["status"],
        })

    def _create_refund(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        idem = request.headers.get("Idempotency-Key")
        if idem and idem in self._idempotency:
            code, body = self._idempotency[idem]
            return httpx.Response(code, json=body)

        charge_id = form.get("charge")
        if not charge_id or charge_id not in self._charges:
            return _error(404, "invalid_request_error", f"No such charge: {charge_id}", param="charge")

        charge = self._charges[charge_id]
        remaining = charge["amount"] - charge["amount_refunded"]
        amount = int(form["amount"]) if "amount" in form else remaining

        if amount > remaining:
            resp = _error(400, "invalid_request_error",
                          f"Refund amount ({amount}) is greater than unrefunded amount ({remaining}).",
                          param="amount")
            if idem:
                self._idempotency[idem] = (resp.status_code, json.loads(resp.content))
            return resp

        charge["amount_refunded"] += amount
        body = {
            "id": f"re_{uuid.uuid4().hex[:24]}", "object": "refund", "amount": amount,
            "charge": charge_id, "currency": charge["currency"], "reason": form.get("reason"),
            "status": "succeeded",
        }
        if idem:
            self._idempotency[idem] = (200, body)
        return httpx.Response(200, json=body)


def _error(code: int, type_: str, message: str, *, param: str | None = None) -> httpx.Response:
    error: dict = {"type": type_, "message": message}
    if param:
        error["param"] = param
    return httpx.Response(code, json={"error": error})
