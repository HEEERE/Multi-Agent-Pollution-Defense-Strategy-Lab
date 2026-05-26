from time import perf_counter

import httpx

from app.core.config import Settings
from app.llm.base import ChatMessage, LLMResponse


class MiMoClient:
    """OpenAI-compatible chat client for MiMo."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._endpoint = f"{str(settings.mimo_base_url).rstrip('/')}/chat/completions"

    async def chat(self, messages: list[ChatMessage]) -> LLMResponse:
        if not self.settings.llm_ready:
            return self._disabled_response(messages)

        started = perf_counter()
        payload = {
            "model": self.settings.mimo_model,
            "messages": [message.__dict__ for message in messages],
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.mimo_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.settings.llm_request_timeout_seconds) as client:
            response = await client.post(self._endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        return LLMResponse(
            content=content,
            model=self.settings.mimo_model,
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
            model=self.settings.mimo_model,
            provider="mimo-disabled",
            latency_ms=0,
        )
