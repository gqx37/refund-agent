# Hand-rolled async Stripe client. Not the `stripe` SDK, so the wire format
# (form-encoding, version pin, idempotency header, error envelope) stays visible.
# In r28 this is abstracted behind the runtime SDK; here it's the gear the tools
# turn.

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional
from urllib.parse import urlencode

import httpx

from app.configs import StripeConfig
from app.integrations.stripe.schemas import Charge, Refund, RefundCreateParams


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
    ) -> None:
        super().__init__(message)
        self.message = message
        self.type = type
        self.code = code
        self.param = param
        self.status_code = status_code


class StripeClient:
    def __init__(self, config: StripeConfig, *, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        headers = {"Authorization": f"Bearer {config.api_key}"}
        if config.api_version:
            headers["Stripe-Version"] = config.api_version
        self._http = httpx.AsyncClient(
            base_url=config.api_base, headers=headers, timeout=config.timeout_seconds, transport=transport
        )

    async def retrieve_charge(self, charge_id: str) -> Charge:
        return Charge.model_validate(await self._request("GET", f"/v1/charges/{charge_id}"))

    async def create_refund(self, params: RefundCreateParams) -> Refund:
        raw = await self._request(
            "POST",
            "/v1/refunds",
            data=params.model_dump(exclude_none=True, mode="json"),
            idempotency_key=self._idempotency_key(params),
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
        headers, content = {}, None
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if data is not None:
            content = urlencode(self._flatten(data))
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        response = await self._http.request(method, path, content=content, headers=headers or None)
        body = response.json() if response.content else {}
        if response.is_success:
            return body
        error = body.get("error", {}) if isinstance(body, dict) else {}
        raise StripeError(
            error.get("message", f"Stripe request failed with HTTP {response.status_code}"),
            type=error.get("type"),
            code=error.get("code"),
            param=error.get("param"),
            status_code=response.status_code,
        )

    @staticmethod
    def _idempotency_key(params: RefundCreateParams) -> str:
        # Deterministic key from the args: a retry replays instead of double-refunding.
        # The caller puts a unique request_id in metadata, so distinct requests differ.
        canonical = json.dumps(
            params.model_dump(exclude_none=True, mode="json"), sort_keys=True, separators=(",", ":")
        )
        return "refund:" + hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _flatten(data: Mapping[str, Any], prefix: str = "") -> list[tuple[str, str]]:
        """Nested dict -> Stripe's bracketed form pairs (metadata[k]=v). Drops None."""
        pairs: list[tuple[str, str]] = []
        for key, value in data.items():
            field = f"{prefix}[{key}]" if prefix else key
            if value is None:
                continue
            if isinstance(value, Mapping):
                pairs.extend(StripeClient._flatten(value, field))
            else:
                pairs.append((field, "true" if value is True else "false" if value is False else str(value)))
        return pairs
