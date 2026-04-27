"""
Kafka event producer.

Design decisions:

1. Graceful degradation — if KAFKA_BOOTSTRAP_SERVERS is empty, publishing
   is a no-op. The app works without Kafka; events are just not emitted.
   This keeps local development simple (no Kafka needed) and lets us add
   Kafka without breaking existing tests.

2. Singleton producer — one AIOKafkaProducer instance shared across all
   requests. Creating a producer per request would be expensive (TCP
   connection + metadata fetch). The producer is initialized on app startup
   via FastAPI's lifespan and closed on shutdown.

3. order_id as partition key — Kafka uses the key to assign a partition.
   All events for the same order land on the same partition, which
   guarantees ordering for that order's events across consumers.

4. Fire-and-forget with acks="all" — we wait for Kafka to acknowledge the
   write before returning. This prevents silent data loss if the broker
   restarts immediately after we publish.

Topics used:
  orders  — all order lifecycle events (created, cancelled)
"""
import structlog
from aiokafka import AIOKafkaProducer

from app.config import settings
from app.events.models import OrderCancelledEvent, OrderCreatedEvent

logger = structlog.get_logger()

# Module-level producer — initialized by lifespan, None when Kafka is disabled
_producer: AIOKafkaProducer | None = None

ORDERS_TOPIC = "orders"


async def start_producer() -> None:
    """Initialize the Kafka producer. Call once on app startup."""
    global _producer
    if not settings.KAFKA_BOOTSTRAP_SERVERS:
        logger.info("kafka.disabled", reason="KAFKA_BOOTSTRAP_SERVERS not set")
        return

    _producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        acks="all",           # Wait for all in-sync replicas to acknowledge
        enable_idempotence=True,  # Exactly-once delivery at the producer level
    )
    await _producer.start()
    logger.info("kafka.producer_started", bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)


async def stop_producer() -> None:
    """Flush and close the Kafka producer. Call once on app shutdown."""
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
        logger.info("kafka.producer_stopped")


async def publish_order_created(event: OrderCreatedEvent) -> None:
    if _producer is None:
        return
    await _producer.send(
        topic=ORDERS_TOPIC,
        key=str(event.order_id).encode("utf-8"),
        value=event.to_json(),
    )
    logger.info("kafka.event_published", event_type=event.event_type, order_id=str(event.order_id))


async def publish_order_cancelled(event: OrderCancelledEvent) -> None:
    if _producer is None:
        return
    await _producer.send(
        topic=ORDERS_TOPIC,
        key=str(event.order_id).encode("utf-8"),
        value=event.to_json(),
    )
    logger.info("kafka.event_published", event_type=event.event_type, order_id=str(event.order_id))
