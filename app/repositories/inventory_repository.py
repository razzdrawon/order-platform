from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import InventoryItem
from app.infrastructure.models import InventoryItemModel
from app.repositories.base import AbstractInventoryRepository


class SqlAlchemyInventoryRepository(AbstractInventoryRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_domain(row: InventoryItemModel) -> InventoryItem:
        return InventoryItem(
            product_id=row.product_id,
            quantity=row.quantity,
            reserved=row.reserved,
        )

    @staticmethod
    def _to_orm(item: InventoryItem) -> InventoryItemModel:
        return InventoryItemModel(
            product_id=item.product_id,
            quantity=item.quantity,
            reserved=item.reserved,
        )

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    async def get_by_product_id(self, product_id: UUID) -> InventoryItem | None:
        row = await self._session.get(InventoryItemModel, product_id)
        return self._to_domain(row) if row else None

    async def get_by_product_ids(self, product_ids: list[UUID]) -> dict[str, InventoryItem]:
        result = await self._session.execute(
            select(InventoryItemModel).where(
                InventoryItemModel.product_id.in_(product_ids)
            )
        )
        return {
            str(row.product_id): self._to_domain(row)
            for row in result.scalars()
        }

    async def save(self, item: InventoryItem) -> None:
        row = await self._session.get(InventoryItemModel, item.product_id)
        if row is None:
            self._session.add(self._to_orm(item))
        else:
            row.quantity = item.quantity
            row.reserved = item.reserved

    async def save_many(self, items: list[InventoryItem]) -> None:
        for item in items:
            await self.save(item)
