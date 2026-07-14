# FastAPI surface. /health is liveness (dependency-free); /health/ready is
# readiness (503 if the graph is down). The agent is conversational: /v1/chat
# holds a thread, /v1/chat/{thread}/resume answers an escalation.

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app.agent import RefundAgent
from app.configs import runtime_config
from app.logging import configure, get_logger

load_dotenv()
log = get_logger()
_INDEX_HTML = (Path(__file__).parent / "web" / "index.html").read_text()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = runtime_config()
    configure(is_production=cfg.is_production)
    app.state.agent = RefundAgent.production()
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


@app.get("/", include_in_schema=False)
async def index() -> HTMLResponse:
    return HTMLResponse(_INDEX_HTML)


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


@app.post("/v1/stream")
async def stream(body: ChatBody) -> StreamingResponse:
    thread_id = body.thread_id or f"thread_{uuid.uuid4().hex[:16]}"

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


@app.post("/v1/chat")
async def chat(body: ChatBody) -> dict:
    thread_id = body.thread_id or f"thread_{uuid.uuid4().hex[:16]}"
    result = await app.state.agent.chat(thread_id, body.message)
    log.info("chat", thread_id=thread_id, status=result["status"])
    return {"thread_id": thread_id, **result}


@app.post("/v1/chat/{thread_id}/resume")
async def resume(thread_id: str, body: ResolveBody) -> dict:
    result = await app.state.agent.resolve(thread_id, approve=body.approve)
    log.info("resume", thread_id=thread_id, approve=body.approve, status=result["status"])
    return {"thread_id": thread_id, **result}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=runtime_config().port)
