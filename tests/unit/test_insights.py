"""Chart selection and deterministic narrative."""

from __future__ import annotations

from agentic_sql_analyst.agents.insights import (
    attach_data,
    build_chart_spec,
    choose_value_column,
    format_number,
    heuristic_synthesis,
    is_valid_chart_spec,
    profile,
)

MONTHLY = [
    {"month": "2026-01-01", "revenue": 1000.0, "orders_count": 10},
    {"month": "2026-02-01", "revenue": 1500.0, "orders_count": 12},
    {"month": "2026-03-01", "revenue": 1200.0, "orders_count": 11},
]
CATEGORIES = [
    {"category": "Ноутбуки", "revenue": 600.0},
    {"category": "Аудио", "revenue": 300.0},
    {"category": "Книги", "revenue": 100.0},
]


def test_profile_detects_column_kinds() -> None:
    data = profile(["month", "revenue", "orders_count"], MONTHLY)
    assert data.temporal == ["month"]
    assert data.numeric == ["revenue", "orders_count"]


def test_value_column_priority() -> None:
    assert choose_value_column(["orders_count", "revenue"]) == "revenue"
    assert choose_value_column(["q1_revenue", "q2_revenue", "change_pct"]) == "change_pct"
    assert choose_value_column([]) is None


def test_time_series_becomes_line_chart() -> None:
    spec = build_chart_spec("динамика", ["month", "revenue", "orders_count"], MONTHLY)
    assert spec is not None
    assert spec["mark"]["type"] == "line"
    assert spec["encoding"]["x"]["type"] == "temporal"


def test_categories_become_bar_chart() -> None:
    spec = build_chart_spec("выручка по категориям", ["category", "revenue"], CATEGORIES)
    assert spec is not None
    assert spec["mark"]["type"] == "bar"


def test_share_question_becomes_donut() -> None:
    spec = build_chart_spec("доля категорий", ["category", "revenue"], CATEGORIES)
    assert spec is not None
    assert spec["mark"]["type"] == "arc"


def test_two_numbers_become_scatter() -> None:
    rows = [{"price": 10.0, "quantity": 3}, {"price": 20.0, "quantity": 1}]
    spec = build_chart_spec("связь цены и спроса", ["price", "quantity"], rows)
    assert spec is not None
    assert spec["mark"]["type"] == "point"


def test_no_chart_for_empty_or_text_only() -> None:
    assert build_chart_spec("q", ["a"], []) is None
    assert build_chart_spec("q", ["name"], [{"name": "x"}]) is None


def test_spec_validation_checks_fields() -> None:
    good = {"mark": "bar", "encoding": {"x": {"field": "category"}, "y": {"field": "revenue"}}}
    assert is_valid_chart_spec(good, ["category", "revenue"])
    assert not is_valid_chart_spec(good, ["category"])
    assert not is_valid_chart_spec({"encoding": {}}, ["category"])
    assert not is_valid_chart_spec("bar", ["category"])


def test_attach_data_inlines_rows() -> None:
    spec = attach_data({"mark": "bar", "encoding": {}}, CATEGORIES)
    assert spec["data"]["values"] == CATEGORIES
    assert spec["$schema"].endswith("v5.json")


def test_heuristic_synthesis_uses_real_numbers() -> None:
    output = heuristic_synthesis("выручка по категориям", ["category", "revenue"], CATEGORIES)
    assert "Ноутбуки" in output.summary
    assert "60,0%" in output.summary  # 600 / 1000
    assert output.vega_lite_spec is not None


def test_heuristic_synthesis_time_series_trend() -> None:
    output = heuristic_synthesis("динамика", ["month", "revenue", "orders_count"], MONTHLY)
    assert "+20,0%" in output.summary  # 1000 -> 1200
    assert "2026-02-01" in output.summary  # peak


def test_heuristic_synthesis_empty() -> None:
    assert "не найдено" in heuristic_synthesis("q", ["a"], []).summary


def test_format_number() -> None:
    assert format_number(14_800_000) == "14,8 млн"
    assert format_number(12345) == "12 345"
    assert format_number(-55.24, percent=True) == "-55,2%"


def test_single_value_answer_is_human_readable() -> None:
    output = heuristic_synthesis("Сколько заказов?", ["orders_count"], [{"orders_count": 27194}])
    assert output.summary == "Результат: количество заказов — 27 194."
