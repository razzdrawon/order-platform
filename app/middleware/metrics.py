"""
Prometheus HTTP metrics middleware.

Records http_requests_total and http_request_duration_seconds for every
request. Uses the FastAPI route template (e.g. /orders/{order_id}) instead
of the raw URL path to avoid label cardinality explosion from UUIDs.

This middleware runs after RequestContextMiddleware in the stack, so
request_id is already bound to the structlog context when it executes.
"""
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_TOTAL


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()

        response = await call_next(request)

        duration = time.perf_counter() - start

        # Use the matched route template so /orders/abc-123 and /orders/xyz-456
        # both map to the same label value: /orders/{order_id}
        route = request.scope.get("route")
        path = route.path if route else request.url.path

        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=path,
            status_code=response.status_code,
        ).inc()

        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            path=path,
        ).observe(duration)

        return response
