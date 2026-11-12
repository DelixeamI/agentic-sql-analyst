# Windows equivalent of the Makefile (no `make` needed).
# Usage: .\tasks.ps1 up | down | db-up | db-reset | run | ask "вопрос" | test | test-integration | check | graph
param(
    [Parameter(Position = 0)][string]$Task = "help",
    [Parameter(Position = 1)][string]$Question = "Покажи динамику выручки по месяцам за 2026 год"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$RoUrl = "postgresql+asyncpg://analyst_ro:analyst_ro_password@localhost:5433/shop"

switch ($Task) {
    "install"          { uv sync }
    "up"               { docker compose up -d --build --wait; Write-Host "Open http://localhost:8000" }
    "down"             { docker compose down }
    "db-up"            { docker compose up -d --wait db }
    "db-reset"         { docker compose down -v; docker compose up -d --wait db }
    "run"              { uv run uvicorn agentic_sql_analyst.api.app:app --reload --port 8000 }
    "ask"              { uv run analyst ask $Question }
    "graph"            { uv run analyst graph }
    "lint"             { uv run ruff check src tests }
    "format"           { uv run ruff format src tests; uv run ruff check --fix src tests }
    "typecheck"        { uv run mypy }
    "test"             { uv run pytest }
    "test-unit"        { uv run pytest tests/unit }
    "test-integration" { $env:TEST_DATABASE_URL = $RoUrl; uv run pytest tests/integration -v; Remove-Item Env:TEST_DATABASE_URL }
    "check"            { uv run ruff check src tests; if ($?) { uv run mypy }; if ($?) { uv run pytest } }
    default {
        Write-Host "Tasks: install, up, down, db-up, db-reset, run, ask `"вопрос`", graph, lint, format, typecheck, test, test-unit, test-integration, check"
    }
}
