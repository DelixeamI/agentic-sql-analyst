.PHONY: help install up down db-up db-down db-reset run ask lint format typecheck test test-unit test-integration check graph

help:  ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install:  ## Install dependencies (uv)
	uv sync

up:  ## Run the full stack (PostgreSQL + API + UI) in Docker -> http://localhost:8000
	docker compose up -d --build --wait

down:  ## Stop the stack
	docker compose down

db-up:  ## Start only PostgreSQL (seeded) on localhost:5433
	docker compose up -d --wait db

db-down:  ## Stop PostgreSQL
	docker compose stop db

db-reset:  ## Drop the DB volume and re-seed from db/init
	docker compose down -v
	docker compose up -d --wait db

run:  ## Run the API locally with autoreload (needs `make db-up`)
	uv run uvicorn agentic_sql_analyst.api.app:app --reload --port 8000

ask:  ## Ask from the CLI: make ask Q="Покажи динамику выручки по месяцам за 2026 год"
	uv run analyst ask "$(Q)"

graph:  ## Print the Mermaid diagram of the agent graph
	uv run analyst graph

lint:  ## Ruff lint
	uv run ruff check src tests

format:  ## Ruff format
	uv run ruff format src tests
	uv run ruff check --fix src tests

typecheck:  ## Mypy strict
	uv run mypy

test:  ## All tests (integration ones auto-skip without Docker)
	uv run pytest

test-unit:  ## Fast tests, no DB
	uv run pytest tests/unit

test-integration:  ## Integration tests against the compose DB (`make db-up` first)
	TEST_DATABASE_URL=postgresql+asyncpg://analyst_ro:analyst_ro_password@localhost:5433/shop uv run pytest tests/integration -v

check: lint typecheck test  ## Everything CI runs
