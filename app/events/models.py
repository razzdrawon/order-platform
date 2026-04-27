"""
Domain event definitions.

Events are plain dataclasses — no framework imports, no DB, no I/O.
They represent facts that have already happened in the domain:
  "An order was created"  →  OrderCreatedEvent
  "An order was cancelled"  →  OrderCancelledEvent

Events are serialized to JSON before being published to Kafka.
Each event carries an event_type field so consumers can route them
without inspecting the topic name alone.
"""
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID


@dataclass
class OrderCreatedEvent:
    order_id: UUID
    customer_id: UUID
    total_amount: Decimal
    item_count: int
    occurred_at: datetime

    event_type: str = "order.created"
    version: int = 1  # Schema version — increment when the shape changes

    def to_json(self) -> bytes:
        data = asdict(self)
        # Convert non-serializable types to strings
        data["order_id"] = str(self.order_id)
        data["customer_id"] = str(self.customer_id)
        data["total_amount"] = str(self.total_amount)
        data["occurred_at"] = self.occurred_at.isoformat()
        return json.dumps(data).encode("utf-8")


@dataclass
class OrderCancelledEvent:
    order_id: UUID
    occurred_at: datetime

    event_type: str = "order.cancelled"
    version: int = 1

    def to_json(self) -> bytes:
        data = asdict(self)
        data["order_id"] = str(self.order_id)
        data["occurred_at"] = self.occurred_at.isoformat()
        return json.dumps(data).encode("utf-8")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
