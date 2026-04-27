"""
API integration tests.

Uses FastAPI's test client (httpx) against a real test DB.
Each test gets a fresh DB session — no state leaks between tests.

Run with: pytest tests/integration/test_order_api.py -v
"""
import pytest
import pytest_asyncio
from decimal import Decimal
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.infrastructure.database import Base
from app.main import app as fastapi_app
from app.api.dependencies import get_session
import app.infrastructure.models  # noqa: F401

from app.infrastructure.models import InventoryItemModel, ProductModel


# ---------------------------------------------------------------------------
# Test DB setup — override the session dependency with the test DB
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
    """HTTP client wired to the test DB session."""

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


# ---------------------------------------------------------------------------
# Helpers — seed test data directly into the test session
# ---------------------------------------------------------------------------

async def seed_product_and_inventory(session, price="50.00", quantity=20):
    import uuid
    product_id = uuid.uuid4()
    sku = f"TEST-{str(product_id)[:8]}"  # unique SKU per call
    session.add(ProductModel(
        id=product_id,
        name="Test Product",
        sku=sku,
        price=Decimal(price),
        is_active=True,
    ))
    session.add(InventoryItemModel(
        product_id=product_id,
        quantity=quantity,
        reserved=0,
    ))
    await session.flush()
    return product_id


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def test_health_check(client):
    response = await client.get("/health")
    body = response.json()
    # Status is 200 (healthy) or 503 (degraded) depending on available services.
    # In CI only PostgreSQL is guaranteed — Redis may not be running.
    assert response.status_code in (200, 503)
    assert body["status"] in ("healthy", "degraded")
    assert "database" in body["checks"]
    assert "redis" in body["checks"]
    # Database must always be reachable in integration tests
    assert body["checks"]["database"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

async def test_list_products_returns_active_only(client, test_session):
    import uuid
    uid = str(uuid.uuid4())[:8]
    test_session.add(ProductModel(
        id=uuid.uuid4(), name="Active", sku=f"ACT-{uid}",
        price=Decimal("10.00"), is_active=True,
    ))
    test_session.add(ProductModel(
        id=uuid.uuid4(), name="Inactive", sku=f"INA-{uid}",
        price=Decimal("5.00"), is_active=False,
    ))
    await test_session.flush()
    active_sku = f"ACT-{uid}"
    inactive_sku = f"INA-{uid}"

    response = await client.get("/products")

    assert response.status_code == 200
    skus = [p["sku"] for p in response.json()]
    assert active_sku in skus
    assert inactive_sku not in skus


# ---------------------------------------------------------------------------
# Create order
# ---------------------------------------------------------------------------

async def test_create_order_success(client, test_session):
    import uuid
    product_id = await seed_product_and_inventory(test_session, quantity=10)

    response = await client.post("/orders", json={
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 3}],
    })

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CONFIRMED"
    assert body["total_amount"] == "150.00"
    assert "order_id" in body


async def test_create_order_insufficient_stock_returns_422(client, test_session):
    import uuid
    product_id = await seed_product_and_inventory(test_session, quantity=2)

    response = await client.post("/orders", json={
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 99}],
    })

    assert response.status_code == 422


async def test_create_order_unknown_product_returns_422(client, test_session):
    import uuid
    response = await client.post("/orders", json={
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}],
    })

    assert response.status_code == 422


async def test_create_order_empty_items_returns_422(client, test_session):
    import uuid
    response = await client.post("/orders", json={
        "customer_id": str(uuid.uuid4()),
        "items": [],
    })

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Get order
# ---------------------------------------------------------------------------

async def test_get_order_success(client, test_session):
    import uuid
    product_id = await seed_product_and_inventory(test_session)
    customer_id = str(uuid.uuid4())

    create_resp = await client.post("/orders", json={
        "customer_id": customer_id,
        "items": [{"product_id": str(product_id), "quantity": 1}],
    })
    order_id = create_resp.json()["order_id"]

    response = await client.get(f"/orders/{order_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == order_id
    assert body["status"] == "CONFIRMED"
    assert len(body["items"]) == 1


async def test_get_order_not_found_returns_404(client, test_session):
    import uuid
    response = await client.get(f"/orders/{uuid.uuid4()}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Cancel order
# ---------------------------------------------------------------------------

async def test_cancel_confirmed_order_returns_409(client, test_session):
    import uuid
    product_id = await seed_product_and_inventory(test_session)

    create_resp = await client.post("/orders", json={
        "customer_id": str(uuid.uuid4()),
        "items": [{"product_id": str(product_id), "quantity": 2}],
    })
    order_id = create_resp.json()["order_id"]

    response = await client.patch(f"/orders/{order_id}/cancel")
    assert response.status_code == 409


async def test_cancel_nonexistent_order_returns_404(client, test_session):
    import uuid
    response = await client.patch(f"/orders/{uuid.uuid4()}/cancel")
    assert response.status_code == 404
