"""
Concurrency tests — verify that SELECT FOR UPDATE prevents overselling.

These tests simulate multiple concurrent requests competing for the same
inventory. Without row-level locking, both requests would read available=1,
both would reserve, and we'd end up with reserved > quantity (oversell).

With SELECT FOR UPDATE, the second transaction blocks until the first commits,
then reads the updated reserved count and correctly raises InsufficientInventoryError.

Run with: pytest tests/integration/test_concurrency.py -v
"""
import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.infrastructure.database import Base
from app.infrastructure.models import InventoryItemModel, ProductModel

import app.infrastructure.models  # noqa: F401

from app.repositories.inventory_repository import SqlAlchemyInventoryRepository
from app.repositories.order_repository import SqlAlchemyOrderRepository
from app.repositories.product_repository import SqlAlchemyProductRepository
from app.use_cases.create_order import CreateOrderUseCase, CreateOrderRequest, OrderItemRequest
from app.domain.exceptions import InsufficientInventoryError


# ---------------------------------------------------------------------------
# Shared test engine — all concurrency tests share one engine so they can
# open multiple *independent* sessions (sessions that don't share a transaction).
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(settings.TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


async def make_session(engine) -> AsyncSession:
    """Open a brand-new independent session (its own transaction)."""
    return AsyncSession(engine, expire_on_commit=False)


async def seed_product_with_stock(engine, quantity: int) -> uuid.UUID:
    """Insert a product + inventory row and commit so all sessions can see it."""
    product_id = uuid.uuid4()
    sku = f"CONC-{str(product_id)[:8]}"
    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add(ProductModel(
                id=product_id, name="Concurrent Product",
                sku=sku, price=Decimal("10.00"), is_active=True,
            ))
            session.add(InventoryItemModel(
                product_id=product_id, quantity=quantity, reserved=0,
            ))
    return product_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_concurrent_orders_only_one_succeeds(engine):
    """
    Two concurrent requests compete for the last 1 unit.
    Expected: exactly one succeeds (201), the other fails with
    InsufficientInventoryError (would map to 422 in the API).
    """
    product_id = await seed_product_with_stock(engine, quantity=1)
    customer_a = uuid.uuid4()
    customer_b = uuid.uuid4()

    async def place_order(customer_id: uuid.UUID) -> str:
        session = await make_session(engine)
        try:
            use_case = CreateOrderUseCase(
                product_repo=SqlAlchemyProductRepository(session),
                inventory_repo=SqlAlchemyInventoryRepository(session),
                order_repo=SqlAlchemyOrderRepository(session),
            )
            result = await use_case.execute(
                CreateOrderRequest(
                    customer_id=customer_id,
                    items=[OrderItemRequest(product_id=product_id, quantity=1)],
                )
            )
            await session.commit()
            return f"SUCCESS:{result.order_id}"
        except InsufficientInventoryError:
            await session.rollback()
            return "INSUFFICIENT_INVENTORY"
        except Exception as e:
            await session.rollback()
            return f"ERROR:{e}"
        finally:
            await session.close()

    results = await asyncio.gather(
        place_order(customer_a),
        place_order(customer_b),
    )

    successes = [r for r in results if r.startswith("SUCCESS")]
    failures = [r for r in results if r == "INSUFFICIENT_INVENTORY"]

    assert len(successes) == 1, f"Expected exactly 1 success, got: {results}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got: {results}"


async def test_concurrent_orders_enough_stock_both_succeed(engine):
    """
    Two concurrent requests, 10 units available, each requests 3.
    Both should succeed — locking shouldn't block valid concurrent orders.
    """
    product_id = await seed_product_with_stock(engine, quantity=10)
    customer_a = uuid.uuid4()
    customer_b = uuid.uuid4()

    async def place_order(customer_id: uuid.UUID, qty: int) -> str:
        session = await make_session(engine)
        try:
            use_case = CreateOrderUseCase(
                product_repo=SqlAlchemyProductRepository(session),
                inventory_repo=SqlAlchemyInventoryRepository(session),
                order_repo=SqlAlchemyOrderRepository(session),
            )
            result = await use_case.execute(
                CreateOrderRequest(
                    customer_id=customer_id,
                    items=[OrderItemRequest(product_id=product_id, quantity=qty)],
                )
            )
            await session.commit()
            return f"SUCCESS:{result.order_id}"
        except InsufficientInventoryError:
            await session.rollback()
            return "INSUFFICIENT_INVENTORY"
        finally:
            await session.close()

    results = await asyncio.gather(
        place_order(customer_a, 3),
        place_order(customer_b, 3),
    )

    successes = [r for r in results if r.startswith("SUCCESS")]
    assert len(successes) == 2, f"Both should succeed, got: {results}"


async def test_concurrent_orders_combined_exceeds_stock(engine):
    """
    Two concurrent requests, 5 units available, each requests 4.
    Combined demand (8) exceeds stock (5) — exactly one must fail.
    """
    product_id = await seed_product_with_stock(engine, quantity=5)
    customer_a = uuid.uuid4()
    customer_b = uuid.uuid4()

    async def place_order(customer_id: uuid.UUID, qty: int) -> str:
        session = await make_session(engine)
        try:
            use_case = CreateOrderUseCase(
                product_repo=SqlAlchemyProductRepository(session),
                inventory_repo=SqlAlchemyInventoryRepository(session),
                order_repo=SqlAlchemyOrderRepository(session),
            )
            result = await use_case.execute(
                CreateOrderRequest(
                    customer_id=customer_id,
                    items=[OrderItemRequest(product_id=product_id, quantity=qty)],
                )
            )
            await session.commit()
            return f"SUCCESS:{result.order_id}"
        except InsufficientInventoryError:
            await session.rollback()
            return "INSUFFICIENT_INVENTORY"
        finally:
            await session.close()

    results = await asyncio.gather(
        place_order(customer_a, 4),
        place_order(customer_b, 4),
    )

    successes = [r for r in results if r.startswith("SUCCESS")]
    failures = [r for r in results if r == "INSUFFICIENT_INVENTORY"]

    assert len(successes) == 1, f"Expected exactly 1 success, got: {results}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got: {results}"


async def test_inventory_reserved_count_is_accurate_after_concurrent_orders(engine):
    """
    After concurrent orders complete, the reserved count in DB should be
    exactly equal to the quantity that was successfully ordered — no more.
    """
    product_id = await seed_product_with_stock(engine, quantity=10)

    async def place_order(customer_id: uuid.UUID, qty: int) -> bool:
        session = await make_session(engine)
        try:
            use_case = CreateOrderUseCase(
                product_repo=SqlAlchemyProductRepository(session),
                inventory_repo=SqlAlchemyInventoryRepository(session),
                order_repo=SqlAlchemyOrderRepository(session),
            )
            await use_case.execute(
                CreateOrderRequest(
                    customer_id=customer_id,
                    items=[OrderItemRequest(product_id=product_id, quantity=qty)],
                )
            )
            await session.commit()
            return True
        except InsufficientInventoryError:
            await session.rollback()
            return False
        finally:
            await session.close()

    # Launch 5 concurrent orders of 3 units each (total demand: 15, stock: 10)
    results = await asyncio.gather(*[
        place_order(uuid.uuid4(), 3) for _ in range(5)
    ])

    successes = sum(results)
    failures = len(results) - successes

    # Verify the DB state is consistent — reserved = successes * 3
    async with AsyncSession(engine, expire_on_commit=False) as verify_session:
        from sqlalchemy import select
        row = (await verify_session.execute(
            select(InventoryItemModel).where(
                InventoryItemModel.product_id == product_id
            )
        )).scalar_one()

    expected_reserved = successes * 3
    assert row.reserved == expected_reserved, (
        f"reserved={row.reserved}, expected={expected_reserved} "
        f"({successes} orders × 3 units)"
    )
    assert row.reserved <= row.quantity, "reserved must never exceed total quantity"
    assert failures > 0, "With only 10 units and 5 orders of 3, some must fail"
