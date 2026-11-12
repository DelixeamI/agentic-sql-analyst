"""LLM client abstraction and robust JSON output parsing."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class AgentTask(StrEnum):
    PLANNER = "planner"
    SQL_GENERATOR = "sql_generator"
    SQL_REPAIR = "sql_repair"
    SYNTHESIZER = "synthesizer"


class LLMError(RuntimeError):
    """LLM call failed or returned output that violates the contract."""


class LLMClient(Protocol):
    """Minimal async LLM interface used by every agent.

    `prompt` is the fully rendered runtime prompt. `context` carries the structured inputs the
    prompt was rendered from; network clients ignore it, deterministic clients (demo mode,
    tests) use it instead of parsing the prompt text.
    """

    name: str

    async def generate(self, *, task: AgentTask, prompt: str, context: Mapping[str, Any]) -> str: ...


def extract_json_object(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM answer (tolerates fences and chatter)."""
    text = raw.strip()
    fenced = _FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"LLM answer contains no JSON object: {raw[:200]!r}") from None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as error:
            raise LLMError(f"LLM answer is not valid JSON: {error}") from error

    if not isinstance(value, dict):
        raise LLMError(f"LLM answer must be a JSON object, got {type(value).__name__}")
    return value


def parse_llm_output[ModelT: BaseModel](raw: str, model: type[ModelT]) -> ModelT:
    """Parse and validate LLM output against a Pydantic contract."""
    payload = extract_json_object(raw)
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise LLMError(f"LLM answer violates {model.__name__} contract: {error.error_count()} error(s)") from error
