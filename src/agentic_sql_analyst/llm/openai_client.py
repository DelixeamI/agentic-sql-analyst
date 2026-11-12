"""Client for any OpenAI-compatible Chat Completions endpoint.

Works with OpenAI (gpt-4o-mini), Ollama (`http://localhost:11434/v1`, e.g. qwen2.5:14b),
vLLM, OpenRouter, LM Studio and GigaChat through an OpenAI-compatible proxy.
"""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Any

from openai import AsyncOpenAI, OpenAIError

from agentic_sql_analyst.llm.base import AgentTask, LLMError
from agentic_sql_analyst.llm.metering import LLMCall, record

SYSTEM_MESSAGE = (
    "Ты — компонент автономной аналитической системы Text-to-SQL. "
    "Строго следуй инструкциям пользователя и отвечай только одним валидным JSON-объектом без Markdown."
)


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        base_url: str | None = None,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
        json_mode: bool = True,
    ) -> None:
        self.name = f"openai:{model}"
        self._model = model
        self._temperature = temperature
        self._json_mode = json_mode
        # Local servers (Ollama, vLLM) accept any key.
        self._client = AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url, timeout=timeout_s)

    async def generate(self, *, task: AgentTask, prompt: str, context: Mapping[str, Any]) -> str:
        del context  # network client uses the rendered prompt only
        extra: dict[str, Any] = {"response_format": {"type": "json_object"}} if self._json_mode else {}
        started = perf_counter()
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=self._temperature,
                seed=42,  # reproducible runs where the backend supports it (OpenAI, Ollama)
                messages=[
                    {"role": "system", "content": SYSTEM_MESSAGE},
                    {"role": "user", "content": prompt},
                ],
                **extra,
            )
        except OpenAIError as error:
            record(LLMCall(task, 0, 0, round((perf_counter() - started) * 1000, 1), ok=False))
            raise LLMError(f"{task.value}: LLM request failed: {error}") from error

        usage = response.usage
        record(
            LLMCall(
                task=task,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                latency_ms=round((perf_counter() - started) * 1000, 1),
            )
        )
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise LLMError(f"{task.value}: LLM returned an empty answer")
        return str(content)
