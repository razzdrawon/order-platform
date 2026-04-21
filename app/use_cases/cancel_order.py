"""
CancelOrder use case.

Responsibilities:
1. Load the order — raise if not found
2. Attempt cancellation (domain enforces status rules)
3. Release reserved inventory
4. Persist updated order and inventory
"""
from dataclasses import dataclass
from uuid import UUID

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

    def execute(self, request: CancelOrderRequest) -> CancelOrderResult:
        # 1. Load order
        order = self._orders.get_by_id(request.order_id)
        if order is None:
            raise OrderNotFoundError(request.order_id)

        # 2. Cancel (raises InvalidOrderTransitionError if not allowed)
        order.cancel()

        # 3. Release inventory
        product_ids = [item.product_id for item in order.items]
        inventory = self._inventory.get_by_product_ids(product_ids)
        self._reservation.release(order, inventory)

        # 4. Persist
        self._orders.save(order)
        self._inventory.save_many(list(inventory.values()))

        return CancelOrderResult(order_id=order.id, status=order.status.value)
