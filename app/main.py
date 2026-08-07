# FastAPI surface. /health is liveness (dependency-free); /health/ready is
# readiness (503 if the graph is down) — both stay open, because Fly's load
# balancer polls them and the UI pings them to wake the machine. The agent is
# conversational: /v1/chat holds a thread, /v1/chat/{thread}/resume answers an
# escalation. Everything under /v1 spends the model, so it sits behind
# require_proxy: only the UI's server-side proxy holds the secret.
#
# The UI itself lives in web/ and is served by Vercel, not from here.

from __future__ import annotations

import hmac
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.agent import RefundAgent
from app.configs import proxy_config, runtime_config
from app.limits import Limits, Rejection, client_key
from app.logging import configure, get_logger

load_dotenv()
log = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = runtime_config()
    configure(is_production=cfg.is_production)
    app.state.agent = RefundAgent.production()
    app.state.limits = Limits()
    if cfg.is_production and not proxy_config().shared_secret:
        log.warning("proxy_secret_missing", detail="/v1 is open to the internet; set PROXY_SHARED_SECRET")
    log.info("startup", env=cfg.env)
    try:
        yield
    finally:
        await app.state.agent.aclose()


app = FastAPI(title="refund-agent", version="0.1.0", lifespan=lifespan)


class ChatBody(BaseModel):
    message: str
    thread_id: Optional[str] = None


class ResolveBody(BaseModel):
    approve: bool


@app.get("/health", include_in_schema=False)
async def health_liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_readiness(response: Response) -> dict:
    try:
        await app.state.agent.verify()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - readiness reports, doesn't raise
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "store": str(exc)}


def require_proxy(request: Request) -> None:
    """Gate on /v1: only the UI's server-side proxy may spend the model.

    The browser holds no credential — it calls the Vercel Route Handler, which
    keeps the secret in a server-only env var and forwards. This is about the
    second hop, proxy -> here.

    Also records whether the hop was authenticated, because that is exactly the
    condition under which a forwarded client IP can be believed (see client_key).
    """
    secret = proxy_config().shared_secret
    if not secret:
        # No secret configured: open service, and no forwarded IP is trustworthy.
        request.state.trusted_proxy = False
        return

    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token, secret):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "This endpoint is only reachable through the demo UI.",
        )
    request.state.trusted_proxy = True


def _rejection(request: Request, thread_id: str, message: str = "") -> Optional[Rejection]:
    """Every LLM-spending endpoint goes through here. Public URL, paid model."""
    client = client_key(
        request.headers,
        request.client.host if request.client else None,
        trusted_proxy=getattr(request.state, "trusted_proxy", False),
        forwarded_header=proxy_config().client_ip_header,
    )
    rejected = app.state.limits.check(client=client, thread_id=thread_id, message=message)
    if rejected:
        log.info("rate_limited", thread_id=thread_id, status=rejected.status)
    return rejected


def _headers(rejected: Rejection) -> dict[str, str]:
    return {"Retry-After": str(rejected.retry_after)} if rejected.retry_after else {}


@app.post("/v1/stream", dependencies=[Depends(require_proxy)])
async def stream(request: Request, body: ChatBody) -> Response:
    thread_id = body.thread_id or f"thread_{uuid.uuid4().hex[:16]}"

    rejected = _rejection(request, thread_id, body.message)
    if rejected:
        return JSONResponse(
            {"detail": rejected.message},
            status_code=rejected.status,
            headers=_headers(rejected),
        )

    async def events() -> AsyncIterator[bytes]:
        yield _sse({"type": "thread", "thread_id": thread_id})
        try:
            async for event in app.state.agent.stream(thread_id, body.message):
                yield _sse(event)
        except Exception as exc:  # noqa: BLE001 - surface a clean error to the client
            log.error("stream_error", thread_id=thread_id, error=str(exc))
            yield _sse({"type": "error", "message": "The agent hit an error. Please try again."})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj)}\n\n".encode()


@app.post("/v1/chat", dependencies=[Depends(require_proxy)])
async def chat(request: Request, body: ChatBody) -> dict:
    thread_id = body.thread_id or f"thread_{uuid.uuid4().hex[:16]}"

    rejected = _rejection(request, thread_id, body.message)
    if rejected:
        raise HTTPException(rejected.status, rejected.message, headers=_headers(rejected))

    result = await app.state.agent.chat(thread_id, body.message)
    log.info("chat", thread_id=thread_id, status=result["status"])
    return {"thread_id": thread_id, **result}


@app.post("/v1/chat/{thread_id}/resume", dependencies=[Depends(require_proxy)])
async def resume(request: Request, thread_id: str, body: ResolveBody) -> dict:
    rejected = _rejection(request, thread_id)
    if rejected:
        raise HTTPException(rejected.status, rejected.message, headers=_headers(rejected))

    result = await app.state.agent.resolve(thread_id, approve=body.approve)
    log.info("resume", thread_id=thread_id, approve=body.approve, status=result["status"])
    return {"thread_id": thread_id, **result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=runtime_config().port)
