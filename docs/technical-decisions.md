# Technical Decisions — Order Orchestration Platform

Key architectural decisions, patterns, and trade-offs behind this project.

---

## 1. "Walk me through the architecture"

This is a **modular monolith with strict layer separation**. The most important rule: dependencies only flow downward — upper layers know about lower layers, never the reverse.

```
API (FastAPI)          <- knows about Use Cases
    |
Use Cases              <- knows about Domain + Repository interfaces
    |
Domain (pure Python)   <- knows nothing external
    |
Repository interfaces  <- abstract contracts
    |
Infrastructure         <- SQLAlchemy, PostgreSQL
```

**Why it matters:**
- The domain is testable without a DB because it has zero external dependencies
- Swap PostgreSQL for MongoDB -> only rewrite Infrastructure
- Swap FastAPI for another framework -> only rewrite the API layer

**Key terms:** Clean Architecture, Separation of Concerns, Modular Monolith.

---

## 2. "Why dataclasses in the domain instead of ORM models directly?"

Because mixing business logic with ORM creates coupling. If `InventoryItem` inherits from SQLAlchemy's `Base`, you can't instantiate it without an open DB session. You need the entire infrastructure running just to test the simplest business rule.

With dataclasses, this test runs in microseconds with no DB:
```python
item = InventoryItem(product_id=uuid4(), quantity=5, reserved=0)
item.reserve(3)
assert item.reserved == 3
```

**Key terms:** Persistence Ignorance, Separation of Concerns.

---

## 3. "What is the Repository Pattern and why do you use it?"

It's an abstraction between business logic and data access. Use cases work against abstract interfaces — they don't know whether data comes from PostgreSQL, Redis, or an in-memory dictionary.

```python
class AbstractInventoryRepository(ABC):
    @abstractmethod
    async def get_by_product_ids(...): ...
    @abstractmethod
    async def save(...): ...
```

Two implementations of the same contract:
- `SqlAlchemyInventoryRepository` — production, uses PostgreSQL
- `FakeInventoryRepository` — unit tests, uses a plain dict

Use cases only see the abstract interface. That's why unit tests need no DB.

**Key term:** Dependency Inversion Principle (the D in SOLID).

---

## 4. "How do you solve the overselling problem?"

**The problem:** without protection, two concurrent requests read the same inventory, both see `available=1`, both reserve, and leave `reserved=2` with `quantity=1`. That's an oversell.

**The solution:** `SELECT FOR UPDATE` on the reservation path.

```python
select(InventoryItemModel)
    .where(InventoryItemModel.product_id.in_(product_ids))
    .with_for_update()   # <- this line is the entire fix
```

PostgreSQL places an exclusive lock on those rows. Any other transaction attempting to read them with `FOR UPDATE` blocks until the first one commits or rolls back.

```
Request A: SELECT ... FOR UPDATE -> acquires lock
Request B: SELECT ... FOR UPDATE -> WAITS
Request A: UPDATE reserved=1, COMMIT -> releases lock
Request B: reads reserved=1, available=0 -> InsufficientInventoryError
```

Concurrency tests use `asyncio.gather()` to fire multiple simultaneous orders against the same product with a single unit in stock, and assert that exactly one succeeds.

**Key terms:** Pessimistic Locking, Row-Level Locking.

---

## 5. "What are Idempotency Keys and when do you need them?"

A system is **idempotent** when executing the same operation N times has the same effect as executing it once.

**The problem without idempotency keys:**
```
Client -> POST /orders -> [timeout / network failure]
Client doesn't know if the order was created
Client retries -> duplicate order created -> charged twice
```

**The solution:**
```
Client sends header: Idempotency-Key: <unique UUID per attempt>

First request  -> executes, stores response tied to that key
Retry          -> finds the key -> returns stored response
                  no inventory touched, no new order created
```

The logic lives in the use case, not in the HTTP route. The API layer only extracts the header and passes it down. This keeps the mechanism testable without HTTP.

**Real-world cases:** Stripe uses exactly this pattern. Mobile apps with unstable connections. Frontend buttons that users can double-click.

**Key terms:** Idempotency, Safe Retries.

---

## 6. "How does dependency injection work in FastAPI?"

`Depends()` is FastAPI's DI system. You declare functions that produce resources and FastAPI runs them automatically before calling your route.

