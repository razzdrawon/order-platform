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

---

## Phase 4 — Observability

**Problem being solved:** in production you cannot attach a debugger. When something breaks at 3am, you need to reconstruct exactly what happened from logs and metrics alone.

### What was added

#### Structured logging with structlog

Every log line is a JSON object with consistent fields. Free-form text like `"Order created abc-123"` becomes:

```json
{"timestamp": "...", "level": "info", "event": "order.created", "request_id": "xyz", "order_id": "abc-123", "customer_id": "...", "total_amount": "29.99"}
```

Every field is queryable in Datadog, CloudWatch, or any log aggregator.

#### request_id — the correlation thread

A UUID is generated per request in `RequestContextMiddleware` and bound to `structlog.contextvars`. Every log call within that request automatically includes `request_id` — no manual passing required.

```
http.request_received   request_id=127c80a2   ← middleware
order.created           request_id=127c80a2   ← use case, 3 layers down
http.request_completed  request_id=127c80a2   ← middleware again
```

In production with thousands of concurrent requests, filtering by `request_id` gives you the complete trace of one specific request with zero noise.

The `X-Request-ID` header lets API gateways or clients inject their own correlation ID, enabling cross-service tracing before OpenTelemetry is wired up.

#### Prometheus metrics — `GET /metrics`

The app exposes metrics in the Prometheus text format. A Prometheus server scrapes this endpoint every 15 seconds and stores the time series.

**HTTP metrics (automatic via middleware):**
- `http_requests_total` — counter by method, route template, status code
- `http_request_duration_seconds` — histogram by method and route template

**Business metrics (manual instrumentation):**
- `orders_created_total` — incremented in `CreateOrderUseCase`
- `orders_cancelled_total` — incremented in `CancelOrderUseCase`
- `inventory_errors_total` — labeled by `error_type` (insufficient_inventory, optimistic_lock)
- `jobs_completed_total` / `jobs_failed_total` — incremented in the Celery worker

Route templates (`/orders/{order_id}`) are used as labels instead of raw paths to avoid cardinality explosion from UUIDs.

#### Dependency-aware health check — `GET /health`

```json
{
  "status": "healthy",
  "checks": {
    "database": {"status": "ok", "latency_ms": 2.1},
    "redis":    {"status": "ok", "latency_ms": 0.4}
  }
}
```

Returns `200` when all dependencies are reachable, `503` when any fails. Load balancers and Kubernetes use the status code to decide whether to route traffic to this instance.

### New files (Phase 4)

```
app/logging_config.py              — structlog configuration (JSON vs console)
app/middleware/request_context.py  — generates request_id, logs request/response
app/middleware/metrics.py          — records HTTP metrics per request
app/metrics.py                     — Prometheus metric definitions
app/api/routes/health.py           — /health with active DB + Redis checks
```

### Infrastructure (Phase 4) — unchanged

No new services. Observability is entirely within the app process. A real Prometheus + Grafana stack would be added as separate containers in Phase 5.

### What it does NOT handle yet

- No distributed tracing (OpenTelemetry) — request_id correlation is manual
- No Grafana dashboards — metrics are exposed but not visualized
- No alerting rules — Prometheus has the data but no alerts configured
- No log aggregation service — logs go to stdout, need a collector (Datadog agent, FluentBit) to ship them

---

## Phases Ahead

| Phase | Focus | Key additions |
|---|---|---|
| **5 — Distribution** | Split into independent services | Kafka for inter-service events, separate Inventory Service, AWS ECS deployment, CI/CD |

---

## What stays constant across all phases

These decisions were made in Phase 1 and are never revisited — they hold at every scale:

- **Domain layer has zero framework imports** — testable in isolation, swappable infrastructure
- **Repository pattern** — use cases are independent of the DB driver or cloud provider
- **Use case per operation** — each business operation is one class with one responsibility
- **Typed domain exceptions** — `InsufficientInventoryError`, `OptimisticLockError` communicate exactly what went wrong
- **Unit tests with fake repos** — run in ~40ms, never need a database
