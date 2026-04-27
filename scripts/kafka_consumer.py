"""
Demo Kafka consumer — prints all events from the orders topic.

This script simulates a downstream service (email service, analytics,
inventory replenishment) listening for order events.

Usage:
    python scripts/kafka_consumer.py

Requires Kafka running on localhost:9092.
Stop with Ctrl+C.
"""
import asyncio
import json

from aiokafka import AIOKafkaConsumer


async def consume():
    consumer = AIOKafkaConsumer(
        "orders",
        bootstrap_servers="localhost:9092",
        group_id="demo-consumer",
        auto_offset_reset="earliest",  # Read from the beginning on first run
    )
    await consumer.start()
    print("Listening for events on topic: orders\n")

    try:
        async for message in consumer:
            event = json.loads(message.value.decode("utf-8"))
            print(f"[partition={message.partition} offset={message.offset}]")
            print(f"  event_type : {event.get('event_type')}")
            print(f"  order_id   : {event.get('order_id')}")
            print(f"  occurred_at: {event.get('occurred_at')}")
            if event.get("event_type") == "order.created":
                print(f"  customer_id: {event.get('customer_id')}")
                print(f"  total_amount: {event.get('total_amount')}")
            print()
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(consume())
