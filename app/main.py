# FastAPI surface. /health is liveness (no dependencies, so a Neo4j outage never
# restarts the machine); /health/ready is readiness (503 if the graph is down).

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Response, status
from pydantic import BaseModel, Field

from app.agent.factory import build_production_service
from app.agent.service import RefundOutcome
from app.config import app_config
from app.domain import RefundRequest
from app.integrations.stripe.schemas import RefundReason
from app.logging import configure, get_logger

load_dotenv()
log = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = app_config()
    configure(is_production=cfg.is_production)
    built = build_production_service()
    app.state.built = built
    app.state.service = built.service
    app.state.fact_store = built.resources[-1]
    log.info("startup", env=cfg.env)
    try:
        yield
    finally:
        await built.aclose()


app = FastAPI(title="refund-agent", version="0.1.0", lifespan=lifespan)


class SubmitBody(BaseModel):
    order_id: str
    customer_message: str = ""
    request_id: Optional[str] = None
    reason: Optional[RefundReason] = None
    requested_amount_cents: Optional[int] = Field(None, ge=1)


class ResolveBody(BaseModel):
    approve: bool
    note: Optional[str] = None


@app.get("/health", include_in_schema=False)
async def health_liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_readiness(response: Response) -> dict:
    try:
        await app.state.fact_store.verify()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 - readiness reports, doesn't raise
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error", "neo4j": str(exc)}


@app.post("/v1/refund-requests", response_model=RefundOutcome)
async def submit_refund_request(body: SubmitBody) -> RefundOutcome:
    request = RefundRequest(
        request_id=body.request_id or f"req_{uuid.uuid4().hex[:24]}",
        order_id=body.order_id,
        reason=body.reason,
        requested_amount_cents=body.requested_amount_cents,
        customer_message=body.customer_message,
    )
    outcome = await app.state.service.submit(request)
    log.info("refund_request", request_id=outcome.request_id, status=outcome.status,
             rule_id=outcome.decision.rule_id if outcome.decision else None)
    return outcome


@app.post("/v1/refund-requests/{request_id}/resolve", response_model=RefundOutcome)
async def resolve_refund_request(request_id: str, body: ResolveBody) -> RefundOutcome:
    outcome = await app.state.service.resolve(request_id, approve=body.approve, note=body.note)
    log.info("refund_resolve", request_id=request_id, approve=body.approve, status=outcome.status)
    return outcome


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=app_config().port)
