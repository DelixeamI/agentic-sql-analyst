"""Robust parsing of LLM JSON answers into Pydantic contracts."""

from __future__ import annotations

import pytest

from agentic_sql_analyst.config import Settings
from agentic_sql_analyst.llm import create_llm_client
from agentic_sql_analyst.llm.base import LLMError, extract_json_object, parse_llm_output
from agentic_sql_analyst.llm.demo_client import DemoLLMClient
from agentic_sql_analyst.llm.openai_client import OpenAICompatibleClient
from agentic_sql_analyst.schemas import PlannerOutput, SqlGenerationOutput, SynthesisOutput


def test_plain_json() -> None:
    assert extract_json_object('{"sql": "SELECT 1"}') == {"sql": "SELECT 1"}


def test_json_in_markdown_fence() -> None:
    raw = 'Вот ответ:\n```json\n{"sql": "SELECT 1", "explanation": "e"}\n```'
    assert parse_llm_output(raw, SqlGenerationOutput).sql == "SELECT 1"


def test_json_surrounded_by_chatter() -> None:
    raw = 'Sure! {"summary": "ok", "key_findings": "single finding"} hope it helps'
    output = parse_llm_output(raw, SynthesisOutput)
    assert output.key_findings == ["single finding"]


def test_no_json_raises() -> None:
    with pytest.raises(LLMError, match="no JSON"):
        extract_json_object("I cannot help with that")


def test_json_array_is_rejected() -> None:
    with pytest.raises(LLMError, match="JSON object"):
        extract_json_object("[1, 2, 3]")


def test_contract_violation_raises() -> None:
    with pytest.raises(LLMError, match="SqlGenerationOutput"):
        parse_llm_output('{"sql": ""}', SqlGenerationOutput)


def test_planner_defaults_and_extra_fields() -> None:
    plan = parse_llm_output('{"target_tables": ["orders"], "unknown": 1}', PlannerOutput)
    assert plan.is_answerable is True
    assert plan.target_tables == ["orders"]


def test_factory_selects_provider() -> None:
    assert isinstance(create_llm_client(Settings(llm_provider="demo")), DemoLLMClient)
    client = create_llm_client(
        Settings(llm_provider="openai", llm_model="qwen2.5:14b", llm_base_url="http://localhost:11434/v1")
    )
    assert isinstance(client, OpenAICompatibleClient)
    assert client.name == "openai:qwen2.5:14b"
