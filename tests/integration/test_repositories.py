"""
Integration tests for SQLAlchemy repositories.

These tests hit a real PostgreSQL database. Each test gets a fresh session
that is rolled back at the end — no state leaks between tests.

Run with: pytest tests/integration/ -v
Requires: PostgreSQL running via docker compose up -d
"""
import pytest
from decimal import Decimal
from uuid import uuid4

from app.domain.models import InventoryItem, Order, OrderItem, Product
from app.repositories.inventory_repository import SqlAlchemyInventoryRepository
from app.repositories.order_repository import SqlAlchemyOrderRepository
from app.repositories.product_repository import SqlAlchemyProductRepository


# ---------------------------------------------------------------------------
# Product repository
# ---------------------------------------------------------------------------

async def test_save_and_get_product(session):
    repo = SqlAlchemyProductRepository(session)
    product = Product(name="Test Widget", sku="TW-001", price=Decimal("29.99"))

    await repo.save(product)
    await session.flush()  # write to DB within the transaction

    fetched = await repo.get_by_id(product.id)

    assert fetched is not None
    assert fetched.id == product.id
    assert fetched.name == "Test Widget"
    assert fetched.sku == "TW-001"
    assert fetched.price == Decimal("29.99")
    assert fetched.is_active is True


async def test_get_product_by_sku(session):
    repo = SqlAlchemyProductRepository(session)
    product = Product(name="Gadget", sku="GDG-002", price=Decimal("99.99"))
    await repo.save(product)
    await session.flush()

    fetched = await repo.get_by_sku("GDG-002")

    assert fetched is not None
    assert fetched.id == product.id


async def test_get_nonexistent_product_returns_none(session):
    repo = SqlAlchemyProductRepository(session)
    result = await repo.get_by_id(uuid4())
    assert result is None


async def test_list_active_products(session):
    repo = SqlAlchemyProductRepository(session)
    active = Product(name="Active", sku="ACT-001", price=Decimal("10.00"), is_active=True)
    inactive = Product(name="Inactive", sku="INA-001", price=Decimal("5.00"), is_active=False)
    await repo.save(active)
    await repo.save(inactive)
    await session.flush()

    results = await repo.list_active()

    active_skus = [p.sku for p in results]
    assert "ACT-001" in active_skus
    assert "INA-001" not in active_skus


async def test_update_existing_product(session):
    repo = SqlAlchemyProductRepository(session)
    product = Product(name="Old Name", sku="UPD-001", price=Decimal("10.00"))
    await repo.save(product)
    await session.flush()

    product.name = "New Name"
    product.price = Decimal("20.00")
    await repo.save(product)
    await session.flush()

    fetched = await repo.get_by_id(product.id)
    assert fetched.name == "New Name"
    assert fetched.price == Decimal("20.00")


# ---------------------------------------------------------------------------
# Inventory repository
# ---------------------------------------------------------------------------

async def test_save_and_get_inventory(session):
    # Need a product first (FK constraint)
    product_repo = SqlAlchemyProductRepository(session)
    product = Product(name="Inventory Product", sku="INV-001", price=Decimal("15.00"))
    await product_repo.save(product)
    await session.flush()

    inv_repo = SqlAlchemyInventoryRepository(session)
    item = InventoryItem(product_id=product.id, quantity=100, reserved=10)
    await inv_repo.save(item)
    await session.flush()

    fetched = await inv_repo.get_by_product_id(product.id)

    assert fetched is not None
    assert fetched.product_id == product.id
    assert fetched.quantity == 100
    assert fetched.reserved == 10
    assert fetched.available == 90


