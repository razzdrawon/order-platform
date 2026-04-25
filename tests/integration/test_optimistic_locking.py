"""
Optimistic locking tests — verify that the version column on inventory_items
detects concurrent writes and raises OptimisticLockError.

Optimistic locking is a complement to SELECT FOR UPDATE:
- SELECT FOR UPDATE (pessimistic): blocks concurrent readers at read time.
- Optimistic locking: allows concurrent reads, detects conflicts at write time.

The version column is incremented on every UPDATE. If two transactions read
version=N and both try to write, only the first one to commit will find
version=N in the DB. The second will find version=N+1 and get rowcount=0,
which triggers OptimisticLockError.

Run with: pytest tests/integration/test_optimistic_locking.py -v
"""
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.infrastructure.database import Base
from app.infrastructure.models import InventoryItemModel, ProductModel
from app.domain.exceptions import OptimisticLockError
from app.repositories.inventory_repository import SqlAlchemyInventoryRepository

import app.infrastructure.models  # noqa: F401


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(settings.TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


async def seed(engine, quantity: int = 10) -> uuid.UUID:
    product_id = uuid.uuid4()
    sku = f"OPT-{str(product_id)[:8]}"
    async with AsyncSession(engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add(ProductModel(
                id=product_id, name="Optimistic Lock Product",
                sku=sku, price=Decimal("10.00"), is_active=True,
            ))
            session.add(InventoryItemModel(
                product_id=product_id, quantity=quantity, reserved=0, version=0,
            ))
    return product_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_version_starts_at_zero(engine):
    """Newly created inventory rows have version=0."""
    product_id = await seed(engine)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        repo = SqlAlchemyInventoryRepository(session)
        item = await repo.get_by_product_id(product_id, for_update=False)

    assert item.version == 0


async def test_version_increments_on_save(engine):
    """Each save increments the version by 1."""
    product_id = await seed(engine)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        repo = SqlAlchemyInventoryRepository(session)
        item = await repo.get_by_product_id(product_id, for_update=False)
        item.reserve(3)
        await repo.save(item)
        await session.commit()

    async with AsyncSession(engine, expire_on_commit=False) as session:
        repo = SqlAlchemyInventoryRepository(session)
        updated = await repo.get_by_product_id(product_id, for_update=False)

    assert updated.version == 1
    assert updated.reserved == 3


async def test_stale_write_raises_optimistic_lock_error(engine):
    """
    Two sessions read the same row (version=0).
    Session A writes first (version becomes 1).
    Session B tries to write with stale version=0 -> OptimisticLockError.
    """
    product_id = await seed(engine)

    # Both sessions read the same row at version=0
    session_a = AsyncSession(engine, expire_on_commit=False)
    session_b = AsyncSession(engine, expire_on_commit=False)

    repo_a = SqlAlchemyInventoryRepository(session_a)
    repo_b = SqlAlchemyInventoryRepository(session_b)

    item_a = await repo_a.get_by_product_id(product_id, for_update=False)
    item_b = await repo_b.get_by_product_id(product_id, for_update=False)

    assert item_a.version == 0
    assert item_b.version == 0

    # Session A writes successfully -> version becomes 1 in DB
    item_a.reserve(2)
    await repo_a.save(item_a)
    await session_a.commit()
    await session_a.close()

    # Session B tries to write with stale version=0 -> should fail
    item_b.reserve(2)
    with pytest.raises(OptimisticLockError):
        await repo_b.save(item_b)

    await session_b.rollback()
    await session_b.close()


async def test_version_in_db_reflects_only_committed_write(engine):
    """
    After a stale write is rejected, the DB version matches only the
    successful write — not the failed one.
    """
    product_id = await seed(engine)

    session_a = AsyncSession(engine, expire_on_commit=False)
    session_b = AsyncSession(engine, expire_on_commit=False)

    item_a = await SqlAlchemyInventoryRepository(session_a).get_by_product_id(product_id, for_update=False)
    item_b = await SqlAlchemyInventoryRepository(session_b).get_by_product_id(product_id, for_update=False)

    # A succeeds
    item_a.reserve(1)
    await SqlAlchemyInventoryRepository(session_a).save(item_a)
    await session_a.commit()
    await session_a.close()

    # B fails
    item_b.reserve(1)
    with pytest.raises(OptimisticLockError):
        await SqlAlchemyInventoryRepository(session_b).save(item_b)
    await session_b.rollback()
    await session_b.close()

    # Verify DB state: version=1, reserved=1 (only A's write)
    async with AsyncSession(engine, expire_on_commit=False) as verify:
        row = (await verify.execute(
            select(InventoryItemModel).where(InventoryItemModel.product_id == product_id)
        )).scalar_one()

    assert row.version == 1
    assert row.reserved == 1
