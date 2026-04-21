import pytest
from decimal import Decimal
from uuid import uuid4
from app.domain.models import Order, OrderItem
from app.domain.enums import OrderStatus
from app.domain.exceptions import InvalidOrderTransitionError


def make_order() -> Order:
    return Order(
        customer_id=uuid4(),
        items=[
            OrderItem(product_id=uuid4(), quantity=2, unit_price=Decimal("29.99"))
        ],
    )


def test_order_total_amount():
    order = make_order()
    assert order.total_amount == Decimal("59.98")


def test_order_initial_status_is_pending():
    order = make_order()
    assert order.status == OrderStatus.PENDING


def test_confirm_pending_order():
    order = make_order()
    order.confirm()
    assert order.status == OrderStatus.CONFIRMED


def test_cancel_pending_order():
    order = make_order()
    order.cancel()
    assert order.status == OrderStatus.CANCELLED


def test_cannot_cancel_confirmed_order():
    order = make_order()
    order.confirm()
    with pytest.raises(InvalidOrderTransitionError):
        order.cancel()


def test_cannot_confirm_cancelled_order():
    order = make_order()
    order.cancel()
    with pytest.raises(InvalidOrderTransitionError):
        order.confirm()


def test_cannot_cancel_twice():
    order = make_order()
    order.cancel()
    with pytest.raises(InvalidOrderTransitionError):
        order.cancel()