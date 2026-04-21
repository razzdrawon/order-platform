"""
Tests for OrderReservationService.

Key scenarios:
- Single item reservation succeeds
- Multi-item reservation succeeds
- Single item with insufficient stock raises and does NOT mutate inventory
- Partial failure (second item fails) rolls back the first item's reservation
- Cancellation releases all reserved inventory
"""
import pytest
from decimal import Decimal
from uuid import uuid4

from app.domain.models import InventoryItem, Order, OrderItem
from app.domain.exceptions import InsufficientInventoryError
from app.domain.services import OrderReservationService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_inventory(product_id, quantity: int, reserved: int = 0) -> InventoryItem:
    return InventoryItem(product_id=product_id, quantity=quantity, reserved=reserved)


def make_order_item(product_id, quantity: int, price: str = "10.00") -> OrderItem:
    return OrderItem(product_id=product_id, quantity=quantity, unit_price=Decimal(price))


# ---------------------------------------------------------------------------
# Reserve — success cases
# ---------------------------------------------------------------------------

def test_reserve_single_item_success():
    product_id = uuid4()
    inv = make_inventory(product_id, quantity=10)
    order = Order(
        customer_id=uuid4(),
        items=[make_order_item(product_id, quantity=3)],
    )

    service = OrderReservationService()
    service.reserve(order, {str(product_id): inv})

    assert inv.reserved == 3
    assert inv.available == 7


def test_reserve_multiple_items_success():
    p1, p2 = uuid4(), uuid4()
    inv1 = make_inventory(p1, quantity=20)
    inv2 = make_inventory(p2, quantity=15)

    order = Order(
        customer_id=uuid4(),
        items=[
            make_order_item(p1, quantity=5),
            make_order_item(p2, quantity=10),
        ],
    )

    service = OrderReservationService()
    service.reserve(order, {str(p1): inv1, str(p2): inv2})

    assert inv1.reserved == 5
    assert inv2.reserved == 10


def test_reserve_exact_available_quantity_succeeds():
    product_id = uuid4()
    inv = make_inventory(product_id, quantity=5, reserved=2)  # available = 3
    order = Order(
        customer_id=uuid4(),
        items=[make_order_item(product_id, quantity=3)],
    )

    service = OrderReservationService()
    service.reserve(order, {str(product_id): inv})

    assert inv.available == 0


# ---------------------------------------------------------------------------
# Reserve — failure cases (the important ones)
# ---------------------------------------------------------------------------

def test_reserve_single_item_insufficient_stock_raises():
    product_id = uuid4()
    inv = make_inventory(product_id, quantity=2)
    order = Order(
        customer_id=uuid4(),
        items=[make_order_item(product_id, quantity=5)],
    )

    service = OrderReservationService()

    with pytest.raises(InsufficientInventoryError):
        service.reserve(order, {str(product_id): inv})

    # Inventory must not have changed
    assert inv.reserved == 0
    assert inv.available == 2


def test_reserve_partial_failure_rolls_back_first_item():
    """
    Critical test: if the second item fails, the first item's reservation
    must be rolled back. Final state = zero reservations on both items.
    """
    p1, p2 = uuid4(), uuid4()
    inv1 = make_inventory(p1, quantity=10)   # plenty of stock
    inv2 = make_inventory(p2, quantity=1)    # only 1 available

    order = Order(
        customer_id=uuid4(),
        items=[
            make_order_item(p1, quantity=5),  # would succeed
            make_order_item(p2, quantity=3),  # will fail
        ],
    )

    service = OrderReservationService()

    with pytest.raises(InsufficientInventoryError) as exc_info:
        service.reserve(order, {str(p1): inv1, str(p2): inv2})

    # Both inventories must be untouched
    assert inv1.reserved == 0, "First item reservation must be rolled back"
    assert inv2.reserved == 0, "Second item was never reserved"

    # Exception must reference the correct product
    assert exc_info.value.product_id == str(p2)


def test_reserve_raises_key_error_for_unknown_product():
    product_id = uuid4()
    order = Order(
        customer_id=uuid4(),
        items=[make_order_item(product_id, quantity=1)],
    )

    service = OrderReservationService()

    with pytest.raises(KeyError):
        service.reserve(order, {})  # empty inventory map


# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------

def test_release_frees_reserved_inventory():
    product_id = uuid4()
    inv = make_inventory(product_id, quantity=10, reserved=5)

    order = Order(
        customer_id=uuid4(),
        items=[make_order_item(product_id, quantity=5)],
    )

    service = OrderReservationService()
    service.release(order, {str(product_id): inv})

    assert inv.reserved == 0
    assert inv.available == 10


def test_release_multiple_items():
    p1, p2 = uuid4(), uuid4()
    inv1 = make_inventory(p1, quantity=20, reserved=8)
    inv2 = make_inventory(p2, quantity=15, reserved=6)

    order = Order(
        customer_id=uuid4(),
        items=[
            make_order_item(p1, quantity=8),
            make_order_item(p2, quantity=6),
        ],
    )

    service = OrderReservationService()
    service.release(order, {str(p1): inv1, str(p2): inv2})

    assert inv1.reserved == 0
    assert inv2.reserved == 0
