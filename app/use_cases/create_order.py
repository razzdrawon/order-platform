import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import structlog

from app.domain.exceptions import DomainException, OptimisticLockError
from app.metrics import INVENTORY_ERRORS_TOTAL, ORDERS_CREATED_TOTAL
from app.domain.models import Order, OrderItem
from app.domain.services import OrderReservationService
from app.repositories.base import (
    AbstractIdempotencyKeyRepository,
    AbstractInventoryRepository,
    AbstractOrderRepository,
    AbstractProductRepository,
    StoredIdempotencyKey,
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
    idempotency_key: str | None = None  # Optional — clients send this to enable safe retries


@dataclass
class CreateOrderResult:
    order_id: UUID
    total_amount: Decimal
    status: str
    from_cache: bool = False  # True when the response was replayed from a previous request


logger = structlog.get_logger()


class CreateOrderUseCase:

    def __init__(
        self,
        product_repo: AbstractProductRepository,
        inventory_repo: AbstractInventoryRepository,
        order_repo: AbstractOrderRepository,
        reservation_service: OrderReservationService | None = None,
        idempotency_repo: AbstractIdempotencyKeyRepository | None = None,
    ) -> None:
        self._products = product_repo
        self._inventory = inventory_repo
        self._orders = order_repo
        self._reservation = reservation_service or OrderReservationService()
        self._idempotency = idempotency_repo

    _MAX_RETRIES = 3

    async def execute(self, request: CreateOrderRequest) -> CreateOrderResult:
        last_error: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                return await self._execute_once(request)
            except OptimisticLockError as exc:
                last_error = exc
                INVENTORY_ERRORS_TOTAL.labels(error_type="optimistic_lock").inc()
                logger.warning(
                    "order.optimistic_lock_retry",
                    attempt=attempt + 1,
                    max_retries=self._MAX_RETRIES,
                    customer_id=str(request.customer_id),
                )
                if attempt == self._MAX_RETRIES - 1:
                    raise
        raise last_error  # unreachable, satisfies type checker

    async def _execute_once(self, request: CreateOrderRequest) -> CreateOrderResult:
        if not request.items:
            raise DomainException("Order must contain at least one item")

        # 0. Idempotency check — if this key was already processed, replay
        #    the stored result without touching inventory or creating a new order.
        if request.idempotency_key and self._idempotency:
            existing = await self._idempotency.get(request.idempotency_key)
            if existing:
                cached = json.loads(existing.response_body)
                logger.info(
                    "order.idempotency_cache_hit",
                    idempotency_key=request.idempotency_key,
                    order_id=str(existing.order_id),
                )
                return CreateOrderResult(
                    order_id=existing.order_id,
                    total_amount=Decimal(cached["total_amount"]),
                    status=cached["status"],
                    from_cache=True,
                )

        # 1. Validate products
        product_ids = [item.product_id for item in request.items]
        products = {
            str(pid): await self._products.get_by_id(pid) for pid in product_ids
        }
        for pid, product in products.items():
            if product is None or not product.is_active:
                raise ProductNotFoundError(UUID(pid))

        # 2. Load inventory (with SELECT FOR UPDATE — row-level lock)
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

        ORDERS_CREATED_TOTAL.inc()
        logger.info(
            "order.created",
            order_id=str(order.id),
            customer_id=str(order.customer_id),
            total_amount=str(order.total_amount),
            item_count=len(order.items),
        )

        result = CreateOrderResult(
            order_id=order.id,
            total_amount=order.total_amount,
            status=order.status.value,
        )

        # 6. Store the idempotency key so future retries get the same response
        if request.idempotency_key and self._idempotency:
            await self._idempotency.save(StoredIdempotencyKey(
                key=request.idempotency_key,
                order_id=order.id,
                response_body=json.dumps({
                    "order_id": str(order.id),
                    "status": order.status.value,
                    "total_amount": str(order.total_amount),
                }),
                status_code=201,
                created_at=order.created_at,
            ))

        return result
