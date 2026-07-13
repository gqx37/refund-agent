# app/main.py

"""FastAPI surface for the refund agent.

Two health endpoints, on purpose (the industry liveness/readiness split):
  - /health       liveness: is the process up? Cheap, no dependencies. Fly/K8s
                  restart the machine if this fails, so it must not depend on Neo4j.
  - /health/ready readiness: are dependencies reachable? Returns 503 if not, so a
                  load balancer stops routing without triggering a restart.

Two agent endpoints:
  - POST /v1/refund-requests                    submit a request
  - POST /v1/refund-requests/{id}/resolve       a human resolves an escalation
"""

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
from app.integrations.stripe.types.refund.actions import RefundCreateReason
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
    log.info("startup", env=cfg.env)
    try:
        yield
    finally:
        await built.aclose()
        log.info("shutdown")


app = FastAPI(title="refund-agent", version="0.1.0", lifespan=lifespan)


class SubmitBody(BaseModel):
    order_id: str = Field(..., description="The order to refund.")
    customer_message: str = Field("", description="The customer's message, verbatim.")
    request_id: Optional[str] = Field(None, description="Idempotency/audit id; generated if omitted.")
    reason: Optional[RefundCreateReason] = Field(None, description="Refund reason, if known.")
    requested_amount_cents: Optional[int] = Field(
        None, ge=1, description="Partial amount in cents; omit to refund the full remaining amount."
    )


class ResolveBody(BaseModel):
    approve: bool = Field(..., description="Whether the reviewer approves the refund.")
    note: Optional[str] = Field(None, description="Optional reviewer note.")


@app.get("/health", include_in_schema=False)
async def health_liveness() -> dict:
    """Liveness: process is up. No dependency checks (a Neo4j outage must not
    restart this machine)."""
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_readiness(response: Response) -> dict:
    """Readiness: can we reach the graph? 503 if not."""
    data: dict = {"status": "ok"}
    try:
        # A trivial read; run_read enforces read-only so this can't mutate.
        await app.state.built.resources[-1].run_read("RETURN 1 AS ok", {})
        data["neo4j"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness reports, doesn't raise
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        data["status"] = "error"
        data["neo4j"] = str(exc)
    return data


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

    cfg = app_config()
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)
