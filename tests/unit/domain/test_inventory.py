import pytest
from uuid import uuid4
from app.domain.models import InventoryItem
from app.domain.exceptions import InsufficientInventoryError


def test_available_quantity_is_quantity_minus_reserved():
    item = InventoryItem(product_id=uuid4(), quantity=100, reserved=30)
    assert item.available == 70


def test_reserve_reduces_available():
    item = InventoryItem(product_id=uuid4(), quantity=50, reserved=0)
    item.reserve(10)
    assert item.reserved == 10
    assert item.available == 40


def test_reserve_exact_available_succeeds():
    item = InventoryItem(product_id=uuid4(), quantity=10, reserved=5)
    item.reserve(5)
    assert item.available == 0


def test_reserve_more_than_available_raises():
    item = InventoryItem(product_id=uuid4(), quantity=10, reserved=8)
    with pytest.raises(InsufficientInventoryError) as exc:
        item.reserve(5)
    assert exc.value.requested == 5
    assert exc.value.available == 2


def test_release_increases_available():
    item = InventoryItem(product_id=uuid4(), quantity=50, reserved=20)
    item.release(10)
    assert item.reserved == 10
    assert item.available == 40


def test_release_more_than_reserved_raises():
    item = InventoryItem(product_id=uuid4(), quantity=50, reserved=5)
    with pytest.raises(ValueError):
        item.release(10)


def test_reserve_zero_raises():
    item = InventoryItem(product_id=uuid4(), quantity=50)
    with pytest.raises(ValueError):
        item.reserve(0)