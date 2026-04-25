"""
Async order processing integration tests.

Tests the POST /orders/async -> GET /jobs/{job_id} flow.

These tests run with Celery in EAGER mode (CELERY_TASK_ALWAYS_EAGER=True),
which means tasks execute synchronously inside the same process instead of
being dispatched to a real Redis queue. This lets us test the full end-to-end
flow — including the worker logic — without needing a running Celery worker.

Run with: pytest tests/integration/test_async_orders.py -v
"""
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.infrastructure.database import Base
from app.main import app as fastapi_app
from app.api.dependencies import get_session
from app.worker.celery_app import celery_app
import app.infrastructure.models  # noqa: F401
from app.infrastructure.models import InventoryItemModel, ProductModel


# ---------------------------------------------------------------------------
# Run Celery tasks synchronously in tests (no real worker needed)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def celery_eager_mode():
    """
    Force Celery to execute tasks inline (synchronous) during tests,
    and redirect the worker's DB connection to the test database.

    The worker creates its own DB sessions at task execution time.
    We temporarily swap settings.DATABASE_URL to TEST_DATABASE_URL so
    those sessions hit the same DB the test fixtures use.
    """
    from app import config as cfg

    original_url = cfg.settings.DATABASE_URL
    cfg.settings.DATABASE_URL = cfg.settings.TEST_DATABASE_URL

    celery_app.conf.task_always_eager = True
    # Do NOT propagate task exceptions to the caller — this mirrors production:
    # a failing task marks the job as FAILED but the HTTP 202 is already sent.
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager = False
    cfg.settings.DATABASE_URL = original_url


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_session():
    engine = create_async_engine(settings.TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_session):
    async def override_get_session():
        # Expire all cached objects so every request reads fresh data from DB.
        # This is necessary in tests because the Celery task (running eagerly)
        # commits updates via its own sync session — the test session would
        # otherwise serve stale cached data on the next request.
        test_session.expire_all()
        try:
            yield test_session
            await test_session.commit()
        except Exception:
            await test_session.rollback()
            raise

    fastapi_app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://test",
    ) as c:
        yield c

    fastapi_app.dependency_overrides.clear()


async def seed_product(session, quantity: int = 10) -> uuid.UUID:
    product_id = uuid.uuid4()
    sku = f"ASYNC-{str(product_id)[:8]}"
    session.add(ProductModel(
        id=product_id, name="Async Test Product",
        sku=sku, price=Decimal("20.00"), is_active=True,
    ))
    session.add(InventoryItemModel(
        product_id=product_id, quantity=quantity, reserved=0, version=0,
    ))
    await session.flush()
    return product_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_async_order_returns_202_with_job_id(client, test_session):
    """POST /orders/async must return 202 Accepted with a job_id immediately."""
    product_id = await seed_product(test_session)

    response = await client.post("/orders/async", json={
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 1}],
    })

    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "PENDING"


async def test_async_order_job_completes_successfully(client, test_session):
    """
    In eager mode the worker runs inline — polling immediately should
    return COMPLETED with an order_id.
    """
    product_id = await seed_product(test_session)

    create_resp = await client.post("/orders/async", json={
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 2}],
    })
    job_id = create_resp.json()["job_id"]

    # In eager mode the task ran synchronously during the POST,
    # so the job should already be COMPLETED.
    status_resp = await client.get(f"/jobs/{job_id}")

    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == "COMPLETED"
    assert body["order_id"] is not None
    assert body["error"] is None


async def test_async_order_job_not_found_returns_404(client, test_session):
    """GET /jobs/{unknown_id} must return 404."""
    response = await client.get(f"/jobs/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_async_order_invalid_product_job_fails(client, test_session):
    """
    If the product doesn't exist, the worker should mark the job as FAILED
    and store the error message.
    """
    response = await client.post("/orders/async", json={
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}],
    })
    job_id = response.json()["job_id"]

    status_resp = await client.get(f"/jobs/{job_id}")
    body = status_resp.json()

    assert body["status"] == "FAILED"
    assert body["order_id"] is None
    assert body["error"] is not None


async def test_async_order_insufficient_stock_job_fails(client, test_session):
    """
    If there isn't enough inventory, the worker marks the job FAILED.
    """
    product_id = await seed_product(test_session, quantity=1)

    response = await client.post("/orders/async", json={
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 99}],
    })
    job_id = response.json()["job_id"]

    status_resp = await client.get(f"/jobs/{job_id}")
    body = status_resp.json()

    assert body["status"] == "FAILED"
    assert body["error"] is not None
