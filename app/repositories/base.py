"""
Abstract repository interfaces.

These define the contract that use cases depend on.
Concrete implementations (SQLAlchemy, in-memory, etc.) live elsewhere.

Rules:
- No framework imports here
- No implementation details
- Use cases import ONLY from this module
"""
from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.models import InventoryItem, Order, Product


class AbstractProductRepository(ABC):

    @abstractmethod
    def get_by_id(self, product_id: UUID) -> Product | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_sku(self, sku: str) -> Product | None:
        raise NotImplementedError

    @abstractmethod
    def list_active(self) -> list[Product]:
        raise NotImplementedError

    @abstractmethod
    def save(self, product: Product) -> None:
        raise NotImplementedError


class AbstractInventoryRepository(ABC):

    @abstractmethod
    def get_by_product_id(self, product_id: UUID) -> InventoryItem | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_product_ids(self, product_ids: list[UUID]) -> dict[str, InventoryItem]:
        """Return inventory keyed by str(product_id) for all given ids."""
        raise NotImplementedError

    @abstractmethod
    def save(self, item: InventoryItem) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_many(self, items: list[InventoryItem]) -> None:
        raise NotImplementedError


class AbstractOrderRepository(ABC):

    @abstractmethod
    def get_by_id(self, order_id: UUID) -> Order | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, order: Order) -> None:
        raise NotImplementedError
