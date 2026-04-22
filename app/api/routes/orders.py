from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_cancel_order_use_case,
    get_create_order_use_case,
    get_get_order_use_case,
)
from app.api.schemas import (
    CreateOrderRequest,
    CreateOrderResponse,
    OrderItemResponse,
    OrderResponse,
)
from app.domain.exceptions import DomainException, InsufficientInventoryError, InvalidOrderTransitionError
from app.use_cases.cancel_order import CancelOrderRequest, CancelOrderUseCase, OrderNotFoundError
from app.use_cases.create_order import (
    CreateOrderUseCase,
    OrderItemRequest,
    ProductNotFoundError,
)
from app.use_cases.create_order import CreateOrderRequest as UseCaseCreateRequest
from app.use_cases.get_order import GetOrderRequest, GetOrderUseCase

router = APIRouter(prefix="/orders", tags=["orders"])


def _build_order_response(order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        customer_id=order.customer_id,
        status=order.status.value,
        total_amount=order.total_amount,
        items=[
            OrderItemResponse(
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=item.unit_price,
                subtotal=item.subtotal,
            )
            for item in order.items
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CreateOrderResponse)
async def create_order(
    body: CreateOrderRequest,
    use_case: Annotated[CreateOrderUseCase, Depends(get_create_order_use_case)],
):
    try:
        result = await use_case.execute(
            UseCaseCreateRequest(
                customer_id=body.customer_id,
                items=[
                    OrderItemRequest(product_id=i.product_id, quantity=i.quantity)
                    for i in body.items
                ],
            )
        )
        return CreateOrderResponse(
            order_id=result.order_id,
            status=result.status,
            total_amount=result.total_amount,
        )
    except ProductNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))
    except InsufficientInventoryError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))
    except DomainException as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    use_case: Annotated[GetOrderUseCase, Depends(get_get_order_use_case)],
):
    try:
        order = await use_case.execute(GetOrderRequest(order_id=order_id))
        return _build_order_response(order)
    except OrderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(
    order_id: UUID,
    cancel_use_case: Annotated[CancelOrderUseCase, Depends(get_cancel_order_use_case)],
    get_use_case: Annotated[GetOrderUseCase, Depends(get_get_order_use_case)],
):
    try:
        await cancel_use_case.execute(CancelOrderRequest(order_id=order_id))
        order = await get_use_case.execute(GetOrderRequest(order_id=order_id))
        return _build_order_response(order)
    except OrderNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidOrderTransitionError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
