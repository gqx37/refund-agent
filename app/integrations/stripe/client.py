# app/integrations/stripe/client.py

"""A small, hand-rolled async Stripe client.

Deliberately not the `stripe` SDK: the point of this project is to show the API
surface translated into typed calls with zero drift from the docs, and a thin
httpx client makes the wire format (form-encoding, the version header, the
idempotency header, Stripe's error envelope) explicit instead of hidden behind a
vendor library. It does exactly what this agent needs — retrieve a charge, create
a refund — and nothing else.

Wire-format notes (from https://docs.stripe.com/api):
  - Request bodies are application/x-www-form-urlencoded, NOT JSON.
  - Nested objects use bracket notation: metadata[order_id]=A123.
  - Arrays use bracket notation too: expand[]=customer.
  - Auth is a bearer token (the secret key).
  - `Stripe-Version` pins the API version; `Idempotency-Key` makes POSTs safe to retry.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import urlencode

import httpx

from app.config import StripeConfig


class StripeError(Exception):
    """A typed error carrying Stripe's own error envelope.

    Stripe returns errors as `{"error": {"type", "code", "message", "param", ...}}`.
    We surface those fields so callers (and, upstream, the LLM) get the provider's
    exact message and can self-correct, rather than a generic HTTP failure.

    API Reference: https://docs.stripe.com/api/errors
    """

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

    def __str__(self) -> str:  # pragma: no cover - trivial
        bits = [self.message]
        if self.code:
            bits.append(f"code={self.code}")
        if self.param:
            bits.append(f"param={self.param}")
        if self.request_id:
            bits.append(f"request_id={self.request_id}")
        return " ".join(bits)


def _flatten(data: Mapping[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Flatten a nested dict/list into Stripe's bracketed form-encoding pairs.

    {"metadata": {"a": "b"}, "expand": ["customer"], "amount": 100}
      -> [("metadata[a]", "b"), ("expand[]", "customer"), ("amount", "100")]

    None values are dropped so optional fields simply don't appear on the wire.
    """
    pairs: list[tuple[str, str]] = []
    for key, value in data.items():
        field = f"{prefix}[{key}]" if prefix else key
        if value is None:
            continue
        if isinstance(value, Mapping):
            pairs.extend(_flatten(value, field))
        elif isinstance(value, (list, tuple)):
            for item in value:
                pairs.append((f"{field}[]", _scalar(item)))
        else:
            pairs.append((field, _scalar(value)))
    return pairs


def _scalar(value: Any) -> str:
    # Stripe wants lowercase booleans and bare numbers, not Python's "True"/"None".
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class StripeClient:
    """Minimal async wrapper over the Stripe REST API.

    The `transport` seam is what lets the whole agent run in tests with no network
    and no API key: tests pass an httpx.MockTransport that serves a fake Stripe.
    """

    def __init__(
        self,
        config: StripeConfig,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._config = config
        headers = {"Authorization": f"Bearer {config.api_key}"}
        if config.api_version:
            headers["Stripe-Version"] = config.api_version
        self._http = httpx.AsyncClient(
            base_url=config.api_base,
            headers=headers,
            timeout=config.timeout_seconds,
            transport=transport,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        data: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """Issue a request and return the decoded JSON body, or raise StripeError."""
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        # Build the form body ourselves. Stripe uses bracketed keys with possible
        # repeats (metadata[k]=v, expand[]=x), which a dict can't represent, so we
        # url-encode the flattened pairs and send them as raw content with the
        # form content-type rather than relying on httpx's dict-only `data=`.
        content = None
        if data is not None:
            content = urlencode(_flatten(data))
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        query = None
        if params is not None:
            query = _flatten(params)

        response = await self._http.request(
            method,
            path,
            params=query,  # type: ignore[arg-type]  # list[tuple] is a valid httpx QueryParams source
            content=content,
            headers=headers or None,
        )
        return self._handle(response)

    @staticmethod
    def _handle(response: httpx.Response) -> dict[str, Any]:
        request_id = response.headers.get("Request-Id")
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
            request_id=request_id,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "StripeClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()
