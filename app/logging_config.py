"""
Structlog configuration for the Order Orchestration Platform.

Two rendering modes controlled by the LOG_JSON environment variable:

  LOG_JSON=true  (production / Docker)
    → One JSON object per line. Easy to ingest by Datadog, CloudWatch, etc.
    {"timestamp": "...", "level": "info", "event": "order.created", "order_id": "..."}

  LOG_JSON=false (default — local development)
    → Human-readable colored output with aligned columns.
    2026-04-25 21:00:00 [info     ] order.created   order_id=abc-123

structlog.contextvars stores per-request bindings (request_id, etc.) in a
Python ContextVar, which is automatically isolated per async task / thread.
This is how request_id flows through the entire call chain without being
passed as a function argument.
"""
import logging
import os

import structlog


def configure_logging() -> None:
    """Call once at application startup (app/main.py)."""

    json_mode = os.getenv("LOG_JSON", "false").lower() == "true"

    # Processors run in order on every log call.
    # Each receives (logger, method, event_dict) and returns a modified event_dict.
    shared_processors: list = [
        # Inject anything bound via structlog.contextvars.bind_contextvars()
        structlog.contextvars.merge_contextvars,
        # Add the log level as a string field
        structlog.stdlib.add_log_level,
        # Add ISO-8601 timestamp
        structlog.processors.TimeStamper(fmt="iso"),
        # Format exceptions as a string in the event_dict
        structlog.processors.format_exc_info,
    ]

    if json_mode:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
