"""Execution accuracy: compare the result set of predicted SQL with the result set of gold SQL.

Rules (close to the Spider / BIRD "EX" metric, made explicit):
* only values are compared, column names and column order are ignored;
* the prediction may return extra columns, every gold column must be matched by a distinct one;
* row count must be equal; row order matters only when the gold item is `ordered`;
* numbers are equal within `max(0.051, 1e-4 * |gold|)` (ROUND(x, 1) vs raw value is still equal);
* ISO dates and timestamps are compared by their date part (`2025-12-01T00:00:00+00:00` == `2025-12-01`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agentic_sql_analyst.schemas import JsonRow

_ISO_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})([T ][\d:.]+([+-]\d{2}(:?\d{2})?|Z)?)?$")

Value = float | str | bool | None


@dataclass(frozen=True)
class MatchResult:
    correct: bool
    reason: str


def normalize(value: Any) -> Value:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    text = str(value).strip()
    date = _ISO_DATE_RE.match(text)
    if date:
        return date.group(1)
    return text


def values_equal(gold: Value, pred: Value) -> bool:
    if isinstance(gold, float) and isinstance(pred, float):
        return abs(gold - pred) <= max(0.051, 1e-4 * abs(gold))
    return gold == pred


def _sort_key(value: Value) -> tuple[int, Any]:
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, value)
    if isinstance(value, float):
        return (2, value)
    return (3, value)


def _vectors_equal(gold: Sequence[Value], pred: Sequence[Value]) -> bool:
    return len(gold) == len(pred) and all(values_equal(g, p) for g, p in zip(gold, pred, strict=True))


def _columns(columns: Sequence[str], rows: Sequence[JsonRow]) -> list[list[Value]]:
    return [[normalize(row.get(column)) for row in rows] for column in columns]


def _rows_equal_unordered(gold_rows: list[tuple[Value, ...]], pred_rows: list[tuple[Value, ...]]) -> bool:
    def key(row: tuple[Value, ...]) -> tuple[tuple[int, Any], ...]:
        return tuple(_sort_key(v) for v in row)

    return all(
        _vectors_equal(g, p) for g, p in zip(sorted(gold_rows, key=key), sorted(pred_rows, key=key), strict=True)
    )


def compare_results(
    gold_columns: Sequence[str],
    gold_rows: Sequence[JsonRow],
    pred_columns: Sequence[str],
    pred_rows: Sequence[JsonRow],
    *,
    ordered: bool = False,
) -> MatchResult:
    if len(gold_rows) != len(pred_rows):
        return MatchResult(False, f"row count {len(pred_rows)} != gold {len(gold_rows)}")
    if not gold_rows:
        return MatchResult(True, "both empty")

    gold = _columns(gold_columns, gold_rows)
    pred = _columns(pred_columns, pred_rows)

    def same(g: list[Value], p: list[Value]) -> bool:
        if ordered:
            return _vectors_equal(g, p)
        return _vectors_equal(sorted(g, key=_sort_key), sorted(p, key=_sort_key))

    candidates = [[k for k, p in enumerate(pred) if same(g, p)] for g in gold]
    missing = [gold_columns[j] for j, options in enumerate(candidates) if not options]
    if missing:
        return MatchResult(False, f"no predicted column matches gold column(s): {', '.join(missing)}")

    gold_tuples = list(zip(*gold, strict=True))

    def search(j: int, used: tuple[int, ...]) -> bool:
        if j == len(gold):
            pred_tuples = list(zip(*(pred[k] for k in used), strict=True))
            if ordered:
                return all(_vectors_equal(g, p) for g, p in zip(gold_tuples, pred_tuples, strict=True))
            return _rows_equal_unordered(gold_tuples, pred_tuples)
        return any(search(j + 1, (*used, k)) for k in candidates[j] if k not in used)

    if search(0, ()):
        return MatchResult(True, "result sets match")
    return MatchResult(False, "columns match individually but rows are misaligned or out of order")
