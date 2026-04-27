from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes import health, jobs, orders, products
from app.events import producer as kafka_producer
from app.logging_config import configure_logging
from app.middleware.metrics import PrometheusMiddleware
from app.middleware.request_context import RequestContextMiddleware

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup (before the first request) and on shutdown.

    Used to initialize and cleanly close resources that must live for the
    entire process lifetime — in this case the Kafka producer.
    FastAPI's Depends() is per-request; lifespan is per-process.
    """
    await kafka_producer.start_producer()
    yield
    await kafka_producer.stop_producer()


app = FastAPI(
    title="Order Orchestration Platform",
    description="Distributed order management with atomic inventory reservation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(PrometheusMiddleware)
app.add_middleware(RequestContextMiddleware)

app.include_router(orders.router)
app.include_router(products.router)
app.include_router(jobs.router)
app.include_router(health.router)


@app.get("/metrics", tags=["observability"], response_class=PlainTextResponse)
async def metrics():
    """Prometheus metrics endpoint. Scrape every 15s."""
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
