"""Structured JSON logging so logs are queryable once deployed on Render/Railway.

CRITICAL: this must log to stderr, never stdout. app/mcp_servers/github_mcp.py
runs as an MCP stdio server subprocess, and the MCP stdio transport reserves
stdout exclusively for JSON-RPC protocol messages. Any log line written to
stdout corrupts that stream and causes 'Failed to parse JSONRPC message from
server' errors on the client side, silently breaking every tool call.
"""
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
