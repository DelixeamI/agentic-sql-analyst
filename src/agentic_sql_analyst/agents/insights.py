"""Deterministic data profiling, chart selection and narrative fallback.

Used in two places:
* as a safety net when the LLM synthesizer fails or returns an invalid Vega-Lite spec;
* as the synthesizer of the offline demo LLM.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agentic_sql_analyst.schemas import JsonRow, SynthesisOutput

VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}.*)?$")
_TEMPORAL_NAMES = ("month", "date", "day", "week", "year", "period", "quarter", "dt", "created_at")
_SHARE_WORDS = ("дол", "структур", "распредел", "share", "процент")
# Priority of value columns, from most to least specific.
_VALUE_PRIORITY: tuple[tuple[str, ...], ...] = (
    ("change", "growth", "diff", "delta", "margin", "share", "pct", "percent"),
    ("revenue", "sales", "total", "sum", "amount", "spent", "gmv"),
    ("avg", "mean", "check", "median"),
    ("count", "qty", "quantity", "number"),
)
_HUMAN_NAMES = {
    "revenue": "выручка",
    "total_revenue": "выручка",
    "total_sales": "выручка",
    "total_spent": "сумма покупок",
    "orders_count": "количество заказов",
    "customers_count": "количество клиентов",
    "avg_check": "средний чек",
    "change_pct": "изменение, %",
    "share_pct": "доля, %",
    "margin_pct": "маржинальность, %",
    "q1_revenue": "выручка Q1",
    "q2_revenue": "выручка Q2",
}


@dataclass(frozen=True)
class DataProfile:
    numeric: list[str]
    temporal: list[str]
    labels: list[str]

    @property
    def label(self) -> str | None:
        return self.temporal[0] if self.temporal else (self.labels[0] if self.labels else None)


def human_name(column: str) -> str:
    return _HUMAN_NAMES.get(column.lower(), column)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def format_number(value: float, *, percent: bool = False) -> str:
    """Russian-style formatting: `1 234 567,8`, `14,8 млн`, `-55,2%`."""
    if percent:
        return f"{value:.1f}".replace(".", ",") + "%"
    abs_value = abs(value)
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".replace(".", ",") + " млн"
    if float(value).is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def profile(columns: Sequence[str], rows: Sequence[JsonRow]) -> DataProfile:
    numeric: list[str] = []
    temporal: list[str] = []
    labels: list[str] = []
    for column in columns:
        values = [row.get(column) for row in rows if row.get(column) is not None]
        if not values:
            labels.append(column)
            continue
        name = column.lower()
        if all(_is_number(v) for v in values):
            if name in ("year",) or name.endswith("_id") or name == "id":
                labels.append(column)
            else:
                numeric.append(column)
        elif all(isinstance(v, str) and _ISO_DATE_RE.match(v) for v in values) or (
            name in _TEMPORAL_NAMES and all(isinstance(v, str) for v in values)
        ):
            temporal.append(column)
        else:
            labels.append(column)
    return DataProfile(numeric=numeric, temporal=temporal, labels=labels)


def choose_value_column(numeric: Sequence[str], question: str = "") -> str | None:
    if not numeric:
        return None
    lowered = [c.lower() for c in numeric]
    for group in _VALUE_PRIORITY:
        for column, low in zip(numeric, lowered, strict=True):
            if any(token in low for token in group):
                return column
    del question
    return numeric[0]


def _is_percent(column: str) -> bool:
    low = column.lower()
    return any(token in low for token in ("pct", "percent", "share", "margin", "change", "growth"))


def _tooltip(columns: Sequence[str], data_profile: DataProfile) -> list[dict[str, Any]]:
    tooltip: list[dict[str, Any]] = []
    for column in list(columns)[:6]:
        if column in data_profile.numeric:
            tooltip.append({"field": column, "type": "quantitative", "title": human_name(column), "format": ",.2f"})
        elif column in data_profile.temporal:
            tooltip.append({"field": column, "type": "temporal", "title": human_name(column)})
        else:
            tooltip.append({"field": column, "type": "nominal", "title": human_name(column)})
    return tooltip


def build_chart_spec(question: str, columns: Sequence[str], rows: Sequence[JsonRow]) -> dict[str, Any] | None:
    """Pick a chart type from the data shape and return a Vega-Lite v5 spec (without data)."""
    if not rows:
        return None
    data_profile = profile(columns, rows)
    value = choose_value_column(data_profile.numeric, question)
    if value is None:
        return None
    tooltip = _tooltip(columns, data_profile)
    y_title = human_name(value)

    if data_profile.temporal:
        x_field = data_profile.temporal[0]
        return {
            "$schema": VEGA_LITE_SCHEMA,
            "description": f"{y_title} по времени",
            "mark": {"type": "line", "point": True, "interpolate": "monotone"},
            "encoding": {
                "x": {"field": x_field, "type": "temporal", "title": human_name(x_field)},
                "y": {"field": value, "type": "quantitative", "title": y_title},
                "tooltip": tooltip,
            },
        }

    label = data_profile.labels[0] if data_profile.labels else None
    if label is None:
        others = [c for c in data_profile.numeric if c != value]
        if not others:
            return None
        return {
            "$schema": VEGA_LITE_SCHEMA,
            "description": f"{human_name(others[0])} vs {y_title}",
            "mark": {"type": "point", "filled": True},
            "encoding": {
                "x": {"field": others[0], "type": "quantitative", "title": human_name(others[0])},
                "y": {"field": value, "type": "quantitative", "title": y_title},
                "tooltip": tooltip,
            },
        }

    q = question.lower()
    values = [row.get(value) for row in rows]
    non_negative = all(isinstance(v, int | float) and _is_number(v) and v >= 0 for v in values)
    if non_negative and len(rows) <= 8 and any(word in q for word in _SHARE_WORDS):
        return {
            "$schema": VEGA_LITE_SCHEMA,
            "description": f"Структура: {y_title}",
            "mark": {"type": "arc", "innerRadius": 60},
            "encoding": {
                "theta": {"field": value, "type": "quantitative", "title": y_title},
                "color": {"field": label, "type": "nominal", "title": human_name(label)},
                "tooltip": tooltip,
            },
        }

    color: dict[str, Any] = {"value": "#4c78a8"}
    if not non_negative:
        color = {"condition": {"test": f"datum['{value}'] < 0", "value": "#e45756"}, "value": "#54a24b"}
    longest_label = max((len(str(row.get(label, ""))) for row in rows), default=0)
    if longest_label > 12 or len(rows) > 10:
        encoding: dict[str, Any] = {
            "y": {"field": label, "type": "nominal", "sort": "-x", "title": human_name(label)},
            "x": {"field": value, "type": "quantitative", "title": y_title},
        }
    else:
        encoding = {
            "x": {
                "field": label,
                "type": "nominal",
                "sort": "-y",
                "axis": {"labelAngle": -30},
                "title": human_name(label),
            },
            "y": {"field": value, "type": "quantitative", "title": y_title},
        }
    encoding["color"] = color
    encoding["tooltip"] = tooltip
    spec: dict[str, Any] = {
        "$schema": VEGA_LITE_SCHEMA,
        "description": f"{y_title} по {human_name(label)}",
        "mark": {"type": "bar", "cornerRadiusEnd": 4},
        "encoding": encoding,
    }
    if "y" in encoding and encoding["y"]["type"] == "nominal":
        spec["height"] = max(120, 30 * len(rows))  # horizontal bars: height follows the number of rows
    return spec


def _referenced_fields(node: Any) -> set[str]:
    fields: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "field" and isinstance(value, str):
                fields.add(value)
            else:
                fields |= _referenced_fields(value)
    elif isinstance(node, list):
        for item in node:
            fields |= _referenced_fields(item)
    return fields


def is_valid_chart_spec(spec: Any, columns: Sequence[str]) -> bool:
    """Minimal structural validation of an LLM-produced Vega-Lite spec."""
    if not isinstance(spec, dict):
        return False
    mark = spec.get("mark")
    if not (isinstance(mark, str) or (isinstance(mark, dict) and isinstance(mark.get("type"), str))):
        return False
    encoding = spec.get("encoding")
    if not isinstance(encoding, dict) or not encoding:
        return False
    fields = _referenced_fields(encoding)
    return bool(fields) and fields.issubset(set(columns))


def attach_data(spec: dict[str, Any], rows: Sequence[JsonRow]) -> dict[str, Any]:
    """Inline the query result into the spec so the UI can render it as is."""
    result = dict(spec)
    result["$schema"] = VEGA_LITE_SCHEMA
    result["data"] = {"values": list(rows)}
    result.setdefault("width", "container")
    result.setdefault("height", 320)
    return result


def heuristic_synthesis(question: str, columns: Sequence[str], rows: Sequence[JsonRow]) -> SynthesisOutput:
    """Deterministic narrative built only from numbers present in the data."""
    chart = build_chart_spec(question, columns, rows)
    if not rows:
        return SynthesisOutput(
            summary="Запрос выполнен успешно, но по заданным условиям данных не найдено.",
            key_findings=[],
            vega_lite_spec=None,
        )

    data_profile = profile(columns, rows)
    value = choose_value_column(data_profile.numeric, question)
    label = data_profile.label
    if value is None or label is None:
        if len(rows) == 1:
            parts = [f"{human_name(k)} — {format_number(float(v)) if _is_number(v) else v}" for k, v in rows[0].items()]
            return SynthesisOutput(summary="Результат: " + "; ".join(parts) + ".", vega_lite_spec=chart)
        first = ", ".join(f"{k}: {v}" for k, v in rows[0].items())
        return SynthesisOutput(
            summary=f"Запрос вернул строк: {len(rows)}. Первая запись — {first}.",
            key_findings=[],
            vega_lite_spec=chart,
        )

    percent = _is_percent(value)
    points = [(str(row.get(label)), float(row[value])) for row in rows if _is_number(row.get(value))]
    if not points:
        return SynthesisOutput(summary=f"Запрос вернул строк: {len(rows)}.", vega_lite_spec=chart)

    name = human_name(value)
    top_label, top_value = max(points, key=lambda p: p[1])
    low_label, low_value = min(points, key=lambda p: p[1])
    findings: list[str] = []

    if label in data_profile.temporal:
        first_label, first_value = points[0]
        last_label, last_value = points[-1]
        summary = (
            f"За период с {first_label[:10]} по {last_label[:10]} показатель «{name}» изменился "
            f"с {format_number(first_value, percent=percent)} до {format_number(last_value, percent=percent)}"
        )
        if first_value and not percent:
            delta = (last_value - first_value) / abs(first_value) * 100
            summary += f" ({'+' if delta >= 0 else ''}{format_number(delta, percent=True)})"
        summary += f". Пик пришёлся на {top_label[:10]}: {format_number(top_value, percent=percent)}."
        findings.append(f"Минимум — {low_label[:10]}: {format_number(low_value, percent=percent)}")
        if not percent:
            avg = sum(v for _, v in points) / len(points)
            findings.append(f"Среднее значение за период: {format_number(avg)}")
    else:
        first_label, first_value = points[0]
        if percent and low_value < 0:
            declines = sorted((p for p in points if p[1] < 0), key=lambda p: p[1])
            summary = (
                f"Наибольшее снижение показателя «{name}» — у «{low_label}» ({format_number(low_value, percent=True)})."
            )
            if len(declines) > 1:
                rest = ", ".join(f"«{label}» ({format_number(v, percent=True)})" for label, v in declines[1:3])
                summary += f" Далее следуют {rest}."
        else:
            summary = (
                f"Первое место в выборке — «{first_label}»: {name} = {format_number(first_value, percent=percent)}."
            )
        total = sum(v for _, v in points)
        if not percent and total > 0 and all(v >= 0 for _, v in points) and "avg" not in value.lower():
            share = first_value / total * 100
            summary += f" Это {format_number(share, percent=True)} от суммарного значения по выборке."
            findings.append(f"Суммарно по выборке: {format_number(total)}")
        if percent and low_value < 0:
            negatives = sum(1 for _, v in points if v < 0)
            findings.append(f"Снижение показали {negatives} из {len(points)} позиций выборки")
            findings.append(f"Наименьшее значение — «{low_label}»: {format_number(low_value, percent=True)}")
            findings.append(f"Наибольшее значение — «{top_label}»: {format_number(top_value, percent=True)}")
        else:
            findings.append(f"Максимум — «{top_label}»: {format_number(top_value, percent=percent)}")
            findings.append(f"Минимум — «{low_label}»: {format_number(low_value, percent=percent)}")
        if len(points) > 1 and low_value > 0 and not percent:
            findings.append(
                f"Разрыв между максимумом и минимумом — в {top_value / low_value:.1f} раза".replace(".", ",")
            )

    return SynthesisOutput(summary=summary, key_findings=findings[:4], vega_lite_spec=chart)
