"""Structured JSON logging so logs are queryable once deployed on Render/Railway."""
import logging
import sys

import structlog

from app.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
