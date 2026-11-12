"""Test doubles: scripted LLM, in-memory executor and schema provider."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from agentic_sql_analyst.agents.nodes import AgentDeps
from agentic_sql_analyst.db.executor import ExecutionResult
from agentic_sql_analyst.llm.base import AgentTask, LLMError

FAKE_DDL = """CREATE TABLE orders (
    id integer NOT NULL,
    customer_id integer NOT NULL,
    status text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);"""

PLAN = {
    "is_answerable": True,
    "target_tables": ["orders"],
    "join_strategy": "",
    "filters": ["orders.status = 'completed'"],
    "aggregations": ["COUNT(*)"],
    "reasoning_steps": ["1. count"],
}


def as_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


class ScriptedLLM:
    """Returns queued answers per task. An `Exception` in the queue is raised instead."""

    name = "scripted"

    def __init__(self, script: Mapping[AgentTask, Iterable[str | Exception]]) -> None:
        self._queues: dict[AgentTask, deque[str | Exception]] = defaultdict(deque)
        for task, answers in script.items():
            self._queues[task].extend(answers)
        self.calls: list[tuple[AgentTask, str, dict[str, Any]]] = []

    async def generate(self, *, task: AgentTask, prompt: str, context: Mapping[str, Any]) -> str:
        self.calls.append((task, prompt, dict(context)))
        queue = self._queues[task]
        if not queue:
            raise LLMError(f"no scripted answer for {task.value}")
        answer = queue.popleft() if len(queue) > 1 else queue[0]  # last answer repeats
        if isinstance(answer, Exception):
            raise answer
        return answer

    def count(self, task: AgentTask) -> int:
        return sum(1 for call in self.calls if call[0] is task)


class FakeExecutor:
    """`handler(sql)` decides the result; every executed SQL is recorded."""

    def __init__(self, handler: Callable[[str], ExecutionResult]) -> None:
        self._handler = handler
        self.executed: list[str] = []

    async def execute(self, sql: str) -> ExecutionResult:
        self.executed.append(sql)
        return self._handler(sql)


class FakeSchema:
    def __init__(self, ddl: str = FAKE_DDL) -> None:
        self.ddl = ddl
        self.calls = 0

    async def get_ddl(self) -> str:
        self.calls += 1
        return self.ddl


ROWS = [
    {"status": "completed", "orders_count": 120},
    {"status": "cancelled", "orders_count": 30},
]


def ok_result(sql: str) -> ExecutionResult:
    del sql
    return ExecutionResult(columns=["status", "orders_count"], rows=list(ROWS))


def make_deps(llm: Any, executor: Any | None = None, *, max_retries: int = 3) -> AgentDeps:
    return AgentDeps(
        llm=llm,
        executor=executor or FakeExecutor(ok_result),
        schema_provider=FakeSchema(),
        max_retries=max_retries,
        row_limit=100,
    )
