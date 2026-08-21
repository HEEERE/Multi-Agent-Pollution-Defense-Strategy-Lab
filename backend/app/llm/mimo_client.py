from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING, Any

import httpx

from app.llm.base import ChatMessage, LLMResponse, TokenUsage, ToolCall

if TYPE_CHECKING:
    from app.core.config import Settings

# Observed on https://chatapi.weixin.qq.com/openai/v1 with Deepseek-v4-flash:
# tool calling uses the standard OpenAI `tools` / `tool_choice` fields and comes
# back in `message.tool_calls`. Of the three thinking-mode spellings tried, only
# `reasoning_effort` actually engages separated reasoning (`reasoning_content`
# populated, `usage.reasoning_tokens` > 0); `thinking` and `enable_thinking` are
# accepted but ignored, leaving reasoning inlined in `content`. So the client
# sends `reasoning_effort` and treats the others as unsupported.
_REASONING_EFFORTS = frozenset({"low", "medium", "high"})


class MiMoClient:
    """OpenAI-compatible chat client.

    Supports tool calling and separated reasoning when the configured model
    provides them. Reasoning text is captured for the record but is never an
    authorisation input.
    """

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
        max_input_tokens: int = 200_000,
        max_output_ceiling: int = 48_000,
        tool_calling_enabled: bool = False,
        thinking_enabled: bool = False,
        reasoning_effort: str = "medium",
    ) -> None:
        if settings is not None:
            self.api_key = settings.mimo_api_key
            self.base_url = str(settings.mimo_base_url)
            self.model = settings.mimo_model
            self.enabled = settings.llm_enabled
            self.temperature = settings.llm_temperature
            self.max_tokens = settings.llm_max_tokens
            self.request_timeout = settings.llm_request_timeout_seconds
            self.max_input_tokens = settings.llm_max_input_tokens
            self.max_output_ceiling = settings.llm_max_output_ceiling
            self.tool_calling_enabled = settings.llm_tool_calling_enabled
            self.thinking_enabled = settings.llm_thinking_enabled
            self.reasoning_effort = settings.llm_reasoning_effort
        else:
            self.api_key = api_key
            self.base_url = base_url
            self.model = model
            self.enabled = enabled
            self.temperature = temperature
            self.max_tokens = max_tokens
            self.request_timeout = request_timeout
            self.max_input_tokens = max_input_tokens
            self.max_output_ceiling = max_output_ceiling
            self.tool_calling_enabled = tool_calling_enabled
            self.thinking_enabled = thinking_enabled
            self.reasoning_effort = reasoning_effort

        self._endpoint = (
            f"{self.base_url.rstrip('/')}/chat/completions" if self.base_url else ""
        )

    @property
    def llm_ready(self) -> bool:
        return self.enabled and bool(self.api_key)

    async def chat(
        self,
        messages: list[ChatMessage],
        temperature: float | None = None,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        thinking: bool | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        ``tools`` is only forwarded when tool calling is enabled for this client,
        so a model without the capability degrades to a plain completion instead
        of erroring. Same for ``thinking``.
        """
        if not self.llm_ready:
            return self._disabled_response(messages)

        requested = max_tokens if max_tokens is not None else self.max_tokens
        if requested > self.max_output_ceiling:
            raise ValueError(
                f"max_tokens={requested} exceeds the model's declared output "
                f"ceiling of {self.max_output_ceiling}. Raise "
                f"LLM_MAX_OUTPUT_CEILING if the model really supports it."
            )

        started = perf_counter()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_wire() for m in messages],
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": requested,
        }

        if tools and self.tool_calling_enabled:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        want_thinking = self.thinking_enabled if thinking is None else thinking
        if want_thinking:
            effort = (self.reasoning_effort or "medium").lower()
            payload["reasoning_effort"] = (
                effort if effort in _REASONING_EFFORTS else "medium"
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.post(self._endpoint, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return self._parse(data, started)

    def _parse(self, data: dict[str, Any], started: float) -> LLMResponse:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}

        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            fn = raw.get("function") or {}
            calls.append(
                ToolCall(
                    call_id=str(raw.get("id") or ""),
                    name=str(fn.get("name") or ""),
                    arguments_raw=str(fn.get("arguments") or ""),
                )
            )

        return LLMResponse(
            content=message.get("content") or "",
            model=data.get("model") or self.model,
            provider="openai-compatible",
            latency_ms=int((perf_counter() - started) * 1000),
            tool_calls=calls,
            reasoning_content=str(message.get("reasoning_content") or ""),
            finish_reason=str(choice.get("finish_reason") or ""),
            usage=TokenUsage.from_wire(data.get("usage")),
        )

    def _disabled_response(self, messages: list[ChatMessage]) -> LLMResponse:
        user_message = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        return LLMResponse(
            content=(
                "LLM disabled. Set LLM_ENABLED=true and MIMO_API_KEY to enable "
                f"model reasoning. Received task preview: {user_message[:220]}"
            ),
            model=self.model,
            provider="disabled",
            latency_ms=0,
        )
