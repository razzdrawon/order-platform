"""
Health check endpoint.

Returns the operational status of the service and its dependencies.
Used by load balancers, container orchestrators (Kubernetes), and
monitoring systems to decide whether to route traffic to this instance.

Response contract:
  200 — all checks passed, service is healthy
  503 — one or more checks failed, service should not receive traffic

Each check includes a latency_ms field so slow dependencies are visible
even when they are technically "up".
"""
import time

import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.infrastructure.database import AsyncSessionFactory

router = APIRouter(tags=["health"])


async def _check_database() -> dict:
    try:
        start = time.perf_counter()
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


async def _check_redis() -> dict:
    try:
        start = time.perf_counter()
        client = aioredis.from_url(settings.CELERY_BROKER_URL)
        await client.ping()
        await client.aclose()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/health")
async def health_check():
    checks = {
        "database": await _check_database(),
        "redis": await _check_redis(),
    }

    all_healthy = all(c["status"] == "ok" for c in checks.values())
    overall = "healthy" if all_healthy else "degraded"
    status_code = 200 if all_healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={"status": overall, "checks": checks},
    )
