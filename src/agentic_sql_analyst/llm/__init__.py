"""LLM clients."""

from __future__ import annotations

from agentic_sql_analyst.config import Settings
from agentic_sql_analyst.llm.base import AgentTask, LLMClient, LLMError, extract_json_object, parse_llm_output
from agentic_sql_analyst.llm.demo_client import DemoLLMClient
from agentic_sql_analyst.llm.openai_client import OpenAICompatibleClient


def create_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "openai":
        api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
        return OpenAICompatibleClient(
            model=settings.llm_model,
            api_key=api_key,
            base_url=settings.llm_base_url,
            temperature=settings.llm_temperature,
            timeout_s=settings.llm_timeout_s,
            json_mode=settings.llm_json_mode,
        )
    return DemoLLMClient()


__all__ = [
    "AgentTask",
    "DemoLLMClient",
    "LLMClient",
    "LLMError",
    "OpenAICompatibleClient",
    "create_llm_client",
    "extract_json_object",
    "parse_llm_output",
]
