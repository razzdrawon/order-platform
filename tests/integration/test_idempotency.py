"""
Idempotency key integration tests.

Verifies that sending the same Idempotency-Key header on repeated requests
returns the same response without creating duplicate orders or touching inventory
a second time.

Run with: pytest tests/integration/test_idempotency.py -v
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
import app.infrastructure.models  # noqa: F401
from app.infrastructure.models import InventoryItemModel, ProductModel


# ---------------------------------------------------------------------------
# Fixtures — same pattern as test_order_api.py
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


async def seed_product(session, price="25.00", quantity=50):
    product_id = uuid.uuid4()
    sku = f"IDEM-{str(product_id)[:8]}"
    session.add(ProductModel(
        id=product_id, name="Idempotency Test Product",
        sku=sku, price=Decimal(price), is_active=True,
    ))
    session.add(InventoryItemModel(
        product_id=product_id, quantity=quantity, reserved=0,
    ))
    await session.flush()
    return product_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_same_idempotency_key_returns_same_order(client, test_session):
    """
    Two requests with the same Idempotency-Key must return identical responses.
    The order_id must be the same — no duplicate order created.
    """
    product_id = await seed_product(test_session)
    idempotency_key = str(uuid.uuid4())
    payload = {
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 2}],
    }

    first = await client.post(
        "/orders", json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )
    second = await client.post(
        "/orders", json=payload,
        headers={"Idempotency-Key": idempotency_key},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["order_id"] == second.json()["order_id"]
    assert first.json()["total_amount"] == second.json()["total_amount"]


async def test_idempotency_does_not_reserve_inventory_twice(client, test_session):
    """
    Inventory reserved count must reflect only ONE order, not two,
    even when the same Idempotency-Key is sent twice.
    """
    from sqlalchemy import select

    product_id = await seed_product(test_session, quantity=10)
    idempotency_key = str(uuid.uuid4())
    payload = {
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 3}],
    }

    await client.post("/orders", json=payload, headers={"Idempotency-Key": idempotency_key})
    await client.post("/orders", json=payload, headers={"Idempotency-Key": idempotency_key})

    # Refresh the inventory from DB
    await test_session.rollback()
    row = (await test_session.execute(
        select(InventoryItemModel).where(InventoryItemModel.product_id == product_id)
    )).scalar_one()

    # Only 3 reserved — not 6
    assert row.reserved == 3, f"Expected reserved=3, got {row.reserved}"


async def test_different_idempotency_keys_create_separate_orders(client, test_session):
    """
    Two requests with *different* Idempotency-Keys must create two separate orders.
    """
    product_id = await seed_product(test_session, quantity=20)
    customer_id = str(uuid.uuid4())
    payload = {
        "customer_id": customer_id,
        "items": [{"product_id": str(product_id), "quantity": 1}],
    }

    first = await client.post(
        "/orders", json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    second = await client.post(
        "/orders", json=payload,
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["order_id"] != second.json()["order_id"]


async def test_request_without_idempotency_key_works_normally(client, test_session):
    """
    The Idempotency-Key header is optional. Requests without it behave
    exactly as before — no regression.
    """
    product_id = await seed_product(test_session)

    response = await client.post("/orders", json={
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 1}],
    })

    assert response.status_code == 201
    assert "order_id" in response.json()


async def test_repeated_request_without_key_creates_duplicate(client, test_session):
    """
    Without an Idempotency-Key, retries DO create duplicate orders.
    This test documents the expected behavior — it's the problem
    idempotency keys solve.
    """
    product_id = await seed_product(test_session, quantity=20)
    payload = {
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 1}],
    }

    first = await client.post("/orders", json=payload)
    second = await client.post("/orders", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    # Without a key, two different orders are created
    assert first.json()["order_id"] != second.json()["order_id"]
