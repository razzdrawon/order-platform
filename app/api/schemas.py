from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

class ProductResponse(BaseModel):
    id: UUID
    name: str
    sku: str
    price: Decimal
    is_active: bool


# ---------------------------------------------------------------------------
# Orders — Request
# ---------------------------------------------------------------------------

class OrderItemRequest(BaseModel):
    product_id: UUID
    quantity: int

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("quantity must be greater than 0")
        return v


class CreateOrderRequest(BaseModel):
    customer_id: UUID
    items: list[OrderItemRequest]

    @field_validator("items")
    @classmethod
    def items_must_not_be_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("order must contain at least one item")
        return v


# ---------------------------------------------------------------------------
# Orders — Response
# ---------------------------------------------------------------------------

class OrderItemResponse(BaseModel):
    product_id: UUID
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class OrderResponse(BaseModel):
    id: UUID
    customer_id: UUID
    status: str
    total_amount: Decimal
    items: list[OrderItemResponse]
    created_at: datetime
    updated_at: datetime


class CreateOrderResponse(BaseModel):
    order_id: UUID
    status: str
    total_amount: Decimal


# ---------------------------------------------------------------------------
# Jobs — Async order processing
# ---------------------------------------------------------------------------

class AcceptedResponse(BaseModel):
    """Returned immediately when POST /orders enqueues an async job (202)."""
    job_id: UUID
    status: str = "PENDING"
    message: str = "Order accepted for processing. Poll /jobs/{job_id} for status."


class JobStatusResponse(BaseModel):
    """Current state of an async order processing job."""
    job_id: UUID
    status: str          # PENDING | PROCESSING | COMPLETED | FAILED
    order_id: UUID | None = None   # Set once the job completes successfully
    error: str | None = None       # Set if the job fails
    created_at: datetime
    updated_at: datetime
