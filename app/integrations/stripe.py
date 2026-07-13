# Hand-rolled async Stripe client. Not the `stripe` SDK, so the wire format
# (form-encoding, version pin, idempotency header, error envelope) stays visible.
# Retrieve a charge, create a refund. The LLM is never given either.
#
# Schemas translated from https://docs.stripe.com/api (charges, refunds).

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.configs import StripeConfig


# --- Schemas ---------------------------------------------------------------

class RefundReason(str, Enum):
    """Caller-settable reasons (Stripe also sets expired_uncaptured_charge itself)."""

    DUPLICATE = "duplicate"
    FRAUDULENT = "fraudulent"
    REQUESTED_BY_CUSTOMER = "requested_by_customer"


class RefundStatus(str, Enum):
    PENDING = "pending"
    REQUIRES_ACTION = "requires_action"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class Charge(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    amount: int = Field(..., description="Amount charged, in cents.")
    amount_refunded: int = Field(..., description="Amount already refunded, in cents.")
    currency: str
    disputed: bool
    status: str = Field(..., description="succeeded | pending | failed.")
    customer: Optional[str] = None


class Refund(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    amount: int
    charge: Optional[str] = None
    currency: str
    reason: Optional[str] = None
    status: Optional[RefundStatus] = None


class RefundCreateParams(BaseModel):
    """POST /v1/refunds. Exactly one of charge / payment_intent."""

    model_config = ConfigDict(extra="forbid")

    charge: Optional[str] = None
    payment_intent: Optional[str] = None
    amount: Optional[int] = Field(None, ge=1, description="Cents; omit to refund the full remainder.")
    reason: Optional[RefundReason] = None
    metadata: Optional[Dict[str, str]] = None

    @model_validator(mode="after")
    def _one_target(self) -> "RefundCreateParams":
        if bool(self.charge) == bool(self.payment_intent):
            raise ValueError("Provide exactly one of `charge` or `payment_intent`.")
        return self


# --- Errors ----------------------------------------------------------------

class StripeError(Exception):
    """Carries Stripe's error envelope (type/code/param) so callers see the real cause."""

    def __init__(
        self,
        message: str,
        *,
        type: Optional[str] = None,
        code: Optional[str] = None,
        param: Optional[str] = None,
        status_code: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.type = type
        self.code = code
        self.param = param
        self.status_code = status_code
        self.request_id = request_id


# --- Client ----------------------------------------------------------------

class StripeClient:
    def __init__(self, config: StripeConfig, *, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        headers = {"Authorization": f"Bearer {config.api_key}"}
        if config.api_version:
            headers["Stripe-Version"] = config.api_version
        self._http = httpx.AsyncClient(
            base_url=config.api_base, headers=headers, timeout=config.timeout_seconds, transport=transport
        )

    async def retrieve_charge(self, charge_id: str) -> Charge:
        raw = await self._request("GET", f"/v1/charges/{charge_id}")
        return Charge.model_validate(raw)

    async def create_refund(self, params: RefundCreateParams) -> Refund:
        # Deterministic idempotency key from the args: a retry replays instead of
        # double-refunding. The caller puts a unique request_id in metadata.
        raw = await self._request(
            "POST",
            "/v1/refunds",
            data=params.model_dump(exclude_none=True, mode="json"),
            idempotency_key=_idempotency_key(params),
        )
        return Refund.model_validate(raw)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        data: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        headers = {}
        content = None
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if data is not None:
            # Bracketed keys can repeat, so url-encode ourselves rather than httpx's dict-only data=.
            content = urlencode(_flatten(data))
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = await self._http.request(method, path, content=content, headers=headers or None)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_success:
            return body
        error = body.get("error", {}) if isinstance(body, dict) else {}
        raise StripeError(
            error.get("message", f"Stripe request failed with HTTP {response.status_code}"),
            type=error.get("type"),
            code=error.get("code"),
            param=error.get("param"),
            status_code=response.status_code,
            request_id=response.headers.get("Request-Id"),
        )


def _idempotency_key(params: RefundCreateParams) -> str:
    canonical = json.dumps(
        params.model_dump(exclude_none=True, mode="json"), sort_keys=True, separators=(",", ":")
    )
    return "refund:" + hashlib.sha256(canonical.encode()).hexdigest()


def _flatten(data: Mapping[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Nested dict -> Stripe's bracketed form pairs (metadata[k]=v). Drops None."""
    pairs: list[tuple[str, str]] = []
    for key, value in data.items():
        field = f"{prefix}[{key}]" if prefix else key
        if value is None:
            continue
        if isinstance(value, Mapping):
            pairs.extend(_flatten(value, field))
        else:
            pairs.append((field, "true" if value is True else "false" if value is False else str(value)))
    return pairs
