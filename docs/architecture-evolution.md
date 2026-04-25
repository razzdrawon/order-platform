# Architecture Evolution — Order Orchestration Platform

This document captures the system's architecture at each phase as a snapshot. The goal is to show how real production systems grow incrementally — each phase adds a layer of reliability, not a rewrite from scratch.

---

## Phase 1 — MVP: Core Domain + REST API

**Problem being solved:** build a correct order system where inventory can never go negative, even under basic usage.

### What was built

- Domain layer: `Product`, `InventoryItem`, `Order`, `OrderItem` as pure Python dataclasses
- `OrderReservationService`: atomic multi-item reservation with rollback on partial failure
- Repository pattern: abstract interfaces tested with in-memory fakes; SQLAlchemy concrete implementations
- Use cases: `CreateOrderUseCase`, `CancelOrderUseCase`, `GetOrderUseCase`
- FastAPI routes: `POST /orders`, `GET /orders/{id}`, `PATCH /orders/{id}/cancel`, `GET /products`
- PostgreSQL + Alembic migrations
- Docker Compose with a single `db` service

### Request flow (Phase 1)

```
Client
  |
  | POST /orders
  ▼
FastAPI Route
  | Depends(get_create_order_use_case)
  ▼
CreateOrderUseCase.execute()
  ├── ProductRepository.get_by_ids()         → SELECT products
  ├── InventoryRepository.get_by_product_ids() → SELECT inventory
  ├── OrderReservationService.reserve()      → in-memory logic
  ├── InventoryRepository.save_many()        → UPDATE inventory
  └── OrderRepository.save()                → INSERT order
  |
  ▼
201 Created { order_id, status, total_amount, ... }
```

### Infrastructure (Phase 1)

```
┌────────────────────────────┐
│  Docker Compose            │
│                            │
│  ┌──────────┐              │
│  │ app:8000 │              │
│  └────┬─────┘              │
│       │                    │
│  ┌────▼─────┐              │
│  │ db:5432  │ PostgreSQL   │
│  └──────────┘              │
└────────────────────────────┘
```

### What it does NOT handle yet

- Two simultaneous requests for the same last item → both can oversell
- A client retrying after a timeout → duplicate order created
- Long-running order processing blocking the HTTP response

---

## Phase 2 — Concurrency & Reliability

**Problem being solved:** the system must behave correctly when multiple requests hit it at the exact same time.

### What was added

#### SELECT FOR UPDATE (Pessimistic Locking)
Inventory rows are locked at read time inside the reservation transaction. A second transaction trying to read the same rows blocks until the first commits or rolls back.

```python
select(InventoryItemModel)
    .where(InventoryItemModel.product_id.in_(product_ids))
    .with_for_update()   # exclusive row lock
```

```
Request A: SELECT inventory FOR UPDATE  → acquires lock on row
Request B: SELECT inventory FOR UPDATE  → WAITS
Request A: reserved=1, COMMIT           → releases lock
Request B: reads reserved=1, available=0 → InsufficientInventoryError ✓
```

#### Optimistic Locking (version column)
`InventoryItem` gains a `version: int` column. Every `UPDATE` includes `WHERE version = N` and increments the version. If another transaction already modified the row, `rowcount == 0` → `OptimisticLockError` → use case retries up to 3 times.

```sql
UPDATE inventory_items
SET reserved = :reserved, version = :new_version
WHERE product_id = :id AND version = :expected_version
```

This is the fallback for high-throughput scenarios where pessimistic locking creates too much contention.

#### Idempotency Keys
The client sends a `Idempotency-Key: <uuid>` header. On first request, the result is stored in the `idempotency_keys` table. On retry with the same key, the stored response is returned immediately — no inventory is touched, no duplicate order is created.

```
First request  → execute → store { key, order_id, response_body }
Retry          → find key → return stored response (no DB writes)
```

### New tables (Phase 2)

```sql
idempotency_keys (
    key          VARCHAR(255) PRIMARY KEY,
    order_id     UUID,
    response_body TEXT,
    status_code  INTEGER,
    created_at   TIMESTAMP
)

-- InventoryItem gains:
version INTEGER NOT NULL DEFAULT 0
```

### Request flow (Phase 2)

```
Client
  |
  | POST /orders
  | Header: Idempotency-Key: <uuid>
  ▼
FastAPI Route
  ▼
CreateOrderUseCase.execute()
  ├── [Step 0] IdempotencyRepo.get(key)     → already seen? return cached
  ├── ProductRepository.get_by_ids()
  ├── InventoryRepository.get_by_product_ids(for_update=True)  ← SELECT FOR UPDATE
  ├── OrderReservationService.reserve()
  ├── InventoryRepository.save_many()       ← versioned UPDATE, OptimisticLockError possible
  ├── OrderRepository.save()
  └── [Step 6] IdempotencyRepo.save(key, result)
  |
  ▼
201 Created (or replayed cached response)
```

