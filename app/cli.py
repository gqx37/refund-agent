# app/cli.py

"""Command-line surface.

    refund-agent demo                      run every demo scenario, no keys needed
    refund-agent submit --order-id … …     run one request (demo mode by default)
    refund-agent serve                     start the HTTP service

`demo` and the default `submit` run entirely on stubs, so a reviewer can see the
policy engine work without a Stripe/Neo4j/Fireworks key.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from app.agent.factory import build_demo_service, build_production_service
from app.agent.service import RefundAgentService, RefundOutcome
from app.domain import RefundRequest


# (order_id, customer_message, human_resolution_or_None) — the resolution is used
# to auto-answer escalations so the demo shows the full round trip.
_DEMO_SCENARIOS: list[tuple[str, str, bool | None]] = [
    ("order_alice_ok", "Please refund my order, it arrived damaged.", None),
    ("order_alice_old", "I'd like a refund on this old order.", None),
    ("order_alice_disputed", "Refund me please.", None),
    ("order_alice_done", "Can I get refunded?", None),
    ("order_alice_big", "This was a mistake, please refund the full amount.", True),
    ("order_bob", "Refund please, didn't like it.", False),
    ("order_carol", "Please refund my purchase.", False),
]


def _print(outcome: RefundOutcome) -> None:
    line = f"[{outcome.status.upper():9}] {outcome.request_id}"
    if outcome.decision:
        line += f"  rule={outcome.decision.rule_id}"
    print(line)
    if outcome.review:
        print(f"            review -> amount={outcome.review['amount_cents']} "
              f"reasons={outcome.review['policy_reasons'][-1]}")
    if outcome.reply:
        print(f"            reply  -> {outcome.reply}")


async def _run_demo() -> None:
    built = build_demo_service()
    service: RefundAgentService = built.service
    print("Running demo scenarios on stubs (no keys)\n")
    try:
        for order_id, message, resolution in _DEMO_SCENARIOS:
            request = RefundRequest(
                request_id=f"req_{order_id}", order_id=order_id, customer_message=message
            )
            outcome = await service.submit(request)
            _print(outcome)
            if outcome.status == "escalated" and resolution is not None:
                resolved = await service.resolve(request.request_id, approve=resolution)
                print(f"            human {'APPROVED' if resolution else 'DENIED'} ->")
                _print(resolved)
            print()
    finally:
        await built.aclose()


async def _run_submit(args: argparse.Namespace) -> None:
    built = build_production_service() if args.live else build_demo_service()
    try:
        request = RefundRequest(
            request_id=args.request_id or f"req_{uuid.uuid4().hex[:24]}",
            order_id=args.order_id,
            requested_amount_cents=args.amount,
            customer_message=args.message,
        )
        outcome = await built.service.submit(request)
        _print(outcome)
    finally:
        await built.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="refund-agent", description="Policy-constrained refund agent.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="Run every demo scenario on stubs (no keys).")

    submit = sub.add_parser("submit", help="Run a single refund request.")
    submit.add_argument("--order-id", required=True, dest="order_id")
    submit.add_argument("--message", default="", help="Customer message.")
    submit.add_argument("--amount", type=int, default=None, help="Partial amount in cents.")
    submit.add_argument("--request-id", default=None, dest="request_id")
    submit.add_argument("--live", action="store_true", help="Use real Stripe/Neo4j/Fireworks.")

    sub.add_parser("serve", help="Start the HTTP service.")

    args = parser.parse_args()

    if args.command == "demo":
        asyncio.run(_run_demo())
    elif args.command == "submit":
        asyncio.run(_run_submit(args))
    elif args.command == "serve":
        import uvicorn

        from app.config import app_config

        uvicorn.run("app.main:app", host="0.0.0.0", port=app_config().port)


if __name__ == "__main__":
    main()