async def test_get_inventory_by_product_ids(session):
    product_repo = SqlAlchemyProductRepository(session)
    inv_repo = SqlAlchemyInventoryRepository(session)

    p1 = Product(name="P1", sku="P1-001", price=Decimal("10.00"))
    p2 = Product(name="P2", sku="P2-001", price=Decimal("20.00"))
    await product_repo.save(p1)
    await product_repo.save(p2)
    await session.flush()

    await inv_repo.save(InventoryItem(product_id=p1.id, quantity=50))
    await inv_repo.save(InventoryItem(product_id=p2.id, quantity=30))
    await session.flush()

    result = await inv_repo.get_by_product_ids([p1.id, p2.id])

    assert str(p1.id) in result
    assert str(p2.id) in result
    assert result[str(p1.id)].quantity == 50
    assert result[str(p2.id)].quantity == 30


async def test_update_inventory_reserved(session):
    product_repo = SqlAlchemyProductRepository(session)
    inv_repo = SqlAlchemyInventoryRepository(session)

    product = Product(name="Reserved Product", sku="RSV-001", price=Decimal("10.00"))
    await product_repo.save(product)
    await session.flush()

    item = InventoryItem(product_id=product.id, quantity=20, reserved=0)
    await inv_repo.save(item)
    await session.flush()

    item.reserve(5)
    await inv_repo.save(item)
    await session.flush()

    fetched = await inv_repo.get_by_product_id(product.id)
    assert fetched.reserved == 5
    assert fetched.available == 15


# ---------------------------------------------------------------------------
# Order repository
# ---------------------------------------------------------------------------

async def test_save_and_get_order(session):
    product_repo = SqlAlchemyProductRepository(session)
    order_repo = SqlAlchemyOrderRepository(session)

    product = Product(name="Order Product", sku="ORD-001", price=Decimal("49.99"))
    await product_repo.save(product)
    await session.flush()

    order = Order(
        customer_id=uuid4(),
        items=[OrderItem(product_id=product.id, quantity=2, unit_price=Decimal("49.99"))],
    )
    await order_repo.save(order)
    await session.flush()

    fetched = await order_repo.get_by_id(order.id)

    assert fetched is not None
    assert fetched.id == order.id
    assert fetched.customer_id == order.customer_id
    assert len(fetched.items) == 1
    assert fetched.items[0].quantity == 2
    assert fetched.items[0].unit_price == Decimal("49.99")
    assert fetched.total_amount == Decimal("99.98")


async def test_get_nonexistent_order_returns_none(session):
    repo = SqlAlchemyOrderRepository(session)
    result = await repo.get_by_id(uuid4())
    assert result is None


async def test_update_order_status(session):
    product_repo = SqlAlchemyProductRepository(session)
    order_repo = SqlAlchemyOrderRepository(session)

    product = Product(name="Status Product", sku="STS-001", price=Decimal("10.00"))
    await product_repo.save(product)
    await session.flush()

    order = Order(
        customer_id=uuid4(),
        items=[OrderItem(product_id=product.id, quantity=1, unit_price=Decimal("10.00"))],
    )
    await order_repo.save(order)
    await session.flush()

    order.confirm()
    await order_repo.save(order)
    await session.flush()

    fetched = await order_repo.get_by_id(order.id)
    from app.domain.enums import OrderStatus
    assert fetched.status == OrderStatus.CONFIRMED


async def test_order_items_loaded_correctly(session):
    product_repo = SqlAlchemyProductRepository(session)
    order_repo = SqlAlchemyOrderRepository(session)

    p1 = Product(name="Item A", sku="ITA-001", price=Decimal("10.00"))
    p2 = Product(name="Item B", sku="ITB-001", price=Decimal("25.00"))
    await product_repo.save(p1)
    await product_repo.save(p2)
    await session.flush()

    order = Order(
        customer_id=uuid4(),
        items=[
            OrderItem(product_id=p1.id, quantity=3, unit_price=Decimal("10.00")),
            OrderItem(product_id=p2.id, quantity=1, unit_price=Decimal("25.00")),
        ],
    )
    await order_repo.save(order)
    await session.flush()

    fetched = await order_repo.get_by_id(order.id)

    assert len(fetched.items) == 2
    assert fetched.total_amount == Decimal("55.00")
