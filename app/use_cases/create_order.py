from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.exceptions import DomainException
from app.domain.models import Order, OrderItem
from app.domain.services import OrderReservationService
from app.repositories.base import (
    AbstractInventoryRepository,
    AbstractOrderRepository,
    AbstractProductRepository,
)


class ProductNotFoundError(DomainException):
    def __init__(self, product_id: UUID):
        super().__init__(f"Product {product_id} not found or inactive")
        self.product_id = product_id


@dataclass
class OrderItemRequest:
    product_id: UUID
    quantity: int


@dataclass
class CreateOrderRequest:
    customer_id: UUID
    items: list[OrderItemRequest]


@dataclass
class CreateOrderResult:
    order_id: UUID
    total_amount: Decimal
    status: str


class CreateOrderUseCase:

    def __init__(
        self,
        product_repo: AbstractProductRepository,
        inventory_repo: AbstractInventoryRepository,
        order_repo: AbstractOrderRepository,
        reservation_service: OrderReservationService | None = None,
    ) -> None:
        self._products = product_repo
        self._inventory = inventory_repo
        self._orders = order_repo
        self._reservation = reservation_service or OrderReservationService()

    async def execute(self, request: CreateOrderRequest) -> CreateOrderResult:
        if not request.items:
            raise DomainException("Order must contain at least one item")

        # 1. Validate products
        product_ids = [item.product_id for item in request.items]
        products = {
            str(pid): await self._products.get_by_id(pid) for pid in product_ids
        }
        for pid, product in products.items():
            if product is None or not product.is_active:
                raise ProductNotFoundError(UUID(pid))

        # 2. Load inventory
        inventory = await self._inventory.get_by_product_ids(product_ids)

        # 3. Build Order with frozen prices
        order_items = [
            OrderItem(
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=products[str(item.product_id)].price,
            )
            for item in request.items
        ]
        order = Order(customer_id=request.customer_id, items=order_items)

        # 4. Reserve inventory
        self._reservation.reserve(order, inventory)

        # 5. Confirm and persist
        order.confirm()
        await self._orders.save(order)
        await self._inventory.save_many(list(inventory.values()))

        return CreateOrderResult(
            order_id=order.id,
            total_amount=order.total_amount,
            status=order.status.value,
        )
