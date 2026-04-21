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
| Infrastructure | Docker + AWS ECS *(Phase 5)* |
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

```bash
# Coming in Phase 1 — Iteration 4
uvicorn app.main:app --reload
```

API will be available at `http://localhost:8000`
Interactive docs at `http://localhost:8000/docs`

---

## API Endpoints *(coming soon)*

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/orders` | Create order + reserve inventory |
| `GET` | `/orders/{id}` | Get order by ID |
| `PATCH` | `/orders/{id}/cancel` | Cancel order + release inventory |
| `GET` | `/products` | List active products |

---

## Roadmap

| Phase | Focus | Status |
|---|---|---|
| 1 — MVP | Domain layer, API, PostgreSQL | 🔄 In progress |
| 2 — Concurrency | Optimistic locking, idempotency, SELECT FOR UPDATE | ⏳ Pending |
| 3 — Async | Celery workers, event-driven side effects | ⏳ Pending |
| 4 — Observability | Structured logs, metrics, tracing | ⏳ Pending |
| 5 — Distribution | Kafka, multi-service, AWS deployment | ⏳ Pending |

---

## Current Status

**Phase 1 — Iteration 1 ✅**
- Core domain model implemented
- 14 unit tests, zero external dependencies
- `pytest tests/unit/` → 14 passed in ~0.05s
