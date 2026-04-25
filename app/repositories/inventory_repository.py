from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import InventoryItem
from app.domain.exceptions import OptimisticLockError
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
            version=row.version,
        )

    @staticmethod
    def _to_orm(item: InventoryItem) -> InventoryItemModel:
        return InventoryItemModel(
            product_id=item.product_id,
            quantity=item.quantity,
            reserved=item.reserved,
            version=item.version,
        )

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    async def get_by_product_id(
        self, product_id: UUID, for_update: bool = True
    ) -> InventoryItem | None:
        # for_update=True (default): acquires a row-level lock via SELECT FOR UPDATE.
        # Use this on the reservation path to prevent concurrent oversells.
        # for_update=False: plain read with no lock, used when the caller relies
        # on optimistic locking (version check at write time) instead.
        stmt = select(InventoryItemModel).where(
            InventoryItemModel.product_id == product_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_product_ids(self, product_ids: list[UUID]) -> dict[str, InventoryItem]:
        # Lock all rows at once so the entire batch is protected as a unit.
        # Any concurrent transaction trying to reserve the same products will
        # block here until this transaction commits or rolls back.
        result = await self._session.execute(
            select(InventoryItemModel)
            .where(InventoryItemModel.product_id.in_(product_ids))
            .with_for_update()
        )
        return {
            str(row.product_id): self._to_domain(row)
            for row in result.scalars()
        }

    async def save(self, item: InventoryItem) -> None:
        existing = await self._session.get(InventoryItemModel, item.product_id)
        if existing is None:
            self._session.add(self._to_orm(item))
            return

        # Optimistic locking: only update if the version in DB matches the
        # version we read. If another transaction already incremented it,
        # rowcount will be 0 and we raise OptimisticLockError so the caller
        # can retry with fresh data.
        next_version = item.version + 1
        result = await self._session.execute(
            update(InventoryItemModel)
            .where(
                InventoryItemModel.product_id == item.product_id,
                InventoryItemModel.version == item.version,
            )
            .values(
                quantity=item.quantity,
                reserved=item.reserved,
                version=next_version,
            )
        )
        if result.rowcount == 0:
            raise OptimisticLockError(
                f"Inventory for product {item.product_id} was modified by a "
                "concurrent transaction. Retry the operation."
            )

    async def save_many(self, items: list[InventoryItem]) -> None:
        for item in items:
            await self.save(item)
