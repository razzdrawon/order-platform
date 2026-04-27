from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes import jobs, orders, products
from app.logging_config import configure_logging
from app.middleware.metrics import PrometheusMiddleware
from app.middleware.request_context import RequestContextMiddleware

configure_logging()

app = FastAPI(
    title="Order Orchestration Platform",
    description="Distributed order management with atomic inventory reservation",
    version="0.1.0",
)

# Middleware executes in reverse registration order (last added = outermost).
# PrometheusMiddleware is added first so it wraps everything, including the
# request context middleware — this ensures HTTP metrics are recorded even
# if the request context middleware raises.
app.add_middleware(PrometheusMiddleware)
app.add_middleware(RequestContextMiddleware)

app.include_router(orders.router)
app.include_router(products.router)
app.include_router(jobs.router)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}


@app.get("/metrics", tags=["observability"], response_class=PlainTextResponse)
async def metrics():
    """
    Prometheus metrics endpoint.

    Returns all registered metrics in the Prometheus text exposition format.
    Scrape this endpoint with a Prometheus server every 15s.
    """
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
