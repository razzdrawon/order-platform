from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.enums import OrderStatus
from app.domain.models import Order, OrderItem
from app.infrastructure.models import OrderItemModel, OrderModel
from app.repositories.base import AbstractOrderRepository


class SqlAlchemyOrderRepository(AbstractOrderRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_domain(row: OrderModel) -> Order:
        return Order(
            id=row.id,
            customer_id=row.customer_id,
            status=OrderStatus(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
            items=[
                OrderItem(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )
                for item in row.items
            ],
        )

    @staticmethod
    def _to_orm(order: Order) -> OrderModel:
        return OrderModel(
            id=order.id,
            customer_id=order.customer_id,
            status=order.status.value,
            created_at=order.created_at,
            updated_at=order.updated_at,
            items=[
                OrderItemModel(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )
                for item in order.items
            ],
        )

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    async def get_by_id(self, order_id: UUID) -> Order | None:
        # selectinload eagerly loads the related items in a second query,
        # avoiding the N+1 problem and lazy load errors with async sessions.
        result = await self._session.execute(
            select(OrderModel)
            .where(OrderModel.id == order_id)
            .options(selectinload(OrderModel.items))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, order: Order) -> None:
        result = await self._session.execute(
            select(OrderModel)
            .where(OrderModel.id == order.id)
            .options(selectinload(OrderModel.items))
        )
        row = result.scalar_one_or_none()

        if row is None:
            self._session.add(self._to_orm(order))
        else:
            # Update scalar fields
            row.status = order.status.value
            row.updated_at = order.updated_at
            # Replace items — cascade delete-orphan handles cleanup
            row.items = [
                OrderItemModel(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )
                for item in order.items
            ]
