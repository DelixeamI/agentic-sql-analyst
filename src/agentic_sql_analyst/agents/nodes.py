"""LangGraph nodes: planner, sql_generator, ast_guard, executor, sql_repair, synthesizer, refusal.

Every node receives the immutable `AgentState` and returns a dict of updates.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

from agentic_sql_analyst.agents.insights import attach_data, build_chart_spec, heuristic_synthesis, is_valid_chart_spec
from agentic_sql_analyst.db.executor import QueryExecutor
from agentic_sql_analyst.db.schema_inspector import SchemaProvider
from agentic_sql_analyst.llm.base import AgentTask, LLMClient, LLMError, parse_llm_output
from agentic_sql_analyst.prompts import render_planner, render_sql_generator, render_sql_repair, render_synthesizer
from agentic_sql_analyst.sandbox.ast_guard import clean_sql, validate_sql
from agentic_sql_analyst.schemas import (
    AgentState,
    AttemptRecord,
    ErrorStage,
    PlannerOutput,
    RunStatus,
    SqlGenerationOutput,
    SqlRepairOutput,
    SynthesisOutput,
    TraceStep,
)

Updates = dict[str, Any]
StepStatus = Literal["ok", "error", "info"]


@dataclass(frozen=True)
class AgentDeps:
    llm: LLMClient
    executor: QueryExecutor
    schema_provider: SchemaProvider
    max_retries: int = 3
    row_limit: int = 100
    synthesizer_max_rows: int = 50


def _shorten(text: str, limit: int = 220) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "…"


class AnalystNodes:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _trace(state: AgentState, node: str, started: float, status: StepStatus, detail: str) -> list[TraceStep]:
        step = TraceStep(
            node=node,
            status=status,
            detail=_shorten(detail),
            duration_ms=round((perf_counter() - started) * 1000, 1),
        )
        return [*state.trace, step]

    @staticmethod
    def _attempt(state: AgentState, stage: ErrorStage, error: str) -> list[AttemptRecord]:
        record = AttemptRecord(attempt=len(state.attempts) + 1, sql=state.sql_query or "", stage=stage, error=error)
        return [*state.attempts, record]

    # ------------------------------------------------------------------ nodes
    async def planner(self, state: AgentState) -> Updates:
        started = perf_counter()
        ddl = await self.deps.schema_provider.get_ddl()
        prompt = render_planner(db_schema=ddl, user_question=state.question)
        try:
            raw = await self.deps.llm.generate(
                task=AgentTask.PLANNER, prompt=prompt, context={"question": state.question}
            )
            plan = parse_llm_output(raw, PlannerOutput)
        except LLMError as error:
            return {
                "status": RunStatus.FAILED,
                "error_message": str(error),
                "error_stage": ErrorStage.GENERATION,
                "trace": self._trace(state, "planner", started, "error", str(error)),
            }
        if not plan.is_answerable:
            detail = f"вопрос вне схемы: {plan.missing_data or 'нет данных'}"
            return {"plan": plan, "trace": self._trace(state, "planner", started, "info", detail)}
        detail = f"таблицы: {', '.join(plan.target_tables) or '—'}; шагов: {len(plan.reasoning_steps)}"
        return {"plan": plan, "trace": self._trace(state, "planner", started, "ok", detail)}

    async def sql_generator(self, state: AgentState) -> Updates:
        started = perf_counter()
        assert state.plan is not None  # guaranteed by routing
        ddl = await self.deps.schema_provider.get_ddl()
        prompt = render_sql_generator(
            db_schema=ddl, plan=state.plan, user_question=state.question, row_limit=self.deps.row_limit
        )
        context = {"question": state.question, "plan": state.plan.model_dump()}
        try:
            raw = await self.deps.llm.generate(task=AgentTask.SQL_GENERATOR, prompt=prompt, context=context)
            output = parse_llm_output(raw, SqlGenerationOutput)
        except LLMError as error:
            return {
                "sql_query": None,
                "error_message": str(error),
                "error_stage": ErrorStage.GENERATION,
                "attempts": self._attempt(state, ErrorStage.GENERATION, str(error)),
                "trace": self._trace(state, "sql_generator", started, "error", str(error)),
            }
        sql = clean_sql(output.sql)
        return {
            "sql_query": sql,
            "sql_explanation": output.explanation,
            "error_message": None,
            "error_stage": None,
            "trace": self._trace(state, "sql_generator", started, "ok", output.explanation or sql),
        }

    async def ast_guard(self, state: AgentState) -> Updates:
        started = perf_counter()
        result = validate_sql(state.sql_query, max_rows=self.deps.row_limit)
        if not result.is_valid:
            error = result.error_message or "Security Violation"
            return {
                "ast_valid": False,
                "error_message": error,
                "error_stage": ErrorStage.AST_GUARD,
                "attempts": self._attempt(state, ErrorStage.AST_GUARD, error),
                "trace": self._trace(state, "ast_guard", started, "error", error),
            }
        notes = ["single SELECT", "no system schemas"]
        if result.limit_injected:
            notes.append(f"LIMIT {self.deps.row_limit} injected")
        if result.limit_clamped:
            notes.append(f"LIMIT clamped to {self.deps.row_limit}")
        return {
            "ast_valid": True,
            "sql_query": result.sql,
            "limit_injected": result.limit_injected,
            "error_message": None,
            "error_stage": None,
            "trace": self._trace(state, "ast_guard", started, "ok", "; ".join(notes)),
        }

    async def executor(self, state: AgentState) -> Updates:
        started = perf_counter()
        assert state.sql_query is not None  # guaranteed by routing
        assert state.ast_valid
        result = await self.deps.executor.execute(state.sql_query)
        if not result.ok:
            error = result.error or "unknown database error"
            return {
                "error_message": error,
                "error_stage": ErrorStage.EXECUTOR,
                "attempts": self._attempt(state, ErrorStage.EXECUTOR, error),
                "trace": self._trace(state, "executor", started, "error", error),
            }
        return {
            "query_result": result.rows,
            "columns": result.columns,
            "error_message": None,
            "error_stage": None,
            "trace": self._trace(state, "executor", started, "ok", f"rows: {len(result.rows)} (read-only tx)"),
        }

    async def sql_repair(self, state: AgentState) -> Updates:
        started = perf_counter()
        retry = state.retry_count + 1
        ddl = await self.deps.schema_provider.get_ddl()
        error_message = state.error_message or "unknown error"
        prompt = render_sql_repair(
            db_schema=ddl,
            user_question=state.question,
            failed_sql=state.sql_query or "",
            error_message=error_message,
            retry_count=retry,
            max_retries=self.deps.max_retries,
            previous_attempts=state.attempts[:-1],
        )
        context = {
            "question": state.question,
            "failed_sql": state.sql_query or "",
            "error_message": error_message,
            "error_stage": state.error_stage.value if state.error_stage else None,
            "retry_count": retry,
        }
        try:
            raw = await self.deps.llm.generate(task=AgentTask.SQL_REPAIR, prompt=prompt, context=context)
            output = parse_llm_output(raw, SqlRepairOutput)
        except LLMError as error:
            return {
                "retry_count": retry,
                "trace": self._trace(state, "sql_repair", started, "error", f"#{retry}: {error}"),
            }
        detail = f"#{retry}: {output.error_cause} → {output.changes_made}".strip()
        return {
            "retry_count": retry,
            "sql_query": clean_sql(output.corrected_sql),
            "ast_valid": False,
            "error_message": None,
            "error_stage": None,
            "trace": self._trace(state, "sql_repair", started, "ok", detail),
        }

    async def synthesizer(self, state: AgentState) -> Updates:
        started = perf_counter()
        rows = state.query_result or []
        columns = state.columns
        source = "llm"
        if not rows:
            output = heuristic_synthesis(state.question, columns, rows)
            source = "no rows"
        else:
            prompt = render_synthesizer(
                user_question=state.question,
                sql_query=state.sql_query or "",
                columns=columns,
                rows=rows,
                max_rows=self.deps.synthesizer_max_rows,
            )
            context = {"question": state.question, "columns": columns, "rows": rows}
            try:
                raw = await self.deps.llm.generate(task=AgentTask.SYNTHESIZER, prompt=prompt, context=context)
                output = parse_llm_output(raw, SynthesisOutput)
            except LLMError:
                output = heuristic_synthesis(state.question, columns, rows)
                source = "heuristic fallback"

        spec = output.vega_lite_spec
        if spec is not None and not is_valid_chart_spec(spec, columns):
            spec = build_chart_spec(state.question, columns, rows)
            source += ", chart fallback"
        chart = attach_data(spec, rows) if spec is not None and rows else None
        mark = chart.get("mark") if chart else None
        mark_type = mark.get("type") if isinstance(mark, dict) else mark
        detail = f"source: {source}; chart: {mark_type or 'none'}"
        return {
            "synthesis": output.summary,
            "key_findings": output.key_findings,
            "chart_spec": chart,
            "status": RunStatus.SUCCESS,
            "trace": self._trace(state, "synthesizer", started, "ok", detail),
        }

    async def refusal(self, state: AgentState) -> Updates:
        """Safe refusal: unanswerable question or exhausted repair budget."""
        started = perf_counter()
        plan: PlannerOutput | None = state.plan
        if plan is not None and not plan.is_answerable:
            status = RunStatus.REFUSED
            message = f"Не могу ответить на вопрос по имеющимся данным. {plan.missing_data or ''}".strip()
        elif plan is None:
            status = RunStatus.FAILED
            message = f"Не удалось построить план запроса: {state.error_message or 'неизвестная ошибка'}"
        else:
            status = RunStatus.FAILED
            reason = (
                "запрос отклонён песочницей безопасности"
                if state.error_stage is ErrorStage.AST_GUARD
                else "запрос не удалось исправить"
            )
            message = (
                f"Безопасный отказ: {reason} после {state.retry_count} попыток исправления. "
                f"Последняя ошибка: {_shorten(state.error_message or 'нет данных', 300)}"
            )
        return {
            "status": status,
            "synthesis": message,
            "chart_spec": None,
            "trace": self._trace(state, "refusal", started, "info", message),
        }
