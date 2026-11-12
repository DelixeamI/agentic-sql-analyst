"""LangGraph state machine: routing, self-repair loop, safe refusal, fallbacks."""

from __future__ import annotations

from agentic_sql_analyst.db.executor import ExecutionResult
from agentic_sql_analyst.graph import GraphRouter
from agentic_sql_analyst.llm.base import AgentTask, LLMError
from agentic_sql_analyst.schemas import AgentState, ErrorStage, PlannerOutput, RunStatus
from agentic_sql_analyst.service import AnalystService
from tests.fakes import PLAN, FakeExecutor, ScriptedLLM, as_json, make_deps, ok_result

GOOD_SQL = "SELECT o.status, COUNT(*) AS orders_count FROM orders o GROUP BY o.status"
SYNTHESIS = as_json(
    {
        "summary": "Выполненных заказов 120.",
        "key_findings": ["80% заказов выполнены"],
        "vega_lite_spec": {
            "mark": "bar",
            "encoding": {
                "x": {"field": "status", "type": "nominal"},
                "y": {"field": "orders_count", "type": "quantitative"},
            },
        },
    }
)


def _nodes(state: AgentState) -> list[str]:
    return [step.node for step in state.trace]


async def test_happy_path_runs_all_agents_once() -> None:
    llm = ScriptedLLM(
        {
            AgentTask.PLANNER: [as_json(PLAN)],
            AgentTask.SQL_GENERATOR: [as_json({"sql": GOOD_SQL, "explanation": "x"})],
            AgentTask.SYNTHESIZER: [SYNTHESIS],
        }
    )
    state = await AnalystService(make_deps(llm)).run("Сколько заказов по статусам?")

    assert state.status is RunStatus.SUCCESS
    assert _nodes(state) == ["planner", "sql_generator", "ast_guard", "executor", "synthesizer"]
    assert state.retry_count == 0
    assert state.synthesis == "Выполненных заказов 120."
    assert state.chart_spec is not None
    assert state.chart_spec["data"]["values"][0]["orders_count"] == 120
    assert "LIMIT 100" in (state.sql_query or "")


async def test_db_error_triggers_repair_and_recovers() -> None:
    def handler(sql: str) -> ExecutionResult:
        if "user_id" in sql:
            return ExecutionResult(error="UndefinedColumnError [42703]: column o.user_id does not exist")
        return ok_result(sql)

    executor = FakeExecutor(handler)
    llm = ScriptedLLM(
        {
            AgentTask.PLANNER: [as_json(PLAN)],
            AgentTask.SQL_GENERATOR: [as_json({"sql": "SELECT o.user_id FROM orders o"})],
            AgentTask.SQL_REPAIR: [as_json({"error_cause": "no user_id", "corrected_sql": GOOD_SQL})],
            AgentTask.SYNTHESIZER: [SYNTHESIS],
        }
    )
    state = await AnalystService(make_deps(llm, executor)).run("q?")

    assert state.status is RunStatus.SUCCESS
    assert state.retry_count == 1
    assert len(executor.executed) == 2
    assert [a.stage for a in state.attempts] == [ErrorStage.EXECUTOR]
    assert "user_id" in state.attempts[0].sql
    repair_context = next(c for t, _, c in llm.calls if t is AgentTask.SQL_REPAIR)
    assert "does not exist" in repair_context["error_message"]
    repair_prompt = next(p for t, p, _ in llm.calls if t is AgentTask.SQL_REPAIR)
    assert "o.user_id" in repair_prompt
    assert "Попытка №1 из 3" in repair_prompt


async def test_security_violation_is_never_executed_and_gets_repaired() -> None:
    executor = FakeExecutor(ok_result)
    llm = ScriptedLLM(
        {
            AgentTask.PLANNER: [as_json(PLAN)],
            AgentTask.SQL_GENERATOR: [as_json({"sql": "SELECT 1; DROP TABLE orders"})],
            AgentTask.SQL_REPAIR: [as_json({"corrected_sql": GOOD_SQL})],
            AgentTask.SYNTHESIZER: [SYNTHESIS],
        }
    )
    state = await AnalystService(make_deps(llm, executor)).run("q?")

    assert state.status is RunStatus.SUCCESS
    assert all("DROP" not in sql.upper() for sql in executor.executed)
    assert state.attempts[0].stage is ErrorStage.AST_GUARD
    assert "Security Violation" in state.attempts[0].error


