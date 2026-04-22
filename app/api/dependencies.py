from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import AsyncSessionFactory
from app.repositories.inventory_repository import SqlAlchemyInventoryRepository
from app.repositories.order_repository import SqlAlchemyOrderRepository
from app.repositories.product_repository import SqlAlchemyProductRepository
from app.use_cases.cancel_order import CancelOrderUseCase
from app.use_cases.create_order import CreateOrderUseCase
from app.use_cases.get_order import GetOrderUseCase


async def get_session() -> AsyncSession:
    """
    Provides a DB session for the duration of a single request.
    Commits on success, rolls back on any exception.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Type alias — cleaner to read in route signatures
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# Use case factories — one per request, injected via FastAPI Depends
# ---------------------------------------------------------------------------

def get_create_order_use_case(session: SessionDep) -> CreateOrderUseCase:
    return CreateOrderUseCase(
        product_repo=SqlAlchemyProductRepository(session),
        inventory_repo=SqlAlchemyInventoryRepository(session),
        order_repo=SqlAlchemyOrderRepository(session),
    )


def get_cancel_order_use_case(session: SessionDep) -> CancelOrderUseCase:
    return CancelOrderUseCase(
        order_repo=SqlAlchemyOrderRepository(session),
        inventory_repo=SqlAlchemyInventoryRepository(session),
    )


def get_get_order_use_case(session: SessionDep) -> GetOrderUseCase:
    return GetOrderUseCase(
        order_repo=SqlAlchemyOrderRepository(session),
    )


def get_product_repository(session: SessionDep) -> SqlAlchemyProductRepository:
    return SqlAlchemyProductRepository(session)
