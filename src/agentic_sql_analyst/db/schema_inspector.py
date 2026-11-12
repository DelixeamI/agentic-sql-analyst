"""Builds a compact DDL description of the database for the LLM prompts.

Uses pg_catalog directly: information_schema hides constraints from a SELECT-only role.
These are trusted, hard-coded queries; LLM-generated SQL can never touch system catalogs
(see the AST guard).
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_COLUMNS_SQL = text(
    """
    SELECT c.relname AS table_name,
           obj_description(c.oid, 'pg_class') AS table_comment,
           c.reltuples::bigint AS approx_rows,
           a.attname AS column_name,
           format_type(a.atttypid, a.atttypmod) AS data_type,
           a.attnotnull AS not_null,
           col_description(c.oid, a.attnum) AS column_comment
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'v', 'm', 'p')
      AND has_table_privilege(c.oid, 'SELECT')
    ORDER BY c.relname, a.attnum
    """
)

_CONSTRAINTS_SQL = text(
    """
    SELECT cl.relname AS table_name, con.contype AS kind, pg_get_constraintdef(con.oid) AS definition
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace
    WHERE n.nspname = 'public' AND con.contype IN ('p', 'f', 'u', 'c')
    ORDER BY cl.relname, con.contype DESC, con.conname
    """
)

_SMALL_TABLE_ROWS = 50
_TEXT_TYPES = ("text", "character varying", "varchar", "character")


class SchemaProvider(Protocol):
    async def get_ddl(self) -> str: ...


@dataclass
class _Column:
    name: str
    data_type: str
    not_null: bool
    comment: str | None


@dataclass
class _Table:
    name: str
    comment: str | None
    approx_rows: int
    columns: list[_Column] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    samples: dict[str, list[str]] = field(default_factory=dict)


def _quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def render_ddl(tables: list[_Table]) -> str:
    blocks: list[str] = []
    for table in tables:
        lines: list[str] = []
        if table.comment:
            lines.append(f"-- {table.comment}")
        lines.append(f"CREATE TABLE {table.name} (")
        entries: list[tuple[str, str]] = []  # (definition, trailing comment)
        for column in table.columns:
            definition = f"    {column.name} {column.data_type}{' NOT NULL' if column.not_null else ''}"
            notes = [column.comment] if column.comment else []
            if column.name in table.samples:
                notes.append("значения: " + ", ".join(repr(v) for v in table.samples[column.name]))
            entries.append((definition, "; ".join(notes)))
        entries.extend((f"    {constraint}", "") for constraint in table.constraints)
        for index, (definition, note) in enumerate(entries):
            comma = "," if index < len(entries) - 1 else ""
            lines.append(f"{definition}{comma}" + (f"  -- {note}" if note else ""))
        lines.append(");")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


class PostgresSchemaInspector:
    """Reads schema metadata and caches the rendered DDL for `ttl_s` seconds."""

    def __init__(self, engine: AsyncEngine, *, ttl_s: int = 300) -> None:
        self._engine = engine
        self._ttl_s = ttl_s
        self._cached: str | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    async def get_ddl(self) -> str:
        async with self._lock:
            now = time.monotonic()
            if self._cached is None or now - self._cached_at > self._ttl_s:
                self._cached = await self._load()
                self._cached_at = now
            return self._cached

    async def _load(self) -> str:
        tables: dict[str, _Table] = {}
        async with self._engine.connect() as conn:
            for row in (await conn.execute(_COLUMNS_SQL)).mappings():
                table = tables.setdefault(
                    row["table_name"],
                    _Table(row["table_name"], row["table_comment"], int(row["approx_rows"] or 0)),
                )
                table.columns.append(
                    _Column(row["column_name"], row["data_type"], row["not_null"], row["column_comment"])
                )

            constraints: dict[str, list[str]] = defaultdict(list)
            for row in (await conn.execute(_CONSTRAINTS_SQL)).mappings():
                constraints[row["table_name"]].append(row["definition"])
            for name, definitions in constraints.items():
                if name in tables:
                    tables[name].constraints = definitions

            # Real values of text columns in small dictionary tables help the LLM write filters.
            for table in tables.values():
                if not 0 < table.approx_rows <= _SMALL_TABLE_ROWS:
                    continue
                for column in table.columns:
                    if column.data_type.startswith(_TEXT_TYPES):
                        result = await conn.execute(
                            text(
                                f"SELECT DISTINCT {_quote_ident(column.name)} AS v "  # noqa: S608 - trusted catalog identifiers
                                f"FROM {_quote_ident(table.name)} WHERE {_quote_ident(column.name)} IS NOT NULL "
                                "ORDER BY 1 LIMIT 30"
                            )
                        )
                        table.samples[column.name] = [str(v) for v in result.scalars()]
            await conn.rollback()
        return render_ddl(list(tables.values()))
