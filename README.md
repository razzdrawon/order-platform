# Order Orchestration Platform

A production-grade backend system that solves real-world e-commerce problems: **overselling, duplicate orders, and inconsistent inventory state under high concurrency.**

Built incrementally following clean architecture principles — modular monolith first, distributed systems later.

---

## The Problem

In high-traffic e-commerce systems, three things go wrong constantly:

- **Overselling** — two users buy the last item simultaneously
- **Duplicate orders** — a user double-clicks and gets charged twice
- **Inconsistent state** — order is created but inventory is never decremented

This system solves all three with atomic reservation, idempotency, and strict domain invariants.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | FastAPI |
| Database | PostgreSQL + SQLAlchemy (async) |
| Migrations | Alembic |
| Cache / Locks | Redis *(Phase 2)* |
| Async Jobs | Celery *(Phase 3)* |
| Observability | structlog + OpenTelemetry *(Phase 4)* |
| Infrastructure | Docker + AWS ECS + Terraform *(Phase 5)* |
| Testing | pytest + pytest-asyncio |
| Language | Python 3.11 |

---

## Architecture

Modular monolith with strict layer separation:

```
┌─────────────────────────────────────┐
│           API Layer (FastAPI)        │  ← HTTP in/out, Pydantic schemas
├─────────────────────────────────────┤
│         Use Cases (Application)      │  ← Orchestrates domain + repos
├─────────────────────────────────────┤
│           Domain Layer               │  ← Business rules, pure Python
├─────────────────────────────────────┤
│        Repository Interfaces         │  ← Abstractions, no SQL here
├─────────────────────────────────────┤
│      Infrastructure (SQLAlchemy)     │  ← DB models, concrete repos
└─────────────────────────────────────┘
```

**Key rule:** the domain layer has zero framework imports. Business logic is testable without a database.

---

## Domain Model

```
Product           InventoryItem              Order
───────           ─────────────              ─────
id: UUID          product_id → Product       id: UUID
name: str         quantity: int              customer_id: UUID
sku: str (unique) reserved: int              status: PENDING | CONFIRMED | CANCELLED
price: Decimal    available = qty - reserved items: List[OrderItem]
is_active: bool                              total_amount: Decimal (computed)

                                             OrderItem
                                             ─────────
                                             product_id → Product
                                             quantity: int
                                             unit_price: Decimal (frozen at order time)
```

**Business rules:**
- `available = quantity - reserved` — never goes negative
- All items in an order are reserved atomically — partial failure rolls back everything
- Cancelling an order releases reserved inventory
- Confirmed orders cannot be cancelled
- Unit price is captured at order time — product price changes don't affect existing orders

---

## Project Structure

```
order-platform/
├── app/
│   ├── domain/          # Pure Python — zero framework imports
│   │   ├── enums.py
│   │   ├── exceptions.py
│   │   ├── models.py
│   │   └── services.py
│   ├── repositories/    # Abstract interfaces
│   ├── use_cases/       # Application logic
│   ├── api/             # FastAPI routes and schemas
│   └── infrastructure/  # SQLAlchemy ORM models + concrete repos
└── tests/
    ├── unit/            # No DB required — runs in milliseconds
    └── integration/     # Requires PostgreSQL
```

---

## Setup

**Requirements:** Python 3.11+, PostgreSQL (for integration tests)

```bash
# Clone the repo
git clone git@github.com:razzdrawon/order-platform.git
cd order-platform

# Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

# Install dependencies
pip install -e ".[dev]"
```

---

## Running Tests

```bash
# Unit tests only — no DB needed, runs in < 1 second
pytest tests/unit/ -v

# Integration tests — requires PostgreSQL running
pytest tests/integration/ -v

# All tests with coverage report
pytest --cov=app --cov-report=term-missing
```

---

## Running the API

**Option 1: Docker Compose (recommended)**
```bash
docker-compose up
```

**Option 2: Manual (local development)**
```bash
uvicorn app.main:app --reload
```

