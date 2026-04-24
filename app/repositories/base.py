"""
Abstract repository interfaces.

All methods are async — the concrete implementations use SQLAlchemy async sessions.
The fake repositories used in unit tests are also async for consistency.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.models import InventoryItem, Order, Product


@dataclass
class StoredIdempotencyKey:
    """Represents a previously stored idempotency key and its cached response."""
    key: str
    order_id: UUID
    response_body: str   # JSON string — the exact response to replay
    status_code: int
    created_at: datetime


class AbstractProductRepository(ABC):

    @abstractmethod
    async def get_by_id(self, product_id: UUID) -> Product | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_sku(self, sku: str) -> Product | None:
        raise NotImplementedError

    @abstractmethod
    async def list_active(self) -> list[Product]:
        raise NotImplementedError

    @abstractmethod
    async def save(self, product: Product) -> None:
        raise NotImplementedError


class AbstractInventoryRepository(ABC):

    @abstractmethod
    async def get_by_product_id(self, product_id: UUID) -> InventoryItem | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_product_ids(self, product_ids: list[UUID]) -> dict[str, InventoryItem]:
        raise NotImplementedError

    @abstractmethod
    async def save(self, item: InventoryItem) -> None:
        raise NotImplementedError

    @abstractmethod
    async def save_many(self, items: list[InventoryItem]) -> None:
        raise NotImplementedError


class AbstractOrderRepository(ABC):

    @abstractmethod
    async def get_by_id(self, order_id: UUID) -> Order | None:
        raise NotImplementedError

    @abstractmethod
    async def save(self, order: Order) -> None:
        raise NotImplementedError


class AbstractIdempotencyKeyRepository(ABC):

    @abstractmethod
    async def get(self, key: str) -> StoredIdempotencyKey | None:
        raise NotImplementedError

    @abstractmethod
    async def save(self, record: StoredIdempotencyKey) -> None:
        raise NotImplementedError