### What it does NOT handle yet

- Heavy workloads where the HTTP response must be immediate regardless of processing time
- Side effects (emails, analytics, webhooks) that should not block the main transaction

---

## Phase 3 — Async Processing

**Problem being solved:** some order flows are slow or unreliable. The client should not wait for the entire processing chain to complete.

### What was added

#### Celery + Redis task queue
A `POST /orders/async` endpoint accepts the order, creates a `Job` record, dispatches a Celery task, and returns `202 Accepted` immediately. The client polls `GET /jobs/{job_id}` for the result.

```
Client          FastAPI App         Redis Queue       Celery Worker
  |                  |                   |                  |
  | POST /orders/async                   |                  |
  |─────────────────►|                   |                  |
  |                  | INSERT job(PENDING)|                 |
  |                  | process_order.delay()               |
  |                  |──────────────────►|                  |
  | 202 { job_id }   |                   |                  |
  |◄─────────────────|                   | task received    |
  |                  |                   |─────────────────►|
  |                  |                   |                  | UPDATE job(PROCESSING)
  |                  |                   |                  | CreateOrderUseCase.execute()
  |                  |                   |                  | UPDATE job(COMPLETED, order_id)
  |                  |                   |                  |
  | GET /jobs/{id}   |                   |                  |
  |─────────────────►|                   |                  |
  | 200 { COMPLETED, order_id }          |                  |
  |◄─────────────────|                   |                  |
```

#### Job lifecycle

```
PENDING → PROCESSING → COMPLETED
                    ↘ FAILED (stores error message)
```

#### New table (Phase 3)

```sql
jobs (
    id         UUID PRIMARY KEY,
    status     VARCHAR(20),   -- PENDING | PROCESSING | COMPLETED | FAILED
    order_id   UUID NULLABLE,
    error      TEXT NULLABLE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)
```

#### Worker architecture

The Celery worker runs in a separate process (separate Docker container in production). It cannot reuse the app's async SQLAlchemy session. Instead, it creates its own:

- A **sync session** (psycopg2) to update the `Job` record (status updates are simple, no async needed)
- An **async session** (asyncpg) inside a `ThreadPoolExecutor` thread to run `CreateOrderUseCase` (which is fully async)

The `ThreadPoolExecutor` is necessary because the worker thread already has no event loop, but in tests with `CELERY_TASK_ALWAYS_EAGER=True` the task runs inside pytest's event loop — spawning a fresh thread gives the coroutine a clean event loop to run in.

### Infrastructure (Phase 3)

```
┌──────────────────────────────────────────────┐
│  Docker Compose                              │
│                                              │
│  ┌──────────┐     ┌───────────┐             │
│  │ app:8000 │     │  worker   │             │
│  └────┬─────┘     └─────┬─────┘             │
│       │                 │                   │
│  ┌────▼─────┐     ┌─────▼─────┐            │
│  │ db:5432  │     │redis:6379 │             │
│  └──────────┘     └───────────┘             │
│       ▲                 │                   │
│       └─────────────────┘                   │
│         (worker also writes to db)           │
└──────────────────────────────────────────────┘
```

### Testing Celery without a real worker

Tests set `CELERY_TASK_ALWAYS_EAGER=True`, which makes Celery execute tasks inline (synchronously) in the same process. `CELERY_TASK_EAGER_PROPAGATES=False` mirrors production behavior — a failing task marks the job FAILED without raising an exception to the route.

The test fixture also overrides `settings.DATABASE_URL → TEST_DATABASE_URL` before the task runs, so the worker's sync and async sessions both hit the test database.

### What it does NOT handle yet

- No webhooks or push notifications when a job completes — client must poll
- No retry strategy for transient failures (DB timeouts, momentary unavailability)
- No dead letter queue for permanently failed tasks
- Side effects (emails, events) are not yet modeled as separate tasks

---

## Phases Ahead

| Phase | Focus | Key additions |
|---|---|---|
| **4 — Observability** | Understand what's happening in production | structlog structured logging, Prometheus metrics, OpenTelemetry tracing, correlation IDs |
| **5 — Distribution** | Split into independent services | Kafka for inter-service events, separate Inventory Service, AWS ECS deployment, CI/CD |

---

## What stays constant across all phases

These decisions were made in Phase 1 and are never revisited — they hold at every scale:

- **Domain layer has zero framework imports** — testable in isolation, swappable infrastructure
- **Repository pattern** — use cases are independent of the DB driver or cloud provider
- **Use case per operation** — each business operation is one class with one responsibility
- **Typed domain exceptions** — `InsufficientInventoryError`, `OptimisticLockError` communicate exactly what went wrong
- **Unit tests with fake repos** — run in ~40ms, never need a database
