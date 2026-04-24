from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.models import IdempotencyKeyModel
from app.repositories.base import AbstractIdempotencyKeyRepository, StoredIdempotencyKey


class SqlAlchemyIdempotencyKeyRepository(AbstractIdempotencyKeyRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> StoredIdempotencyKey | None:
        result = await self._session.execute(
            select(IdempotencyKeyModel).where(IdempotencyKeyModel.key == key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return StoredIdempotencyKey(
            key=row.key,
            order_id=row.order_id,
            response_body=row.response_body,
            status_code=row.status_code,
            created_at=row.created_at,
        )

    async def save(self, record: StoredIdempotencyKey) -> None:
        self._session.add(IdempotencyKeyModel(
            key=record.key,
            order_id=record.order_id,
            response_body=record.response_body,
            status_code=record.status_code,
        ))
