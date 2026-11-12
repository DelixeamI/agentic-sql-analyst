"""Evaluation harness: result-set comparison, dataset integrity, usage metering, summary."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_sql_analyst.db.executor import unique_column_names
from agentic_sql_analyst.evals.runner import ItemResult, load_dataset, render_markdown, summarize
from agentic_sql_analyst.evals.scoring import compare_results, normalize
from agentic_sql_analyst.llm.base import AgentTask
from agentic_sql_analyst.llm.metering import LLMCall, metered, record
from agentic_sql_analyst.sandbox import validate_sql
from agentic_sql_analyst.schemas import RunStatus

DATASET = Path(__file__).resolve().parents[2] / "evals" / "questions.json"

GOLD_COLS = ["segment", "count"]
GOLD = [{"segment": "b2b", "count": 305}, {"segment": "b2c", "count": 1585}, {"segment": "vip", "count": 110}]


# ------------------------------------------------------------------ scoring
def test_same_values_different_names_and_order_match() -> None:
    pred = [{"n": 1585, "seg": "b2c"}, {"n": 110, "seg": "vip"}, {"n": 305, "seg": "b2b"}]
    assert compare_results(GOLD_COLS, GOLD, ["n", "seg"], pred).correct


def test_extra_predicted_columns_are_allowed() -> None:
    pred = [{**row, "share": 0.1} for row in GOLD]
    assert compare_results(GOLD_COLS, GOLD, [*GOLD_COLS, "share"], pred).correct


def test_wrong_value_is_detected() -> None:
    pred = [*GOLD[:2], {"segment": "vip", "count": 111}]
    result = compare_results(GOLD_COLS, GOLD, GOLD_COLS, pred)
    assert not result.correct
    assert "count" in result.reason


def test_row_count_mismatch() -> None:
    assert "row count" in compare_results(GOLD_COLS, GOLD, GOLD_COLS, GOLD[:2]).reason


def test_misaligned_rows_are_detected() -> None:
    shuffled = [
        {"segment": "b2b", "count": 1585},
        {"segment": "b2c", "count": 305},
        {"segment": "vip", "count": 110},
    ]
    assert not compare_results(GOLD_COLS, GOLD, GOLD_COLS, shuffled).correct


def test_order_matters_only_for_ordered_items() -> None:
    reversed_rows = list(reversed(GOLD))
    assert compare_results(GOLD_COLS, GOLD, GOLD_COLS, reversed_rows).correct
    assert not compare_results(GOLD_COLS, GOLD, GOLD_COLS, reversed_rows, ordered=True).correct


@pytest.mark.parametrize(
    ("gold", "pred", "equal"),
    [
        (2.9785982, 3.0, True),  # ROUND(x, 1)
        (1895980175.569, 1895980175.57, True),
        (1895980175.569, 1895000000.0, False),
        (13, 14, False),
        ("2025-12-01", "2025-12-01T00:00:00+00:00", True),
    ],
)
def test_value_tolerance(gold: object, pred: object, equal: bool) -> None:
    result = compare_results(["v"], [{"v": gold}], ["v"], [{"v": pred}])
    assert result.correct is equal


def test_normalize() -> None:
    assert normalize(5) == 5.0
    assert normalize(" Москва ") == "Москва"
    assert normalize("2026-04-01 00:00:00") == "2026-04-01"
    assert normalize(None) is None


# ------------------------------------------------------------------ dataset
def test_dataset_is_consistent() -> None:
    version, items = load_dataset(DATASET)
    assert version >= 1
    assert len(items) >= 50
    assert len({item.id for item in items}) == len(items)
    answerable = [item for item in items if item.expect == "answer"]
    assert len(answerable) >= 40
    for item in answerable:
        assert item.gold_sql, item.id
        assert validate_sql(item.gold_sql, max_rows=1000).is_valid, item.id
    assert {item.expect for item in items} == {"answer", "refuse", "no_write"}


# ------------------------------------------------------------------ metering & summary
def test_metering_collects_calls_only_inside_context() -> None:
    record(LLMCall(AgentTask.PLANNER, 10, 5, 100.0))  # outside: ignored
    with metered() as meter:
        record(LLMCall(AgentTask.PLANNER, 100, 20, 1000.0))
        record(LLMCall(AgentTask.SQL_GENERATOR, 200, 30, 500.0))
    assert meter.prompt_tokens == 300
    assert meter.completion_tokens == 50
    assert meter.by_task() == {"planner": 1000.0, "sql_generator": 500.0}


def test_unique_column_names() -> None:
    assert unique_column_names(["sum", "sum", "x", "sum"]) == ["sum", "sum_2", "x", "sum_3"]


def _result(item_id: str, expect: str, status: RunStatus, correct: bool, retries: int = 0) -> ItemResult:
    return ItemResult(
        id=item_id,
        category="simple" if expect == "answer" else expect,
        expect=expect,  # type: ignore[arg-type]
        question="q",
        status=status,
        correct=correct,
        reason="r",
        retry_count=retries,
        first_try_correct=correct and retries == 0,
        guard_blocked=False,
        sql=None,
        answer="a",
        elapsed_ms=1000.0,
        llm_calls=3,
        prompt_tokens=3000,
        completion_tokens=300,
        latency_by_agent_ms={"planner": 400.0},
    )


def test_summary_and_markdown() -> None:
    results = [
        _result("s1", "answer", RunStatus.SUCCESS, True),
        _result("s2", "answer", RunStatus.SUCCESS, True, retries=1),
        _result("s3", "answer", RunStatus.SUCCESS, False),
        _result("s4", "answer", RunStatus.REFUSED, False),
        _result("u1", "refuse", RunStatus.REFUSED, True),
        _result("a1", "no_write", RunStatus.REFUSED, True),
    ]
    summary = summarize(results, price_in=1.0, price_out=2.0)
    answerable = summary["answerable"]
    assert answerable["execution_accuracy"] == 0.5
    assert answerable["first_try_accuracy"] == 0.25
    assert answerable["recovered_by_repair"] == 1
    assert answerable["false_refusals"] == 1
    assert summary["cost_usd"]["total"] == pytest.approx((6 * 3000 * 1 + 6 * 300 * 2) / 1e6, abs=1e-4)
    assert summary["adversarial"]["refused_by_planner"] == 1
    from agentic_sql_analyst.evals.runner import EvalReport

    report = EvalReport(
        label="t",
        llm="x",
        dataset_version=1,
        started_at="a",
        finished_at="b",
        summary=summary,
        items=results,
    )
    markdown = render_markdown(report)
    assert "**50.0%**" in markdown
    assert "| s3 |" in markdown
