from dataclasses import dataclass
from uuid import UUID

import structlog

from app.domain.exceptions import DomainException
from app.domain.services import OrderReservationService
from app.repositories.base import AbstractInventoryRepository, AbstractOrderRepository


class OrderNotFoundError(DomainException):
    def __init__(self, order_id: UUID):
        super().__init__(f"Order {order_id} not found")
        self.order_id = order_id


@dataclass
class CancelOrderRequest:
    order_id: UUID


@dataclass
class CancelOrderResult:
    order_id: UUID
    status: str


logger = structlog.get_logger()


class CancelOrderUseCase:

    def __init__(
        self,
        order_repo: AbstractOrderRepository,
        inventory_repo: AbstractInventoryRepository,
        reservation_service: OrderReservationService | None = None,
    ) -> None:
        self._orders = order_repo
        self._inventory = inventory_repo
        self._reservation = reservation_service or OrderReservationService()

    async def execute(self, request: CancelOrderRequest) -> CancelOrderResult:
        order = await self._orders.get_by_id(request.order_id)
        if order is None:
            raise OrderNotFoundError(request.order_id)

        order.cancel()

        product_ids = [item.product_id for item in order.items]
        inventory = await self._inventory.get_by_product_ids(product_ids)
        self._reservation.release(order, inventory)

        await self._orders.save(order)
        await self._inventory.save_many(list(inventory.values()))

        logger.info("order.cancelled", order_id=str(order.id))

        return CancelOrderResult(order_id=order.id, status=order.status.value)
