import pytest
from decimal import Decimal
from uuid import uuid4, UUID

from app.domain.enums import OrderStatus
from app.domain.exceptions import InsufficientInventoryError
from app.domain.models import InventoryItem, Order, Product
from app.repositories.base import (
    AbstractInventoryRepository,
    AbstractOrderRepository,
    AbstractProductRepository,
)
from app.use_cases.create_order import (
    CreateOrderRequest,
    CreateOrderUseCase,
    OrderItemRequest,
    ProductNotFoundError,
)


# ---------------------------------------------------------------------------
# In-memory fake repositories (async)
# ---------------------------------------------------------------------------

class FakeProductRepository(AbstractProductRepository):
    def __init__(self, products: list[Product] | None = None):
        self._store: dict[UUID, Product] = {p.id: p for p in (products or [])}

    async def get_by_id(self, product_id: UUID) -> Product | None:
        return self._store.get(product_id)

    async def get_by_sku(self, sku: str) -> Product | None:
        return next((p for p in self._store.values() if p.sku == sku), None)

    async def list_active(self) -> list[Product]:
        return [p for p in self._store.values() if p.is_active]

    async def save(self, product: Product) -> None:
        self._store[product.id] = product


class FakeInventoryRepository(AbstractInventoryRepository):
    def __init__(self, items: list[InventoryItem] | None = None):
        self._store: dict[UUID, InventoryItem] = {
            i.product_id: i for i in (items or [])
        }

    async def get_by_product_id(self, product_id: UUID) -> InventoryItem | None:
        return self._store.get(product_id)

    async def get_by_product_ids(self, product_ids: list[UUID]) -> dict[str, InventoryItem]:
        return {str(pid): self._store[pid] for pid in product_ids if pid in self._store}

    async def save(self, item: InventoryItem) -> None:
        self._store[item.product_id] = item

    async def save_many(self, items: list[InventoryItem]) -> None:
        for item in items:
            await self.save(item)


class FakeOrderRepository(AbstractOrderRepository):
    def __init__(self):
        self._store: dict[UUID, Order] = {}

    async def get_by_id(self, order_id: UUID) -> Order | None:
        return self._store.get(order_id)

    async def save(self, order: Order) -> None:
        self._store[order.id] = order


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def product():
    return Product(name="Widget", sku="WDG-001", price=Decimal("49.99"))

@pytest.fixture
def inventory(product):
    return InventoryItem(product_id=product.id, quantity=20)

@pytest.fixture
def use_case(product, inventory):
    return CreateOrderUseCase(
        product_repo=FakeProductRepository([product]),
        inventory_repo=FakeInventoryRepository([inventory]),
        order_repo=FakeOrderRepository(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_create_order_success(use_case, product):
    request = CreateOrderRequest(
        customer_id=uuid4(),
        items=[OrderItemRequest(product_id=product.id, quantity=3)],
    )
    result = await use_case.execute(request)

    assert result.total_amount == Decimal("149.97")
    assert result.status == OrderStatus.CONFIRMED.value
    assert result.order_id is not None


async def test_create_order_decrements_inventory(use_case, product, inventory):
    request = CreateOrderRequest(
        customer_id=uuid4(),
        items=[OrderItemRequest(product_id=product.id, quantity=5)],
    )
    await use_case.execute(request)

    assert inventory.reserved == 5
    assert inventory.available == 15


async def test_create_order_price_frozen_at_order_time(product, inventory):
    order_repo = FakeOrderRepository()
    uc = CreateOrderUseCase(
        product_repo=FakeProductRepository([product]),
        inventory_repo=FakeInventoryRepository([inventory]),
        order_repo=order_repo,
    )
    request = CreateOrderRequest(
        customer_id=uuid4(),
        items=[OrderItemRequest(product_id=product.id, quantity=2)],
    )
    result = await uc.execute(request)
    original_total = result.total_amount

    product.price = Decimal("999.99")

    saved_order = await order_repo.get_by_id(result.order_id)
    assert saved_order.total_amount == original_total


async def test_create_order_insufficient_stock_raises(use_case, product, inventory):
    request = CreateOrderRequest(
        customer_id=uuid4(),
        items=[OrderItemRequest(product_id=product.id, quantity=999)],
    )
    with pytest.raises(InsufficientInventoryError):
        await use_case.execute(request)

    assert inventory.reserved == 0


async def test_create_order_unknown_product_raises(use_case):
    request = CreateOrderRequest(
        customer_id=uuid4(),
        items=[OrderItemRequest(product_id=uuid4(), quantity=1)],
    )
    with pytest.raises(ProductNotFoundError):
        await use_case.execute(request)


async def test_create_order_inactive_product_raises():
    inactive = Product(name="Old", sku="OLD-001", price=Decimal("10.00"), is_active=False)
    inv = InventoryItem(product_id=inactive.id, quantity=10)
    uc = CreateOrderUseCase(
        product_repo=FakeProductRepository([inactive]),
        inventory_repo=FakeInventoryRepository([inv]),
        order_repo=FakeOrderRepository(),
    )
    request = CreateOrderRequest(
        customer_id=uuid4(),
        items=[OrderItemRequest(product_id=inactive.id, quantity=1)],
    )
    with pytest.raises(ProductNotFoundError):
        await uc.execute(request)


async def test_create_order_empty_items_raises(use_case):
    from app.domain.exceptions import DomainException
    with pytest.raises(DomainException):
        await use_case.execute(CreateOrderRequest(customer_id=uuid4(), items=[]))
