from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID, uuid4
from datetime import datetime, timezone

from app.domain.enums import OrderStatus
from app.domain.exceptions import (
    InsufficientInventoryError,
    InvalidOrderTransitionError,
    EmptyOrderError,
)


@dataclass
class Product:
    name: str
    sku: str
    price: Decimal
    id: UUID = field(default_factory=uuid4)
    is_active: bool = True


@dataclass
class InventoryItem:
    product_id: UUID
    quantity: int
    reserved: int = 0
    version: int = 0  # Incremented on every write — used for optimistic locking

    @property
    def available(self) -> int:
        return self.quantity - self.reserved

    def reserve(self, amount: int) -> None:
        if amount <= 0:
            raise ValueError("Reserve amount must be positive")
        if amount > self.available:
            raise InsufficientInventoryError(
                str(self.product_id), amount, self.available
            )
        self.reserved += amount

    def release(self, amount: int) -> None:
        if amount <= 0:
            raise ValueError("Release amount must be positive")
        if amount > self.reserved:
            raise ValueError("Cannot release more than reserved")
        self.reserved -= amount


@dataclass
class OrderItem:
    product_id: UUID
    quantity: int
    unit_price: Decimal

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass
class Order:
    customer_id: UUID
    items: list[OrderItem] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_amount(self) -> Decimal:
        return sum(item.subtotal for item in self.items)

    def confirm(self) -> None:
        if self.status != OrderStatus.PENDING:
            raise InvalidOrderTransitionError(
                f"Cannot confirm order in status {self.status}"
            )
        self.status = OrderStatus.CONFIRMED
        self.updated_at = datetime.now(timezone.utc)

    def cancel(self) -> None:
        if self.status == OrderStatus.CONFIRMED:
            raise InvalidOrderTransitionError("Cannot cancel a confirmed order")
        if self.status == OrderStatus.CANCELLED:
            raise InvalidOrderTransitionError("Order is already cancelled")
        self.status = OrderStatus.CANCELLED
        self.updated_at = datetime.now(timezone.utc)