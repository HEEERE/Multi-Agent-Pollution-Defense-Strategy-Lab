from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

import httpx

from app.llm.base import ChatMessage, LLMResponse

if TYPE_CHECKING:
    from app.core.config import Settings


class MiMoClient:
    """OpenAI-compatible chat client for MiMo."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        enabled: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 700,
        request_timeout: float = 45,
    ) -> None:
        if settings is not None:
            self.api_key = settings.mimo_api_key
            self.base_url = str(settings.mimo_base_url)
            self.model = settings.mimo_model
            self.enabled = settings.llm_enabled
            self.temperature = settings.llm_temperature
            self.max_tokens = settings.llm_max_tokens
            self.request_timeout = settings.llm_request_timeout_seconds
        else:
            self.api_key = api_key
            self.base_url = base_url
            self.model = model
            self.enabled = enabled
            self.temperature = temperature
            self.max_tokens = max_tokens
            self.request_timeout = request_timeout

        self._endpoint = f"{self.base_url.rstrip('/')}/chat/completions" if self.base_url else ""

    @property
    def llm_ready(self) -> bool:
        return self.enabled and bool(self.api_key)

    async def chat(self, messages: list[ChatMessage], temperature: float | None = None) -> LLMResponse:
        if not self.llm_ready:
            return self._disabled_response(messages)

        started = perf_counter()
        payload = {
            "model": self.model,
            "messages": [message.__dict__ for message in messages],
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.post(self._endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        return LLMResponse(
            content=content,
            model=self.model,
            provider="mimo",
            latency_ms=int((perf_counter() - started) * 1000),
        )

    def _disabled_response(self, messages: list[ChatMessage]) -> LLMResponse:
        user_message = next((message.content for message in reversed(messages) if message.role == "user"), "")
        return LLMResponse(
            content=(
                "LLM disabled. Set LLM_ENABLED=true and MIMO_API_KEY to enable MiMo reasoning. "
                f"Received task preview: {user_message[:220]}"
            ),
            model=self.model,
            provider="mimo-disabled",
            latency_ms=0,
        )
