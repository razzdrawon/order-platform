"""
GetOrder use case.

Simple query — loads and returns an order by ID.
"""
from dataclasses import dataclass
from uuid import UUID

from app.domain.models import Order
from app.repositories.base import AbstractOrderRepository
from app.use_cases.cancel_order import OrderNotFoundError


@dataclass
class GetOrderRequest:
    order_id: UUID


class GetOrderUseCase:

    def __init__(self, order_repo: AbstractOrderRepository) -> None:
        self._orders = order_repo

    def execute(self, request: GetOrderRequest) -> Order:
        order = self._orders.get_by_id(request.order_id)
        if order is None:
            raise OrderNotFoundError(request.order_id)
        return order
