# Validation Guide — Order Orchestration Platform

How to run and validate the system at each phase. Each section is self-contained — you can pick up from any phase without reading the others.

---

## Prerequisites

```bash
# Clone and set up the virtual environment
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Copy environment config
cp .env.example .env
```

---

## Phase 1 — MVP

### What to validate
- Domain logic runs correctly in isolation (no DB)
- Orders can be created, retrieved, and cancelled via HTTP
- Insufficient stock returns an error — no partial state

### Run unit tests (no DB required)

```bash
pytest tests/unit/ -v
```

Expected: **33 passed** in ~0.04s

### Run everything via Docker

```bash
docker-compose up
```

Wait until you see `Application startup complete` in the app logs.

### Seed a product (required before placing orders)

```bash
# Connect to the DB and insert a product + inventory
docker-compose exec db psql -U order_user -d order_platform -c "
INSERT INTO products (id, name, sku, price, is_active)
VALUES (
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  'Test Product', 'SKU-001', 29.99, true
);
INSERT INTO inventory_items (product_id, quantity, reserved, version)
VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 10, 0, 0);
"
```

### Verify endpoints

```bash
# Health check
curl -s http://localhost:8000/health | python3 -m json.tool

# List products
curl -s http://localhost:8000/products | python3 -m json.tool

# Create an order
curl -s -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "00000000-0000-0000-0000-000000000001",
    "items": [{"product_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "quantity": 2}]
  }' | python3 -m json.tool
# Expected: 201 with order_id, status: PENDING, total_amount: 59.98

# Get the order (replace <order_id>)
curl -s http://localhost:8000/orders/<order_id> | python3 -m json.tool

# Cancel the order
curl -s -X PATCH http://localhost:8000/orders/<order_id>/cancel | python3 -m json.tool
# Expected: 200 with status: CANCELLED

# Insufficient stock — should fail cleanly
curl -s -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "00000000-0000-0000-0000-000000000001",
    "items": [{"product_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "quantity": 999}]
  }' | python3 -m json.tool
# Expected: 422 with error about insufficient inventory
```

### Run integration tests

```bash
pytest tests/integration/ -v
```

Expected: all integration tests pass (requires PostgreSQL running via Docker or locally).

---

## Phase 2 — Concurrency & Reliability

### What to validate
- Two simultaneous requests for the same last unit → exactly one succeeds
- Retrying with the same `Idempotency-Key` → same order returned, no duplicate
- Optimistic lock conflict → use case retries and succeeds (or fails cleanly)

### Run all tests

```bash
pytest tests/ -v
```

Key test files:
- `tests/integration/test_concurrency.py` — fires simultaneous orders with `asyncio.gather()`
- `tests/integration/test_optimistic_locking.py` — version increments, stale write raises error
- `tests/integration/test_idempotency.py` — same key returns same order

### Validate idempotency manually

```bash
# First request — creates the order
curl -s -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: my-unique-key-001" \
  -d '{
    "customer_id": "00000000-0000-0000-0000-000000000001",
    "items": [{"product_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "quantity": 1}]
  }' | python3 -m json.tool
# Expected: 201 with a new order_id

# Retry with same key — must return the exact same order_id
curl -s -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: my-unique-key-001" \
  -d '{
    "customer_id": "00000000-0000-0000-0000-000000000001",
    "items": [{"product_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "quantity": 1}]
  }' | python3 -m json.tool
# Expected: same order_id as the first response
# Inventory was NOT decremented a second time
```

### Verify inventory was only decremented once

```bash
docker-compose exec db psql -U order_user -d order_platform -c "
SELECT product_id, quantity, reserved FROM inventory_items;
"
# reserved should be 1, not 2
```

---

## Phase 3 — Async Processing

### What to validate
- `POST /orders/async` returns 202 immediately (does not wait for processing)
- Celery worker picks up the task and processes it in the background
- `GET /jobs/{job_id}` eventually shows COMPLETED with an order_id
- Invalid product or insufficient stock → job shows FAILED with error message

### Start all services (includes Redis + worker)

```bash
docker-compose up
```

Wait for all four services to be healthy:
- `order_platform_db` — PostgreSQL ready
- `order_platform_redis` — Redis ready
- `order_platform_app` — FastAPI started
- `order_platform_worker` — `celery@... ready.`

### Submit an async order

```bash
# Step 1: get a valid product_id
curl -s http://localhost:8000/products | python3 -m json.tool
# Copy a product id from the response

# Step 2: submit the async order
curl -s -X POST http://localhost:8000/orders/async \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "00000000-0000-0000-0000-000000000001",
    "items": [{"product_id": "<product_id>", "quantity": 1}]
  }' | python3 -m json.tool
# Expected: 202 { "job_id": "...", "status": "PENDING" }

# Step 3: poll for the result (replace <job_id>)
curl -s http://localhost:8000/jobs/<job_id> | python3 -m json.tool
# Expected: { "status": "COMPLETED", "order_id": "...", "error": null }
```

### Verify the worker processed the task

In the docker-compose logs you should see:

```
order_platform_worker | Task app.worker.tasks.process_order[<id>] received
order_platform_worker | Task app.worker.tasks.process_order[<id>] succeeded in 0.09s: None
```

### Test failure cases

```bash
# Invalid product → job should be FAILED
curl -s -X POST http://localhost:8000/orders/async \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "00000000-0000-0000-0000-000000000001",
    "items": [{"product_id": "00000000-0000-0000-0000-000000000099", "quantity": 1}]
  }' | python3 -m json.tool

# Then poll the job_id — expected: { "status": "FAILED", "error": "..." }
```

### Run async integration tests (no real worker needed)

```bash
pytest tests/integration/test_async_orders.py -v
```

These tests use `CELERY_TASK_ALWAYS_EAGER=True` — tasks run inline, no Redis or worker process required.

### Run full test suite with coverage

```bash
pytest --cov=app --cov-report=term-missing
```

Expected: **~92% coverage**, all tests pass.

---

## Running tests inside Docker (alternative)

If you don't have PostgreSQL installed locally, run all tests inside the app container:

```bash
docker-compose exec app pytest tests/ -v
```

---

## Quick reference — useful commands

```bash
# Check running containers
docker-compose ps

# View worker logs
docker-compose logs worker -f

# View app logs
docker-compose logs app -f

# Connect to the database
docker-compose exec db psql -U order_user -d order_platform

# Apply pending migrations
docker-compose exec app alembic upgrade head

# Force clean rebuild (after adding new dependencies)
docker-compose down
docker-compose build --no-cache
docker-compose up

# Stop all containers
docker-compose down

# Stop and delete volumes (resets the database)
docker-compose down -v
```
