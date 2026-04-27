"""
Celery tasks for async order processing.

Celery tasks run in a regular synchronous context (not an async event loop).
To reuse the existing async use cases, we run them in a dedicated thread with
its own event loop via _run_async(). This avoids conflicts with any event loop
that may already be running in the current thread (e.g. during tests).

In production the worker process has no running event loop, so _run_async()
is equivalent to asyncio.run(). In tests with CELERY_TASK_ALWAYS_EAGER=True,
using a ThreadPoolExecutor sidesteps the "event loop already running" error.
"""
import asyncio
import concurrent.futures
import uuid

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.logging_config import configure_logging
from app.metrics import JOBS_COMPLETED_TOTAL, JOBS_FAILED_TOTAL
from app.worker.celery_app import celery_app

configure_logging()
logger = structlog.get_logger()
from app.infrastructure.models import JobModel
from app.use_cases.create_order import CreateOrderUseCase, CreateOrderRequest, OrderItemRequest

def _make_sync_session_factory():
    """Build a sync session factory from the current settings.

    Called at task execution time (not module load time) so that tests can
    override settings.DATABASE_URL before the factory is created.
    """
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _run_async(coro):
    """
    Run an async coroutine from a synchronous context.

    Executes in a fresh thread so it always gets a clean event loop,
    regardless of whether the calling thread already has one running.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


async def _execute_order(customer_id, items, idempotency_key):
    """
    Async wrapper that creates its own async engine + session for the worker.
    The worker can't reuse the main app's session because it runs in a
    different process (or thread in tests).
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    async_url = settings.DATABASE_URL  # already uses +asyncpg
    engine = create_async_engine(async_url, echo=False)
    AsyncWorkerSession = async_sessionmaker(engine, expire_on_commit=False)

    async with AsyncWorkerSession() as session:
        from app.repositories.product_repository import SqlAlchemyProductRepository
        from app.repositories.inventory_repository import SqlAlchemyInventoryRepository
        from app.repositories.order_repository import SqlAlchemyOrderRepository
        from app.repositories.idempotency_repository import SqlAlchemyIdempotencyKeyRepository

        use_case = CreateOrderUseCase(
            product_repo=SqlAlchemyProductRepository(session),
            inventory_repo=SqlAlchemyInventoryRepository(session),
            order_repo=SqlAlchemyOrderRepository(session),
            idempotency_repo=SqlAlchemyIdempotencyKeyRepository(session),
        )
        result = await use_case.execute(
            CreateOrderRequest(
                customer_id=uuid.UUID(customer_id),
                items=[
                    OrderItemRequest(
                        product_id=uuid.UUID(item["product_id"]),
                        quantity=item["quantity"],
                    )
                    for item in items
                ],
                idempotency_key=idempotency_key,
            )
        )
        await session.commit()

    await engine.dispose()
    return result


@celery_app.task(bind=True, max_retries=3, default_retry_delay=2)
def process_order(
    self,
    job_id: str,
    customer_id: str,
    items: list[dict],
    idempotency_key: str | None = None,
):
    """
    Process an order asynchronously.

    1. Updates the Job status to PROCESSING
    2. Runs CreateOrderUseCase via a dedicated async event loop
    3. Updates the Job with the resulting order_id and COMPLETED status
    4. On failure: updates the Job with FAILED status and the error message
    """
    # Bind task-level context so every log line from this task carries these fields.
    # The worker has no HTTP request context, so we use the Celery task ID instead.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        task_id=self.request.id,
        job_id=job_id,
    )

    SyncSessionFactory = _make_sync_session_factory()

    with SyncSessionFactory() as session:
        job = session.get(JobModel, uuid.UUID(job_id))
        if job is None:
            logger.warning("worker.job_not_found", job_id=job_id)
            return  # Job was deleted before the worker picked it up
        job.status = "PROCESSING"
        session.commit()

    logger.info("worker.task_started", customer_id=customer_id, item_count=len(items))

    try:
        result = _run_async(
            _execute_order(customer_id, items, idempotency_key)
        )

        with SyncSessionFactory() as session:
            job = session.get(JobModel, uuid.UUID(job_id))
            job.status = "COMPLETED"
            job.order_id = result.order_id
            session.commit()

        JOBS_COMPLETED_TOTAL.inc()
        logger.info("worker.task_completed", order_id=str(result.order_id))

    except Exception as exc:
        with SyncSessionFactory() as session:
            job = session.get(JobModel, uuid.UUID(job_id))
            if job:
                job.status = "FAILED"
                job.error = str(exc)
                session.commit()

        JOBS_FAILED_TOTAL.inc()
        logger.error("worker.task_failed", error=str(exc))
        raise
