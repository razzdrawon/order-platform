from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Product
from app.infrastructure.models import ProductModel
from app.repositories.base import AbstractProductRepository


class SqlAlchemyProductRepository(AbstractProductRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_domain(row: ProductModel) -> Product:
        return Product(
            id=row.id,
            name=row.name,
            sku=row.sku,
            price=row.price,
            is_active=row.is_active,
        )

    @staticmethod
    def _to_orm(product: Product) -> ProductModel:
        return ProductModel(
            id=product.id,
            name=product.name,
            sku=product.sku,
            price=product.price,
            is_active=product.is_active,
        )

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    async def get_by_id(self, product_id: UUID) -> Product | None:
        row = await self._session.get(ProductModel, product_id)
        return self._to_domain(row) if row else None

    async def get_by_sku(self, sku: str) -> Product | None:
        result = await self._session.execute(
            select(ProductModel).where(ProductModel.sku == sku)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_active(self) -> list[Product]:
        result = await self._session.execute(
            select(ProductModel).where(ProductModel.is_active.is_(True))
        )
        return [self._to_domain(row) for row in result.scalars()]

    async def save(self, product: Product) -> None:
        row = await self._session.get(ProductModel, product.id)
        if row is None:
            self._session.add(self._to_orm(product))
        else:
            row.name = product.name
            row.sku = product.sku
            row.price = product.price
            row.is_active = product.is_active
