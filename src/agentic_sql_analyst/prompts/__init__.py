"""Jinja2 runtime prompts of the agents (see `templates/`)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from agentic_sql_analyst.schemas import AttemptRecord, JsonRow, PlannerOutput

TEMPLATES_DIR = Path(__file__).parent / "templates"


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,  # a missing variable is a bug, not an empty string
        autoescape=False,  # noqa: S701 - prompts are plain text, not HTML
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render(template_name: str, **variables: Any) -> str:
    return _env().get_template(template_name).render(**variables)


def _today(today: date | None) -> str:
    return (today or date.today()).isoformat()


def render_planner(*, db_schema: str, user_question: str, today: date | None = None) -> str:
    return render("planner.j2", db_schema=db_schema, user_question=user_question, today=_today(today))


def render_sql_generator(
    *,
    db_schema: str,
    plan: PlannerOutput,
    user_question: str,
    row_limit: int,
    today: date | None = None,
) -> str:
    return render(
        "sql_generator.j2",
        db_schema=db_schema,
        plan_json=plan.model_dump_json(indent=2),
        user_question=user_question,
        row_limit=row_limit,
        today=_today(today),
    )


def render_sql_repair(
    *,
    db_schema: str,
    user_question: str,
    failed_sql: str,
    error_message: str,
    retry_count: int,
    max_retries: int,
    previous_attempts: Sequence[AttemptRecord] = (),
) -> str:
    return render(
        "sql_repair.j2",
        db_schema=db_schema,
        user_question=user_question,
        failed_sql=failed_sql,
        error_message=error_message,
        retry_count=retry_count,
        max_retries=max_retries,
        previous_attempts=list(previous_attempts),
    )


def render_synthesizer(
    *,
    user_question: str,
    sql_query: str,
    columns: Sequence[str],
    rows: Sequence[JsonRow],
    max_rows: int,
) -> str:
    shown = list(rows[:max_rows])
    return render(
        "synthesizer.j2",
        user_question=user_question,
        sql_query=sql_query,
        columns=list(columns),
        query_results_json=json.dumps(shown, ensure_ascii=False, default=str),
        shown_rows=len(shown),
        total_rows=len(rows),
    )


__all__ = [
    "render",
    "render_planner",
    "render_sql_generator",
    "render_sql_repair",
    "render_synthesizer",
]
