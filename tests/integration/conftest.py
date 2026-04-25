import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.infrastructure.database import Base
import app.infrastructure.models  # noqa: F401 — registers all models


@pytest_asyncio.fixture
async def session():
    """
    Provides a fresh async session for each test.

    - Creates all tables if they don't exist (create_all is idempotent)
    - Yields the session for the test to use
    - Rolls back any changes after the test — no state leaks between tests
    - Disposes the engine cleanly
    """
    engine = create_async_engine(settings.TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s
        await s.rollback()

    await engine.dispose()