The actual flow of a request:
```python
async def create_order(
    body: CreateOrderRequest,
    use_case: Annotated[CreateOrderUseCase, Depends(get_create_order_use_case)],
):
    ...
# FastAPI runs first:
# 1. get_session() -> opens a DB session
# 2. get_create_order_use_case(session) -> builds use case with repos
# 3. calls create_order with everything resolved
# 4. after return -> get_session() commits or rolls back
```

**Why `yield` in `get_session()`:**
```python
async def get_session():
    async with AsyncSessionFactory() as session:
        try:
            yield session          # FastAPI pauses here, runs the route
            await session.commit() # runs after the route returns
        except Exception:
            await session.rollback()
            raise
```

Code before `yield` = setup. Code after = guaranteed teardown.

**Key terms:** Dependency Injection, Context Manager.

---

## 7. "What is Alembic and how do you use it?"

Alembic is SQLAlchemy's migration system. It's like git for your DB schema — every change is versioned and can be applied or rolled back in order.

**The workflow:**
```bash
# 1. Modify an ORM model in infrastructure/models.py
# 2. Alembic compares your models against the current DB schema
alembic revision --autogenerate -m "add idempotency_keys table"
# 3. Generates a Python file with the schema change as SQL
# 4. Apply the change
alembic upgrade head
```

**Why not just run CREATE TABLE directly?** Because you need to reproduce the exact same schema across local, staging, and production environments — in order, automatically, and reversibly.

**Key terms:** Database Migrations, Schema Version Control.

---

## 8. "How are your tests structured and why?"

Two levels with different purposes:

**Unit tests (`tests/unit/`) — 33 tests, ~40ms:**
- Use in-memory fake repositories that implement the abstract interfaces
- Test domain and use cases in complete isolation
- If a unit test fails, you know exactly which business rule is broken

**Integration tests (`tests/integration/`) — 31 tests, ~2s:**
- Use real PostgreSQL
- Use httpx `AsyncClient` to make actual HTTP requests to the app
- Each test uses a session with rollback at the end -> no state leaks between tests

**Why rollback instead of DELETE?** Faster and safer. PostgreSQL discards all changes in the transaction without needing to clear every table manually.

**Key terms:** Test Pyramid, Test Isolation, Fake vs Mock.

---

## 9. "What is async/await and why do you use it here?"

Python async allows handling many concurrent I/O operations without blocking the thread. While a DB query is executing, instead of the thread sitting idle waiting, it can handle another request.

```
Traditional threading:  Thread A waits for DB    Thread B waits for DB    (N blocked threads)
Async:                  One thread alternates between A and B while they wait for I/O
```

**asyncpg vs psycopg2:**
- `asyncpg` — async driver, used in the app (releases the thread while PostgreSQL processes)
- `psycopg2` — sync driver, used only by Alembic (CLI script, needs no concurrency)

**Key terms:** Async I/O, Event Loop, Non-blocking I/O.

---

## 10. "What would you change to scale to 100k orders per minute?"

The current design has the right foundations. Scaling would require attacking three things:

**1. SELECT FOR UPDATE does not scale well under high concurrency** — many locks means many waits. The alternative is *optimistic locking*: instead of locking on read, you verify on write that nobody modified the data. If someone did, retry. Less contention in most cases.

**2. Processing the order synchronously inside the HTTP request** means the client waits for everything. At scale, the request accepts the order (`202 Accepted`) and a Celery worker processes it in the background. The client gets confirmation via webhook or polling.

**3. A single DB is the eventual bottleneck** — read replicas for query-heavy reads, or splitting the inventory service into its own DB.

**Key terms:** Optimistic Locking, Horizontal Scaling, CQRS, Event-Driven Architecture.

---

## Quick Glossary

