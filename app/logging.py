# Structured logging: JSON in production, console in development.

from __future__ import annotations

import logging
import sys

import structlog


def configure(is_production: bool) -> None:
    renderer = structlog.processors.JSONRenderer() if is_production else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "refund-agent") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
