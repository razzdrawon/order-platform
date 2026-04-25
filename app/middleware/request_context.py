"""
Request context middleware.

For every incoming HTTP request:
  1. Reads or generates a request_id (from X-Request-ID header or a new UUID)
  2. Binds it to structlog's context — every log call within the request
     automatically includes request_id without any manual passing
  3. Also binds the HTTP method and path for easy filtering in log aggregators
  4. Logs request received and request completed (with status code + duration)
  5. Clears the context after the response so no fields leak to the next request

The X-Request-ID header lets clients (or API gateways) inject their own
correlation ID, which makes it possible to trace a request across multiple
services even before OpenTelemetry is wired up.
"""
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Respect an incoming correlation ID or generate a fresh one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

        # Clear any leftover bindings from a previous request on this worker
        structlog.contextvars.clear_contextvars()

        # Bind fields that will appear in every log line for this request
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
        )

        start = time.perf_counter()
        logger.info("http.request_received")

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("http.request_failed")
            raise
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            structlog.contextvars.bind_contextvars(duration_ms=duration_ms)

        logger.info(
            "http.request_completed",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        # Forward the request_id to the client so they can correlate with their logs
        response.headers["X-Request-ID"] = request_id

        structlog.contextvars.clear_contextvars()
        return response
