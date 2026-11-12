"""Zero-trust SQL sandbox: AST-level security checks."""

from __future__ import annotations

import pytest

from agentic_sql_analyst.sandbox import SecurityViolationError, enforce, validate_sql
from agentic_sql_analyst.sandbox.ast_guard import clean_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT o.id FROM orders o",
        "SELECT o.id FROM orders o;",
        "WITH t AS (SELECT o.id FROM orders o) SELECT t.id FROM t",
        "SELECT o.id FROM orders o UNION ALL SELECT oi.order_id FROM order_items oi",
        "SELECT DATE_TRUNC('month', o.created_at) AS m, COUNT(*) FROM orders o GROUP BY 1",
        "SELECT c.name FROM categories c WHERE c.name LIKE '%бук%'",
        "SELECT o.id, SUM(oi.quantity) OVER (PARTITION BY o.id) FROM orders o JOIN order_items oi ON oi.order_id = o.id"
        " WHERE o.id > 0",
        "SELECT 100.0 * a / NULLIF(b, 0) FROM (SELECT 1 AS a, 2 AS b) s",
        "select o.id from orders o -- trailing comment ; drop table x",
    ],
)
def test_safe_selects_are_accepted(sql: str) -> None:
    result = validate_sql(sql)
    assert result.is_valid, result.violations


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("DELETE FROM orders", "only SELECT"),
        ("UPDATE orders SET status = 'x'", "only SELECT"),
        ("INSERT INTO orders (id) VALUES (1)", "only SELECT"),
        ("DROP TABLE orders", "only SELECT"),
        ("TRUNCATE orders", "only SELECT"),
        ("ALTER TABLE orders ADD COLUMN x int", "only SELECT"),
        ("GRANT ALL ON orders TO public", "only SELECT"),
        ("COPY orders TO '/tmp/orders.csv'", "only SELECT"),
        ("SELECT 1; DROP TABLE orders", "multiple statements"),
        ("SELECT COUNT(*) FROM orders; DELETE FROM orders;", "multiple statements"),
        ("SELECT * INTO backup_orders FROM orders", "INTO"),
        ("SELECT o.id FROM orders o FOR UPDATE", "LOCK"),
        ("WITH d AS (DELETE FROM orders RETURNING id) SELECT id FROM d", "DELETE"),
        ("SELECT * FROM pg_catalog.pg_tables", "system schema"),
        ("SELECT * FROM information_schema.columns", "system schema"),
        ("SELECT usename FROM pg_user", "system table"),
        ("SELECT pg_sleep(10)", "pg_sleep"),
        ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
        ("SELECT current_setting('data_directory')", "current_setting"),
        ("SELECT * FROM otherdb.public.orders", "cross-database"),
        ("SELEC id FROM orders", "SQL syntax error"),
        ("", "empty SQL"),
    ],
)
def test_dangerous_sql_is_rejected(sql: str, expected: str) -> None:
    result = validate_sql(sql)
    assert not result.is_valid
    assert expected.lower() in (result.error_message or "").lower()


def test_limit_is_injected_when_missing() -> None:
    result = validate_sql("SELECT o.id FROM orders o", max_rows=100)
    assert result.is_valid
    assert result.limit_injected
    assert "LIMIT 100" in result.sql


def test_small_limit_is_preserved() -> None:
    result = validate_sql("SELECT o.id FROM orders o ORDER BY o.id LIMIT 3")
    assert result.is_valid
    assert not result.limit_injected
    assert not result.limit_clamped
    assert "LIMIT 3" in result.sql


def test_huge_limit_is_clamped() -> None:
    result = validate_sql("SELECT o.id FROM orders o LIMIT 1000000", max_rows=100)
    assert result.limit_clamped
    assert "LIMIT 100" in result.sql
    assert "1000000" not in result.sql


def test_limit_applies_to_union_as_a_whole() -> None:
    result = validate_sql("SELECT 1 AS x UNION SELECT 2 AS x")
    assert result.is_valid
    assert result.sql.rstrip().endswith("LIMIT 100")


def test_markdown_fences_are_stripped() -> None:
    assert clean_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert validate_sql("```sql\nSELECT o.id FROM orders o\n```").is_valid


def test_none_is_rejected() -> None:
    assert not validate_sql(None).is_valid


def test_enforce_raises_on_violation() -> None:
    with pytest.raises(SecurityViolationError, match="Security Violation"):
        enforce("DROP TABLE orders")
    assert "LIMIT" in enforce("SELECT o.id FROM orders o")