async def test_retries_are_bounded_and_end_with_safe_refusal() -> None:
    executor = FakeExecutor(ok_result)
    llm = ScriptedLLM(
        {
            AgentTask.PLANNER: [as_json(PLAN)],
            AgentTask.SQL_GENERATOR: [as_json({"sql": "DELETE FROM orders"})],
            AgentTask.SQL_REPAIR: [as_json({"corrected_sql": "DELETE FROM orders"})],
        }
    )
    state = await AnalystService(make_deps(llm, executor, max_retries=3)).run("q?")

    assert state.status is RunStatus.FAILED
    assert state.retry_count == 3
    assert llm.count(AgentTask.SQL_REPAIR) == 3
    assert len(state.attempts) == 4  # initial + 3 repairs
    assert executor.executed == []
    assert "песочницей безопасности" in (state.synthesis or "")
    assert _nodes(state)[-1] == "refusal"


async def test_unanswerable_question_is_refused_without_sql() -> None:
    llm = ScriptedLLM({AgentTask.PLANNER: [as_json({"is_answerable": False, "missing_data": "Нет данных о погоде"})]})
    state = await AnalystService(make_deps(llm)).run("Какая погода?")

    assert state.status is RunStatus.REFUSED
    assert "погоде" in (state.synthesis or "")
    assert llm.count(AgentTask.SQL_GENERATOR) == 0
    assert _nodes(state) == ["planner", "refusal"]


async def test_planner_llm_failure_is_reported() -> None:
    llm = ScriptedLLM({AgentTask.PLANNER: [LLMError("timeout")]})
    state = await AnalystService(make_deps(llm)).run("q?")
    assert state.status is RunStatus.FAILED
    assert "timeout" in (state.synthesis or "")


async def test_generator_garbage_goes_to_repair() -> None:
    llm = ScriptedLLM(
        {
            AgentTask.PLANNER: [as_json(PLAN)],
            AgentTask.SQL_GENERATOR: ["I am sorry, I cannot produce JSON"],
            AgentTask.SQL_REPAIR: [as_json({"corrected_sql": GOOD_SQL})],
            AgentTask.SYNTHESIZER: [SYNTHESIS],
        }
    )
    state = await AnalystService(make_deps(llm)).run("q?")
    assert state.status is RunStatus.SUCCESS
    assert state.attempts[0].stage is ErrorStage.GENERATION
    assert _nodes(state)[:3] == ["planner", "sql_generator", "sql_repair"]


async def test_synthesizer_failure_falls_back_to_heuristics() -> None:
    llm = ScriptedLLM(
        {
            AgentTask.PLANNER: [as_json(PLAN)],
            AgentTask.SQL_GENERATOR: [as_json({"sql": GOOD_SQL})],
            AgentTask.SYNTHESIZER: ["not json at all"],
        }
    )
    state = await AnalystService(make_deps(llm)).run("Сколько заказов по статусам?")
    assert state.status is RunStatus.SUCCESS
    assert "completed" in (state.synthesis or "")
    assert state.chart_spec is not None
    assert "heuristic fallback" in state.trace[-1].detail


async def test_invalid_vega_spec_is_replaced() -> None:
    bad_spec = as_json(
        {"summary": "ok", "vega_lite_spec": {"mark": "bar", "encoding": {"x": {"field": "no_such_column"}}}}
    )
    llm = ScriptedLLM(
        {
            AgentTask.PLANNER: [as_json(PLAN)],
            AgentTask.SQL_GENERATOR: [as_json({"sql": GOOD_SQL})],
            AgentTask.SYNTHESIZER: [bad_spec],
        }
    )
    state = await AnalystService(make_deps(llm)).run("q?")
    assert state.chart_spec is not None
    assert state.chart_spec["encoding"]["x"]["field"] in {"status", "orders_count"}
    assert "chart fallback" in state.trace[-1].detail


async def test_ask_builds_api_response() -> None:
    llm = ScriptedLLM(
        {
            AgentTask.PLANNER: [as_json(PLAN)],
            AgentTask.SQL_GENERATOR: [as_json({"sql": GOOD_SQL})],
            AgentTask.SYNTHESIZER: [SYNTHESIS],
        }
    )
    response = await AnalystService(make_deps(llm)).ask("q?")
    assert response.status is RunStatus.SUCCESS
    assert response.row_count == 2
    assert response.columns == ["status", "orders_count"]
    assert response.llm_provider == "scripted"
    assert response.elapsed_ms >= 0


def test_router_retry_budget() -> None:
    router = GraphRouter(max_retries=2)
    plan = PlannerOutput()
    assert router.retry_or_refuse(AgentState(question="q", retry_count=1)) == "sql_repair"
    assert router.retry_or_refuse(AgentState(question="q", retry_count=2)) == "refusal"
    assert router.after_planner(AgentState(question="q", plan=plan)) == "sql_generator"
    assert router.after_planner(AgentState(question="q")) == "refusal"
    assert router.after_guard(AgentState(question="q", plan=plan, ast_valid=True)) == "executor"
    assert router.after_executor(AgentState(question="q", error_message="boom")) == "sql_repair"
    assert router.after_executor(AgentState(question="q")) == "synthesizer"
