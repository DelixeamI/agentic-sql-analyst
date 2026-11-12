"""Zero-trust layer #3: execution inside a READ ONLY transaction with a hard timeout."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from agentic_sql_analyst.db.serialization import to_jsonable
from agentic_sql_analyst.schemas import JsonRow

# SQLSTATE classes that mean "infrastructure problem", not "bad SQL":
# 08 connection exception, 28 invalid authorization, 3D invalid catalog, 53 insufficient resources,
# 57P0x admin shutdown / crash.
_INFRA_SQLSTATE_PREFIXES = ("08", "28", "3D", "53", "57P")


class DatabaseUnavailableError(RuntimeError):
    """Infrastructure failure (network, auth, pool). Not something the LLM can repair."""


@dataclass(frozen=True)
class ExecutionResult:
    columns: list[str] = field(default_factory=list)
    rows: list[JsonRow] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class QueryExecutor(Protocol):
    async def execute(self, sql: str) -> ExecutionResult: ...


def _driver_error(error: BaseException) -> Any:
    original: Any = getattr(error, "orig", None) or error
    # SQLAlchemy's asyncpg adapter keeps the real asyncpg exception as __cause__.
    return getattr(original, "__cause__", None) or original


def format_db_error(error: BaseException) -> str:
    """Compact, LLM-friendly diagnostic: `<ErrorClass> [SQLSTATE]: message` + DETAIL/HINT."""
    driver_error = _driver_error(error)
    message = getattr(driver_error, "message", None) or (str(driver_error).splitlines() or [""])[0]
    sqlstate = getattr(driver_error, "sqlstate", None)
    parts = [f"{type(driver_error).__name__}{f' [{sqlstate}]' if sqlstate else ''}: {message}"]
    for attr, label in (("detail", "DETAIL"), ("hint", "HINT")):
        value = getattr(driver_error, attr, None)
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


def is_sql_error(error: DBAPIError) -> bool:
    """True when PostgreSQL rejected the statement itself (the LLM can fix it)."""
    if error.connection_invalidated:
        return False
    sqlstate = getattr(_driver_error(error), "sqlstate", None)
    return isinstance(sqlstate, str) and not sqlstate.startswith(_INFRA_SQLSTATE_PREFIXES)


class PostgresExecutor:
    def __init__(self, engine: AsyncEngine, *, statement_timeout_ms: int, max_rows: int) -> None:
        self._engine = engine
        self._timeout_ms = int(statement_timeout_ms)
        self._max_rows = max_rows

    async def execute(self, sql: str) -> ExecutionResult:
        try:
            async with self._engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    # Must be the first statement of the transaction.
                    await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                    await conn.exec_driver_sql(f"SET LOCAL statement_timeout = {self._timeout_ms}")
                    result = await conn.exec_driver_sql(sql)
                    columns = list(result.keys())
                    raw_rows = result.fetchmany(self._max_rows)
                finally:
                    # Nothing is ever committed: read-only work is always rolled back.
                    await transaction.rollback()
        except DBAPIError as error:
            if is_sql_error(error):
                return ExecutionResult(error=format_db_error(error))
            raise DatabaseUnavailableError(format_db_error(error)) from error
        except (OSError, TimeoutError) as error:
            raise DatabaseUnavailableError(f"{type(error).__name__}: {error}") from error

        rows = [{column: to_jsonable(value) for column, value in zip(columns, row, strict=True)} for row in raw_rows]
        return ExecutionResult(columns=columns, rows=rows)
