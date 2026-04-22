from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_product_repository
from app.api.schemas import ProductResponse
from app.repositories.product_repository import SqlAlchemyProductRepository

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductResponse])
async def list_products(
    repo: Annotated[SqlAlchemyProductRepository, Depends(get_product_repository)],
):
    products = await repo.list_active()
    return [
        ProductResponse(
            id=p.id,
            name=p.name,
            sku=p.sku,
            price=p.price,
            is_active=p.is_active,
        )
        for p in products
    ]
