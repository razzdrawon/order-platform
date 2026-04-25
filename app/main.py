from fastapi import FastAPI

from app.api.routes import jobs, orders, products
from app.logging_config import configure_logging
from app.middleware.request_context import RequestContextMiddleware

configure_logging()

app = FastAPI(
    title="Order Orchestration Platform",
    description="Distributed order management with atomic inventory reservation",
    version="0.1.0",
)

app.add_middleware(RequestContextMiddleware)

app.include_router(orders.router)
app.include_router(products.router)
app.include_router(jobs.router)


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}
