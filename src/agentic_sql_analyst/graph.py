"""LangGraph state machine of the analyst.

START → planner ─┬─(unanswerable / failed)──────────────────────────→ refusal → END
                 └→ sql_generator ─┬→ ast_guard ─┬─(valid)→ executor ─┬─(ok)→ synthesizer → END
                                   │             │                    │
                                   │             └─(invalid)┐         └─(DB error)┐
                                   └─(bad LLM output)───────┴→ sql_repair ←───────┘
                                                               │  (retry_count < max_retries)
                                                               └→ ast_guard   (else → refusal)
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from agentic_sql_analyst.agents.nodes import AgentDeps, AnalystNodes
from agentic_sql_analyst.schemas import AgentState, ErrorStage, RunStatus

RetryRoute = Literal["sql_repair", "refusal"]


class GraphRouter:
    """Pure routing functions (unit-tested separately from the nodes)."""

    def __init__(self, max_retries: int) -> None:
        self.max_retries = max_retries

    def retry_or_refuse(self, state: AgentState) -> RetryRoute:
        return "sql_repair" if state.retry_count < self.max_retries else "refusal"

    def after_planner(self, state: AgentState) -> Literal["sql_generator", "refusal"]:
        if state.status is RunStatus.FAILED or state.plan is None or not state.plan.is_answerable:
            return "refusal"
        return "sql_generator"

    def after_generator(self, state: AgentState) -> Literal["ast_guard", "sql_repair", "refusal"]:
        if state.error_stage is ErrorStage.GENERATION:
            return self.retry_or_refuse(state)
        return "ast_guard"

    def after_guard(self, state: AgentState) -> Literal["executor", "sql_repair", "refusal"]:
        if state.ast_valid:
            return "executor"
        return self.retry_or_refuse(state)

    def after_executor(self, state: AgentState) -> Literal["synthesizer", "sql_repair", "refusal"]:
        if state.error_message is None:
            return "synthesizer"
        return self.retry_or_refuse(state)


def build_graph(deps: AgentDeps) -> Any:
    """Compile the multi-agent state machine. Returns a LangGraph `CompiledStateGraph`."""
    nodes = AnalystNodes(deps)
    router = GraphRouter(deps.max_retries)

    graph = StateGraph(AgentState)
    graph.add_node("planner", nodes.planner)
    graph.add_node("sql_generator", nodes.sql_generator)
    graph.add_node("ast_guard", nodes.ast_guard)
    graph.add_node("executor", nodes.executor)
    graph.add_node("sql_repair", nodes.sql_repair)
    graph.add_node("synthesizer", nodes.synthesizer)
    graph.add_node("refusal", nodes.refusal)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", router.after_planner, ["sql_generator", "refusal"])
    graph.add_conditional_edges("sql_generator", router.after_generator, ["ast_guard", "sql_repair", "refusal"])
    graph.add_conditional_edges("ast_guard", router.after_guard, ["executor", "sql_repair", "refusal"])
    graph.add_conditional_edges("executor", router.after_executor, ["synthesizer", "sql_repair", "refusal"])
    graph.add_edge("sql_repair", "ast_guard")
    graph.add_edge("synthesizer", END)
    graph.add_edge("refusal", END)
    return graph.compile()


def mermaid_diagram(deps: AgentDeps) -> str:
    """Mermaid source of the compiled graph (used to keep the README diagram honest)."""
    compiled = build_graph(deps)
    return str(compiled.get_graph().draw_mermaid())
