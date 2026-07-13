# Hand-rolled async Stripe client. Not the `stripe` SDK, so the wire format
# (form-encoding, version pin, idempotency header, error envelope) stays visible.
# Does what the agent needs: retrieve a charge, create a refund.

from __future__ import annotations

from typing import Any, Mapping, Optional
from urllib.parse import urlencode

import httpx

from app.config import StripeConfig


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


def _flatten(data: Mapping[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Nested dict/list -> Stripe's bracketed form pairs (metadata[k]=v, expand[]=x).
    Drops None values."""
    pairs: list[tuple[str, str]] = []
    for key, value in data.items():
        field = f"{prefix}[{key}]" if prefix else key
        if value is None:
            continue
        if isinstance(value, Mapping):
            pairs.extend(_flatten(value, field))
        elif isinstance(value, (list, tuple)):
            pairs.extend((f"{field}[]", _scalar(v)) for v in value)
        else:
            pairs.append((field, _scalar(value)))
    return pairs


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class StripeClient:
    def __init__(
        self,
        config: StripeConfig,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
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
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        content = None
        if data is not None:
            # Bracketed keys can repeat, so url-encode ourselves rather than use
            # httpx's dict-only `data=`.
            content = urlencode(_flatten(data))
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        query = _flatten(params) if params is not None else None
        response = await self._http.request(
            method, path, params=query, content=content, headers=headers or None  # type: ignore[arg-type]
        )
        return self._handle(response)

    @staticmethod
    def _handle(response: httpx.Response) -> dict[str, Any]:
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

    async def aclose(self) -> None:
        await self._http.aclose()
