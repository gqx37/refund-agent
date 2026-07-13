# app/logging.py

"""Structured logging. One configure() call, JSON in production, human-readable
console in development. Every decision the agent makes is logged as an event with
key/value fields so a refund can be reconstructed from logs alone."""

from __future__ import annotations

import logging
import sys

import structlog


def configure(is_production: bool) -> None:
    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if is_production
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "refund-agent") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
