"""Pydantic contracts: LLM outputs, graph state and API models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

JsonRow = dict[str, Any]


# --------------------------------------------------------------------------- #
# LLM output contracts (validated after every LLM call)
# --------------------------------------------------------------------------- #
class PlannerOutput(BaseModel):
    """Planner & Schema Inspector agent output."""

    model_config = ConfigDict(extra="ignore")

    is_answerable: bool = True
    missing_data: str | None = None
    target_tables: list[str] = Field(default_factory=list)
    join_strategy: str = ""
    filters: list[str] = Field(default_factory=list)
    aggregations: list[str] = Field(default_factory=list)
    reasoning_steps: list[str] = Field(default_factory=list)


class SqlGenerationOutput(BaseModel):
    """SQL Generator agent output."""

    model_config = ConfigDict(extra="ignore")

    sql: str = Field(min_length=1)
    explanation: str = ""


class SqlRepairOutput(BaseModel):
    """Error Repair Loop agent output."""

    model_config = ConfigDict(extra="ignore")

    error_cause: str = ""
    corrected_sql: str = Field(min_length=1)
    changes_made: str = ""


class SynthesisOutput(BaseModel):
    """Data Synthesizer agent output."""

    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1)
    key_findings: list[str] = Field(default_factory=list)
    vega_lite_spec: dict[str, Any] | None = None

    @field_validator("key_findings", mode="before")
    @classmethod
    def _coerce_findings(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [value]
        return value


# --------------------------------------------------------------------------- #
# Graph state
# --------------------------------------------------------------------------- #
class RunStatus(StrEnum):
    SUCCESS = "success"
    REFUSED = "refused"  # question can't be answered from the schema
    FAILED = "failed"  # retries exhausted / unrecoverable error


class ErrorStage(StrEnum):
    GENERATION = "generation"
    AST_GUARD = "ast_guard"
    EXECUTOR = "executor"


class AttemptRecord(BaseModel):
    """One failed SQL attempt, used by the repair agent and shown in the UI."""

    attempt: int
    sql: str
    stage: ErrorStage
    error: str


class TraceStep(BaseModel):
    """Observability: one executed graph node."""

    node: str
    status: Literal["ok", "error", "info"]
    detail: str = ""
    duration_ms: float = 0.0


class AgentState(BaseModel):
    """State of the LangGraph state machine."""

    question: str
    plan: PlannerOutput | None = None
    sql_query: str | None = None
    sql_explanation: str | None = None
    ast_valid: bool = False
    limit_injected: bool = False
    error_message: str | None = None
    error_stage: ErrorStage | None = None
    retry_count: int = 0
    query_result: list[JsonRow] | None = None
    columns: list[str] = Field(default_factory=list)
    synthesis: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    chart_spec: dict[str, Any] | None = None
    status: RunStatus | None = None
    attempts: list[AttemptRecord] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000, examples=["Динамика выручки по месяцам за 2026 год"])

    @field_validator("question")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("question is too short")
        return stripped


class QueryResponse(BaseModel):
    question: str
    status: RunStatus
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    plan: PlannerOutput | None = None
    sql: str | None = None
    retry_count: int = 0
    attempts: list[AttemptRecord] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[JsonRow] = Field(default_factory=list)
    row_count: int = 0
    chart_spec: dict[str, Any] | None = None
    trace: list[TraceStep] = Field(default_factory=list)
    llm_provider: str
    elapsed_ms: float


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    llm_provider: str
    detail: str | None = None


class SchemaResponse(BaseModel):
    ddl: str


class ExampleQuestion(BaseModel):
    title: str
    question: str