| Term | One line |
|---|---|
| **Clean Architecture** | Layered design where the domain has zero external dependencies |
| **Repository Pattern** | Abstraction between business logic and data access |
| **Dependency Injection** | Objects receive their dependencies instead of creating them |
| **Pessimistic Locking** | Lock before reading to prevent concurrent modifications |
| **Optimistic Locking** | Verify on write that nobody modified the data; retry if someone did |
| **Idempotency** | Same operation N times = same result as 1 time |
| **Async I/O** | Release the thread while waiting for DB or network responses |
| **Migration** | Versioned DB schema change, reproducible and reversible |
| **Domain Exception** | Typed error that communicates a violated business rule |
| **Integration test** | Test that verifies multiple layers working together with real dependencies |
| **Unit test** | Test of an isolated unit with no external dependencies |
| **Modular Monolith** | Single deployable with well-separated internal modules |
| **Optimistic Locking** | No lock on read; verify version on write; retry on conflict |
| **Version Column** | Integer incremented on every write; detects concurrent modifications |
| **Task Queue** | Buffer between the app and background workers (Redis + Celery here) |
| **202 Accepted** | HTTP status meaning "received and queued, not yet processed" |
| **Job Polling** | Client repeatedly calls GET /jobs/{id} until status is terminal |
| **Eager Mode** | Celery config that runs tasks inline for testing — no real worker needed |

---

---

## 11. "What is Optimistic Locking and how is it different from SELECT FOR UPDATE?"

Both prevent concurrent writes from corrupting data, but they take opposite approaches to contention.

**Pessimistic locking (SELECT FOR UPDATE):** lock the row before you read it. Other transactions block until you're done. Safe, simple, but creates a queue under high concurrency.

**Optimistic locking:** don't lock at all. Instead, add a `version` column. When you write, assert that the version hasn't changed since you read it:

```sql
UPDATE inventory_items
SET reserved = :new_reserved, version = :version + 1
WHERE product_id = :id AND version = :version_i_read
```

If another transaction already modified the row, `rowcount == 0` — your update was rejected. The use case catches `OptimisticLockError` and retries up to 3 times.

**When to use which:**
- SELECT FOR UPDATE when contention is guaranteed (one item left, many buyers) — pessimistic wins because you know there will be a conflict
- Optimistic locking when conflicts are rare — most transactions succeed on the first try, no blocking

In this system, both coexist: SELECT FOR UPDATE protects the reservation path; optimistic locking acts as a safety net for versioned writes.

**Key terms:** Optimistic Locking, Pessimistic Locking, Version Column, Lost Update Problem.

---

## 12. "Walk me through what happens when a Celery task runs"

When a client hits `POST /orders/async`:

1. FastAPI creates a `Job` row with `status=PENDING` in PostgreSQL
2. Calls `process_order.delay(job_id, customer_id, items)` — this serializes the arguments and pushes a message to the Redis queue
3. Returns `202 Accepted` with the `job_id` immediately — the client doesn't wait

In the worker process:
1. Celery picks up the message from Redis
2. Updates `job.status = PROCESSING`
3. Runs `CreateOrderUseCase` (fully async) inside a `ThreadPoolExecutor` thread with its own event loop
4. On success: updates `job.status = COMPLETED`, stores `order_id`
5. On failure: updates `job.status = FAILED`, stores the error message

The client polls `GET /jobs/{job_id}` to check the result.

**Why a ThreadPoolExecutor?** Celery tasks are synchronous. The use case is `async`. You can't call `asyncio.run()` if an event loop is already running in the thread (which happens in tests). Spawning a fresh thread guarantees a clean event loop every time.

**Key terms:** Message Queue, Producer/Consumer, Task Queue, Event-Driven, 202 Accepted.

---

## 13. "Why does the worker create its own DB session instead of sharing the app's?"

Because the worker runs in a completely separate process (its own Docker container). Processes don't share memory — there is no way to hand a SQLAlchemy session across a process boundary.

The worker creates two independent session factories:
- A **sync session** (psycopg2) for simple job status updates — no async needed for a single UPDATE
- An **async session** (asyncpg) inside `_execute_order()` to run `CreateOrderUseCase`, which is fully async

This separation reflects a real constraint in distributed systems: **each service owns its own DB connection pool.** The Celery worker is effectively a second service that happens to share the same database.

**Key terms:** Process Isolation, Connection Pool, Service Boundaries.

---

## The answer that wins the interview

If asked *"what's the most interesting problem you solved?"*:

> "Overselling under concurrency. Two transactions can read the same available inventory simultaneously, both decide there's enough stock, and both confirm — resulting in more reservations than physical units. I solved it with `SELECT FOR UPDATE` on the reservation path, which tells PostgreSQL to place an exclusive lock on the inventory rows for the duration of the transaction. I added concurrency tests using `asyncio.gather()` that fire multiple simultaneous orders against the same product with a single unit in stock, and assert that exactly one succeeds and the other fails with `InsufficientInventoryError`. The tests prove the correct behavior without any mocks."