API will be available at `http://localhost:8000`
Interactive docs at `http://localhost:8000/docs`

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/orders` | Create order synchronously (201 with order) |
| `POST` | `/orders/async` | Submit order for async processing (202 with job_id) |
| `GET` | `/jobs/{job_id}` | Poll async job status |
| `GET` | `/orders/{id}` | Get order by ID |
| `PATCH` | `/orders/{id}/cancel` | Cancel order + release inventory |
| `GET` | `/products` | List active products |
| `GET` | `/health` | Dependency-aware health check (DB + Redis) |
| `GET` | `/metrics` | Prometheus metrics endpoint |

The `POST /orders` endpoint accepts an optional `Idempotency-Key` header. Retrying with the same key returns the cached response without creating a duplicate order.

---

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 1 — MVP | Domain layer, API, PostgreSQL | ✅ Complete |
| 2 — Concurrency | Optimistic locking, idempotency, SELECT FOR UPDATE | ✅ Complete |
| 3 — Async | Celery + Redis, background jobs, job polling | ✅ Complete |
| 4 — Observability | Structured logs, Prometheus metrics, health check | ✅ Complete |
| 5 — Distribution | GitFlow, CI/CD, AWS ECS + RDS + ElastiCache, Terraform | ✅ Complete |

---

## Current Status

**Phase 1 — Iteration 1 ✅**
- Core domain model: `Product`, `InventoryItem`, `OrderItem`, `Order`
- Full order lifecycle: `PENDING → CONFIRMED / CANCELLED`
- 14 unit tests, zero external dependencies

**Phase 1 — Iteration 2 ✅**
- `OrderReservationService`: atomic multi-item reservation with rollback on partial failure
- Repository interfaces: abstract contracts for `Product`, `Inventory`, `Order`
- Use cases: `CreateOrder`, `CancelOrder`, `GetOrder`
- 19 additional unit tests using in-memory fake repositories
- `pytest tests/unit/` → 33 passed in ~0.04s, zero DB required

**Phase 1 — Iteration 3 ✅**
- `app/config.py` with pydantic-settings reading from `.env`
- SQLAlchemy async engine, session factory, and ORM models
- Alembic configured with autogenerate — initial migration creates all 4 tables
- Concrete SQLAlchemy repositories: `Product`, `Inventory`, `Order`
- All use cases and repository interfaces refactored to async
- Docker Compose with PostgreSQL 16 for local development
- 12 integration tests against real PostgreSQL
- `pytest tests/` → 45 passed (33 unit + 12 integration) in ~0.9s

**Phase 1 — Iteration 4 ✅**
- FastAPI routes: `POST /orders`, `GET /orders/{id}`, `PATCH /orders/{id}/cancel`, `GET /products`
- API integration tests with real DB + HTTP client
- Exception handling: 422 for validation errors, 404 for not found, 409 for invalid state transitions
- 10 API integration tests
- `pytest tests/` → 55 passed in ~1.0s

**Phase 1 — Iteration 5 ✅**
- Dockerfile for containerized app deployment
- docker-compose.yml with app + PostgreSQL
- Environment configuration via `.env`
- Full end-to-end testing in Docker

**Phase 2 — Iteration 1 ✅**
- `SELECT FOR UPDATE` on inventory rows during reservation — prevents overselling under concurrency
- Concurrency tests using `asyncio.gather()` — proves correct behavior with simultaneous requests

**Phase 2 — Iteration 2 ✅**
- Idempotency keys: `Idempotency-Key` header, stored in `idempotency_keys` table, replay on retry
- Prevents duplicate orders on client retries

**Phase 2 — Iteration 3 ✅**
- Optimistic locking: `version` column on `inventory_items`, versioned UPDATE, `OptimisticLockError` + retry
- `pytest tests/` → 55+ passed

**Phase 3 — Iteration 1 ✅**
- `POST /orders/async` → 202 Accepted with `job_id` (non-blocking)
- Celery worker processes order in background: PENDING → PROCESSING → COMPLETED / FAILED
- `GET /jobs/{job_id}` for polling
- Redis as message broker; worker runs in separate Docker container
- Integration tests with `CELERY_TASK_ALWAYS_EAGER=True` — no real worker needed in CI
- `pytest tests/` → 92% coverage

**Phase 4 — Iteration 1 ✅**
- Structured logging with structlog — JSON in production, colored console in dev
- `request_id` generated per request in middleware, flows through entire call chain via `contextvars`

**Phase 4 — Iteration 2 ✅**
- Prometheus metrics: `GET /metrics` with HTTP counters, latency histograms, and business counters

**Phase 4 — Iteration 3 ✅**
- `GET /health` verifies DB and Redis actively — returns 200/503 for load balancer integration
- `pytest tests/` → 73 passed, 92% coverage

**Phase 5 — Iteration 1 ✅**
- GitFlow branching strategy: `develop` → `release/*` → `master`
- `ci.yml`: runs pytest on every push, blocks PRs if coverage < 80%
- `release.yml`: auto-creates git tag + GitHub Release + back-merges master → develop on release PR merge
- `deploy.yml`: builds `linux/amd64` Docker image, pushes to ECR, updates ECS task definitions, waits for stability

**Phase 5 — Iteration 2 ✅**
- AWS infrastructure via Terraform: VPC, ECR, ECS Fargate (app + worker), RDS PostgreSQL 16, ElastiCache Redis 7, ALB, CloudWatch Logs, IAM roles
- Remote Terraform state in S3
- `/health` extended with `version` and `commit` fields — deployment verification on every release
- App live on ALB, logs centralized in CloudWatch
