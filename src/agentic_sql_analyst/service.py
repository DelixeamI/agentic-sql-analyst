"""Application service: wires settings → engine → agents → graph."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from agentic_sql_analyst.agents.nodes import AgentDeps
from agentic_sql_analyst.config import Settings
from agentic_sql_analyst.db import PostgresExecutor, PostgresSchemaInspector, SchemaProvider, create_engine, ping
from agentic_sql_analyst.graph import build_graph
from agentic_sql_analyst.llm import LLMClient, create_llm_client
from agentic_sql_analyst.schemas import AgentState, QueryResponse, RunStatus

RECURSION_LIMIT = 60


class AnalystService:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps
        self._graph = build_graph(deps)

    @property
    def llm_name(self) -> str:
        return self.deps.llm.name

    @property
    def schema_provider(self) -> SchemaProvider:
        return self.deps.schema_provider

    async def run(self, question: str) -> AgentState:
        raw: Any = await self._graph.ainvoke(AgentState(question=question), config={"recursion_limit": RECURSION_LIMIT})
        return raw if isinstance(raw, AgentState) else AgentState.model_validate(raw)

    async def ask(self, question: str) -> QueryResponse:
        started = perf_counter()
        state = await self.run(question)
        rows = (state.query_result or []) if state.status is RunStatus.SUCCESS else []
        return QueryResponse(
            question=state.question,
            status=state.status or RunStatus.FAILED,
            summary=state.synthesis or "Нет ответа",
            key_findings=state.key_findings,
            plan=state.plan,
            sql=state.sql_query,
            retry_count=state.retry_count,
            attempts=state.attempts,
            columns=state.columns if rows else [],
            rows=rows,
            row_count=len(rows),
            chart_spec=state.chart_spec,
            trace=state.trace,
            llm_provider=self.llm_name,
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
        )


@dataclass
class AppResources:
    """Everything the API needs; created on startup, disposed on shutdown."""

    service: AnalystService
    engine: AsyncEngine | None = None

    async def check_database(self) -> None:
        if self.engine is None:
            return
        await ping(self.engine)

    async def aclose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


def build_resources(settings: Settings, *, llm: LLMClient | None = None) -> AppResources:
    engine = create_engine(settings)
    deps = AgentDeps(
        llm=llm or create_llm_client(settings),
        executor=PostgresExecutor(
            engine,
            statement_timeout_ms=settings.statement_timeout_ms,
            max_rows=settings.default_row_limit,
        ),
        schema_provider=PostgresSchemaInspector(engine, ttl_s=settings.schema_cache_ttl_s),
        max_retries=settings.max_retries,
        row_limit=settings.default_row_limit,
        synthesizer_max_rows=settings.synthesizer_max_rows,
    )
    return AppResources(service=AnalystService(deps), engine=engine)
