"""Zero-trust layer #2: deterministic AST validation of LLM-generated SQL with sqlglot.

The guard never trusts the LLM. It parses the SQL into an AST and rejects anything that is
not a single read-only SELECT over user tables. It also enforces a row LIMIT.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

DIALECT = "postgres"

FORBIDDEN_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})

# Any of these nodes anywhere in the tree (CTEs and subqueries included) is a violation.
_FORBIDDEN_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Drop",
    "Create",
    "Alter",
    "TruncateTable",
    "Merge",
    "Command",  # unparsed statements: GRANT, VACUUM, DO, CALL, ...
    "Grant",
    "Revoke",
    "Copy",
    "Set",
    "Transaction",
    "Commit",
    "Rollback",
    "Into",  # SELECT ... INTO new_table creates a table
    "Lock",  # SELECT ... FOR UPDATE takes row locks
    "Use",
    "Pragma",
)
FORBIDDEN_NODE_TYPES: tuple[type[exp.Expression], ...] = tuple(
    node_type
    for name in _FORBIDDEN_NODE_NAMES
    if isinstance(node_type := getattr(exp, name, None), type) and issubclass(node_type, exp.Expression)
)

# Functions that can sleep, read files, leak settings or touch other sessions.
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "pg_advisory_lock",
        "pg_advisory_xact_lock",
        "lo_import",
        "lo_export",
        "lo_get",
        "lo_open",
        "dblink",
        "dblink_exec",
        "dblink_connect",
        "set_config",
        "current_setting",
        "query_to_xml",
        "query_to_json",
        "txid_current",
        "nextval",
        "setval",
    }
)

_FENCE_RE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.IGNORECASE)


class SecurityViolationError(ValueError):
    """Raised by :func:`enforce` when SQL is rejected."""


@dataclass(frozen=True)
class GuardResult:
    is_valid: bool
    sql: str
    violations: list[str] = field(default_factory=list)
    limit_injected: bool = False
    limit_clamped: bool = False

    @property
    def error_message(self) -> str | None:
        if self.is_valid:
            return None
        return "Security Violation: " + "; ".join(self.violations)


def clean_sql(raw: str) -> str:
    """Remove Markdown fences and surrounding whitespace produced by LLMs."""
    text = raw.strip()
    text = _FENCE_RE.sub("", text).strip()
    return text


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def _collect_violations(root: exp.Expr) -> list[str]:
    violations: list[str] = []
    for node in root.walk():
        if isinstance(node, FORBIDDEN_NODE_TYPES):
            violations.append(f"forbidden construct {type(node).__name__.upper()}")
        elif isinstance(node, exp.Func):
            name = _function_name(node)
            if name in FORBIDDEN_FUNCTIONS:
                violations.append(f"forbidden function {name}()")
        elif isinstance(node, exp.Table):
            schema = (node.db or "").lower()
            table = (node.name or "").lower()
            if schema in FORBIDDEN_SCHEMAS or table in FORBIDDEN_SCHEMAS:
                violations.append(f"system schema access is forbidden: {schema or table}")
            elif table.startswith("pg_"):
                violations.append(f"system table access is forbidden: {table}")
            elif node.catalog:
                violations.append("cross-database references are forbidden")
    # keep order, drop duplicates
    return list(dict.fromkeys(violations))


def _apply_limit(root: exp.Query, max_rows: int) -> tuple[exp.Query, bool, bool]:
    """Inject `LIMIT max_rows` when missing, clamp it when too large."""
    limit_node = root.args.get("limit")
    if root.args.get("fetch") is not None and limit_node is None:
        # FETCH FIRST n ROWS: replace with an explicit LIMIT for uniform handling.
        root.set("fetch", None)
        return root.limit(max_rows), True, False
    if limit_node is None:
        return root.limit(max_rows), True, False

    value = limit_node.expression if isinstance(limit_node, exp.Limit) else None
    if isinstance(value, exp.Literal) and value.is_int:
        if int(value.this) > max_rows:
            return root.limit(max_rows), False, True
        return root, False, False
    # LIMIT ALL / LIMIT (subquery) / parameter: replace with a safe constant.
    return root.limit(max_rows), False, True


def validate_sql(sql: str | None, *, max_rows: int = 100) -> GuardResult:
    """Validate a SQL string and return a normalized, safe version of it."""
    if sql is None or not clean_sql(sql):
        return GuardResult(False, sql or "", ["empty SQL query"])

    text = clean_sql(sql)
    try:
        statements = [stmt for stmt in sqlglot.parse(text, read=DIALECT) if stmt is not None]
    except (ParseError, TokenError) as error:
        first_line = str(error).splitlines()[0] if str(error) else type(error).__name__
        return GuardResult(False, text, [f"SQL syntax error: {first_line}"])

    if not statements:
        return GuardResult(False, text, ["empty SQL query"])
    if len(statements) > 1:
        kinds = ", ".join(type(stmt).__name__.upper() for stmt in statements)
        violations = [f"multiple statements are forbidden ({kinds})"]
        for stmt in statements:
            violations.extend(_collect_violations(stmt))
        return GuardResult(False, text, list(dict.fromkeys(violations)))

    root = statements[0]
    if not isinstance(root, exp.Select | exp.SetOperation):
        return GuardResult(
            False,
            text,
            [f"only SELECT statements are allowed, got {type(root).__name__.upper()}"],
        )

    violations = _collect_violations(root)
    if violations:
        return GuardResult(False, text, violations)

    limited, injected, clamped = _apply_limit(root, max_rows)
    normalized = limited.sql(dialect=DIALECT, pretty=True)
    return GuardResult(True, normalized, [], limit_injected=injected, limit_clamped=clamped)


def enforce(sql: str, *, max_rows: int = 100) -> str:
    """Return safe SQL or raise :class:`SecurityViolationError`."""
    result = validate_sql(sql, max_rows=max_rows)
    if not result.is_valid:
        raise SecurityViolationError(result.error_message)
    return result.sql
