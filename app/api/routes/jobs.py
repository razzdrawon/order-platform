"""
Async order processing routes.

POST /orders/async  — enqueues an order processing job, returns 202 immediately
GET  /jobs/{job_id} — polls the status of an enqueued job
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import SessionDep
from app.api.schemas import AcceptedResponse, CreateOrderRequest, JobStatusResponse
from app.infrastructure.models import JobModel
from app.worker.tasks import process_order

router = APIRouter(tags=["jobs"])


@router.post(
    "/orders/async",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedResponse,
)
async def create_order_async(
    body: CreateOrderRequest,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """
    Enqueue an order for async processing.

    Returns 202 immediately with a job_id. The order is processed in the
    background by a Celery worker. Poll GET /jobs/{job_id} for the result.
    """
    # Create the Job record first so the client can start polling right away
    job = JobModel(status="PENDING")
    session.add(job)
    await session.flush()   # assigns job.id without committing yet
    await session.commit()

    # Dispatch the Celery task — this is non-blocking (just sends a message to Redis)
    process_order.delay(
        job_id=str(job.id),
        customer_id=str(body.customer_id),
        items=[
            {"product_id": str(item.product_id), "quantity": item.quantity}
            for item in body.items
        ],
        idempotency_key=idempotency_key,
    )

    return AcceptedResponse(job_id=job.id)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: UUID, session: SessionDep):
    """Poll the status of an async order processing job."""
    job = await session.get(JobModel, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        order_id=job.order_id,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )
