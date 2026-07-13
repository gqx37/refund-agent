# app/stubs/stripe_stub.py

"""A stateful fake Stripe served over an httpx.MockTransport.

This is the seam that makes the agent testable end-to-end without a key: hand the
StripeClient this transport and every request is answered from in-memory demo
state. It mirrors the real wire contract closely enough to be worth trusting:
  - GET /v1/charges/{id} returns a Charge object.
  - POST /v1/refunds validates the amount, mutates amount_refunded, returns a Refund.
  - 4xx errors use Stripe's {"error": {...}} envelope.
  - Idempotency-Key is honored: replaying a key replays the stored response, so a
    retry can't double-refund — the same guarantee the real API gives.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional, TypedDict
from urllib.parse import parse_qsl

import httpx

from app.demo import CHARGES


class _ChargeState(TypedDict):
    amount: int
    amount_refunded: int
    disputed: bool
    status: str
    currency: str
    customer: Optional[str]
    created: int


class FakeStripe:
    """Holds mutable charge state + an idempotency cache, exposes a MockTransport."""

    def __init__(self) -> None:
        # Deep-ish copy so mutations don't leak across test cases.
        self._charges: dict[str, _ChargeState] = {
            cid: _ChargeState(
                amount=c.amount_cents,
                amount_refunded=c.amount_refunded_cents,
                disputed=c.disputed,
                status=c.status,
                currency="usd",
                customer=c.customer_id,
                created=int(time.time()),
            )
            for cid, c in CHARGES.items()
        }
        self._idempotency: dict[str, tuple[int, dict]] = {}

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    # --- request routing -----------------------------------------------------

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
        return httpx.Response(200, json=self._charge_json(charge_id, charge))

    def _create_refund(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        idem = request.headers.get("Idempotency-Key")
        if idem and idem in self._idempotency:
            status, body = self._idempotency[idem]
            return httpx.Response(status, json=body)

        charge_id = form.get("charge")
        if not charge_id or charge_id not in self._charges:
            return _error(404, "invalid_request_error", f"No such charge: {charge_id}", param="charge")

        charge = self._charges[charge_id]
        remaining = charge["amount"] - charge["amount_refunded"]
        amount = int(form["amount"]) if "amount" in form else remaining

        if amount > remaining:
            resp = _error(
                400,
                "invalid_request_error",
                f"Refund amount ({amount}) is greater than unrefunded amount ({remaining}) on charge.",
                param="amount",
            )
            if idem:
                self._idempotency[idem] = (resp.status_code, json.loads(resp.content))
            return resp

        # Apply the refund to fake money state.
        charge["amount_refunded"] += amount
        body = {
            "id": f"re_{uuid.uuid4().hex[:24]}",
            "object": "refund",
            "amount": amount,
            "charge": charge_id,
            "currency": charge["currency"],
            "created": int(time.time()),
            "payment_intent": None,
            "reason": form.get("reason"),
            "receipt_number": None,
            "status": "succeeded",
        }
        if idem:
            self._idempotency[idem] = (200, body)
        return httpx.Response(200, json=body)

    @staticmethod
    def _charge_json(charge_id: str, charge: _ChargeState) -> dict:
        return {
            "id": charge_id,
            "object": "charge",
            "amount": charge["amount"],
            "amount_captured": charge["amount"],
            "amount_refunded": charge["amount_refunded"],
            "currency": charge["currency"],
            "created": charge["created"],
            "customer": charge["customer"],
            "captured": True,
            "disputed": charge["disputed"],
            "paid": True,
            "refunded": charge["amount_refunded"] >= charge["amount"],
            "status": charge["status"],
            "payment_intent": None,
        }


def _error(status: int, type_: str, message: str, *, param: str | None = None) -> httpx.Response:
    error: dict = {"type": type_, "message": message}
    if param:
        error["param"] = param
    return httpx.Response(status, json={"error": error})
