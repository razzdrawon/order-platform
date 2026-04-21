"""
Tests for CancelOrderUseCase.
"""
import pytest
from decimal import Decimal
from uuid import uuid4

from app.domain.enums import OrderStatus
from app.domain.exceptions import InvalidOrderTransitionError
from app.domain.models import InventoryItem, Order, OrderItem
from app.repositories.base import AbstractInventoryRepository, AbstractOrderRepository
from app.use_cases.cancel_order import (
    CancelOrderRequest,
    CancelOrderUseCase,
    OrderNotFoundError,
)


# ---------------------------------------------------------------------------
# Fakes (minimal — only what cancel needs)
# ---------------------------------------------------------------------------

class FakeOrderRepository(AbstractOrderRepository):
    def __init__(self, orders: list[Order] | None = None):
        self._store = {o.id: o for o in (orders or [])}

    def get_by_id(self, order_id):
        return self._store.get(order_id)

    def save(self, order: Order) -> None:
        self._store[order.id] = order


class FakeInventoryRepository(AbstractInventoryRepository):
    def __init__(self, items: list[InventoryItem] | None = None):
        self._store = {i.product_id: i for i in (items or [])}

    def get_by_product_id(self, product_id):
        return self._store.get(product_id)

    def get_by_product_ids(self, product_ids):
        return {str(pid): self._store[pid] for pid in product_ids if pid in self._store}

    def save(self, item):
        self._store[item.product_id] = item

    def save_many(self, items):
        for item in items:
            self.save(item)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_pending_order(product_id, quantity: int = 3) -> Order:
    return Order(
        customer_id=uuid4(),
        items=[OrderItem(product_id=product_id, quantity=quantity, unit_price=Decimal("10.00"))],
    )


def make_confirmed_order(product_id, quantity: int = 3) -> Order:
    order = make_pending_order(product_id, quantity)
    order.confirm()
    return order


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cancel_pending_order_succeeds():
    product_id = uuid4()
    order = make_pending_order(product_id, quantity=3)
    inv = InventoryItem(product_id=product_id, quantity=10, reserved=3)

    uc = CancelOrderUseCase(
        order_repo=FakeOrderRepository([order]),
        inventory_repo=FakeInventoryRepository([inv]),
    )
    result = uc.execute(CancelOrderRequest(order_id=order.id))

    assert result.status == OrderStatus.CANCELLED.value
    assert inv.reserved == 0
    assert inv.available == 10


def test_cancel_releases_inventory():
    product_id = uuid4()
    order = make_pending_order(product_id, quantity=5)
    inv = InventoryItem(product_id=product_id, quantity=20, reserved=5)

    uc = CancelOrderUseCase(
        order_repo=FakeOrderRepository([order]),
        inventory_repo=FakeInventoryRepository([inv]),
    )
    uc.execute(CancelOrderRequest(order_id=order.id))

    assert inv.reserved == 0
    assert inv.available == 20


def test_cancel_confirmed_order_raises():
    product_id = uuid4()
    order = make_confirmed_order(product_id)
    inv = InventoryItem(product_id=product_id, quantity=10, reserved=3)

    uc = CancelOrderUseCase(
        order_repo=FakeOrderRepository([order]),
        inventory_repo=FakeInventoryRepository([inv]),
    )

    with pytest.raises(InvalidOrderTransitionError):
        uc.execute(CancelOrderRequest(order_id=order.id))

    # Inventory must be untouched
    assert inv.reserved == 3


def test_cancel_nonexistent_order_raises():
    uc = CancelOrderUseCase(
        order_repo=FakeOrderRepository([]),
        inventory_repo=FakeInventoryRepository([]),
    )

    with pytest.raises(OrderNotFoundError):
        uc.execute(CancelOrderRequest(order_id=uuid4()))
