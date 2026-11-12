"""Per-request LLM usage metering (tokens, latency, number of calls).

A `UsageMeter` is bound to the current async context with :func:`metered`. LLM clients call
:func:`record` after every request; LangGraph node tasks inherit the context, so all calls of
one question land in the same meter without passing it through the graph state.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from agentic_sql_analyst.llm.base import AgentTask


@dataclass(frozen=True)
class LLMCall:
    task: AgentTask
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    ok: bool = True


@dataclass
class UsageMeter:
    calls: list[LLMCall] = field(default_factory=list)

    @property
    def prompt_tokens(self) -> int:
        return sum(call.prompt_tokens for call in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(call.completion_tokens for call in self.calls)

    @property
    def latency_ms(self) -> float:
        return round(sum(call.latency_ms for call in self.calls), 1)

    def by_task(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for call in self.calls:
            totals[call.task.value] = round(totals.get(call.task.value, 0.0) + call.latency_ms, 1)
        return totals


_current: ContextVar[UsageMeter | None] = ContextVar("llm_usage_meter", default=None)


@contextmanager
def metered() -> Iterator[UsageMeter]:
    meter = UsageMeter()
    token = _current.set(meter)
    try:
        yield meter
    finally:
        _current.reset(token)


def record(call: LLMCall) -> None:
    meter = _current.get()
    if meter is not None:
        meter.calls.append(call)
