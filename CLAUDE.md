# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Order Orchestration Platform — a production-grade backend that solves overselling, duplicate orders, and inconsistent inventory state under concurrency. Built as a modular monolith with clean architecture, incrementally growing toward distributed systems.

**Current phase:** Phase 1 (MVP) — FastAPI + PostgreSQL, single-service.

**Roadmap phases:** Optimistic locking / idempotency → Celery workers → Observability (structlog + OpenTelemetry) → Kafka + AWS ECS.

## Commands

```bash
# Install dependencies
pip install -e ".[dev]"

# Run the API locally (requires .env with DATABASE_URL)
uvicorn app.main:app --reload

# Run everything via Docker (recommended — starts PostgreSQL + app)
docker-compose up

# Apply migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "description"

# Unit tests only — no DB, runs in ~0.04s
pytest tests/unit/ -v

# Integration tests — requires PostgreSQL
pytest tests/integration/ -v

# All tests with coverage
pytest --cov=app --cov-report=term-missing

# Run a single test file
pytest tests/unit/domain/test_order.py -v

# Run a single test by name
pytest tests/unit/domain/test_order.py::test_name -v
```

Integration tests use `TEST_DATABASE_URL` from `.env`. Copy `.env.example` to `.env` to get started.

## Architecture

Five strict layers — dependencies only flow downward, never up:

```
API (FastAPI routes + Pydantic schemas)
  ↓
Use Cases (application orchestration)
  ↓
Domain (pure Python — zero framework imports, zero DB)
  ↓
Repository interfaces (abstract base classes)
  ↓
Infrastructure (SQLAlchemy ORM models + concrete repos)
```

**Key constraint:** `app/domain/` has no SQLAlchemy, no FastAPI, no I/O. All business rules are testable without a database.

### Layer responsibilities

- **`app/domain/`** — dataclass models (`Product`, `InventoryItem`, `Order`, `OrderItem`), `OrderReservationService` (atomic reserve/rollback logic), domain exceptions, enums.
- **`app/repositories/base.py`** — abstract async interfaces (`AbstractProductRepository`, `AbstractInventoryRepository`, `AbstractOrderRepository`). All methods are `async`.
- **`app/use_cases/`** — one class per operation (`CreateOrderUseCase`, `CancelOrderUseCase`, `GetOrderUseCase`). Each receives repository interfaces via constructor injection; unit tests pass fake in-memory repos.
- **`app/infrastructure/`** — SQLAlchemy ORM models (separate from domain models), concrete repository implementations, async engine + session factory.
- **`app/api/`** — FastAPI routers, Pydantic request/response schemas, `dependencies.py` wires use cases per-request via `Depends`.

### Dependency injection

`app/api/dependencies.py` is the composition root. Each request gets a fresh `AsyncSession` via `get_session()`, and use cases are instantiated with concrete SQLAlchemy repositories passed in. There is no DI container — factories are plain functions used with `fastapi.Depends`.

### Inventory reservation

`OrderReservationService.reserve()` is the critical concurrency path. It loops over order items, reserves each one, and on any failure rolls back all previously reserved items before re-raising. This runs in-memory on domain objects; the caller (use case) is responsible for persisting the updated inventory with `save_many()` after reservation succeeds.

### ORM ↔ Domain mapping

Infrastructure models (`ProductModel`, `OrderModel`, etc.) are distinct from domain dataclasses. Concrete repositories translate between them — ORM models are never exposed above the repository layer.

### Testing strategy

- **Unit tests** (`tests/unit/`) — use fake in-memory repositories that implement the abstract interfaces. No DB, no fixtures needed.
- **Integration tests** (`tests/integration/`) — `conftest.py` creates a real async engine against `TEST_DATABASE_URL`, creates all tables, yields a session, then rolls back after each test to keep tests isolated.

## Commit Rules

Never add `Co-Authored-By` trailers or any Claude/Anthropic attribution to commits. Commits must appear as authored solely by the developer.

## Workflow Rules

**Never commit without explicit instruction.** After completing a feature or phase, stop and tell the developer how to validate the work (commands to run, endpoints to test, expected output). Wait for approval before creating any git commit. The developer reviews code and runs tests before deciding to commit each version.
