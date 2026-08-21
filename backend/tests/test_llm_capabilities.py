"""Tool calling, thinking mode and capability-gating in the LLM client.

Request-shaping and response-parsing are covered offline with a stub transport,
so the contract is pinned without spending tokens. The live probe at the end is
opt-in via RUN_LIVE_LLM_TESTS=1.
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from app.llm.base import ChatMessage, TokenUsage, ToolCall
from app.llm.mimo_client import MiMoClient

WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}


def _client(**over) -> MiMoClient:
    base = {
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
        "model": "Deepseek-v4-flash",
        "enabled": True,
        "tool_calling_enabled": True,
        "thinking_enabled": True,
        "reasoning_effort": "medium",
        "max_tokens": 48000,
    }
    base.update(over)
    return MiMoClient(**base)


class _Capture:
    """Records the outgoing payload and replays a canned response."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.payload: dict | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.payload = json.loads(request.content.decode())
        return httpx.Response(200, json=self.response)


def _patch(monkeypatch, capture: _Capture) -> None:
    transport = httpx.MockTransport(capture.handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


PLAIN_RESPONSE = {
    "model": "Deepseek-v4-flash",
    "choices": [
        {
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "OK"},
        }
    ],
    "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
}

TOOL_RESPONSE = {
    "model": "Deepseek-v4-flash",
    "choices": [
        {
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": "I'll check that.",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "index": 0,
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Beijing"}',
                        },
                    }
                ],
            },
        }
    ],
    "usage": {"prompt_tokens": 290, "completion_tokens": 53, "total_tokens": 343},
}

THINKING_RESPONSE = {
    "model": "Deepseek-v4-flash",
    "choices": [
        {
            "finish_reason": "stop",
            "message": {
                "role": "assistant",
                "content": "391",
                "reasoning_content": "17*(20+3) = 340+51 = 391.",
            },
        }
    ],
    "usage": {
        "prompt_tokens": 14,
        "completion_tokens": 65,
        "reasoning_tokens": 56,
        "total_tokens": 79,
    },
}


class TestRequestShaping:
    async def test_tools_are_forwarded_when_enabled(self, monkeypatch):
        cap = _Capture(TOOL_RESPONSE)
        _patch(monkeypatch, cap)
        await _client().chat(
            [ChatMessage("user", "weather in Beijing?")], tools=[WEATHER_TOOL]
        )
        assert cap.payload is not None
        assert cap.payload["tools"] == [WEATHER_TOOL]
        assert cap.payload["tool_choice"] == "auto"

    async def test_tools_are_dropped_when_capability_disabled(self, monkeypatch):
        """A model without tool calling must degrade, not error."""
        cap = _Capture(PLAIN_RESPONSE)
        _patch(monkeypatch, cap)
        await _client(tool_calling_enabled=False).chat(
            [ChatMessage("user", "hi")], tools=[WEATHER_TOOL]
        )
        assert "tools" not in cap.payload
        assert "tool_choice" not in cap.payload

    async def test_thinking_sends_reasoning_effort_only(self, monkeypatch):
        """Only reasoning_effort actually engages thinking on this endpoint.

        `thinking` and `enable_thinking` are accepted but ignored there, so
        sending them would be cargo cult.
        """
        cap = _Capture(THINKING_RESPONSE)
        _patch(monkeypatch, cap)
        await _client().chat([ChatMessage("user", "17*23?")])
        assert cap.payload["reasoning_effort"] == "medium"
        assert "thinking" not in cap.payload
        assert "enable_thinking" not in cap.payload

    async def test_thinking_can_be_overridden_per_call(self, monkeypatch):
        cap = _Capture(PLAIN_RESPONSE)
        _patch(monkeypatch, cap)
        await _client().chat([ChatMessage("user", "hi")], thinking=False)
        assert "reasoning_effort" not in cap.payload

    async def test_invalid_reasoning_effort_falls_back(self, monkeypatch):
        cap = _Capture(PLAIN_RESPONSE)
        _patch(monkeypatch, cap)
        await _client(reasoning_effort="turbo").chat([ChatMessage("user", "hi")])
        assert cap.payload["reasoning_effort"] == "medium"

    async def test_max_tokens_override(self, monkeypatch):
        cap = _Capture(PLAIN_RESPONSE)
        _patch(monkeypatch, cap)
        await _client().chat([ChatMessage("user", "hi")], max_tokens=128)
        assert cap.payload["max_tokens"] == 128

    async def test_per_call_default_is_not_the_model_ceiling(self, monkeypatch):
        """The routine default must stay small.

        Setting the per-call default to the model's 48K ceiling makes every
        ordinary agent turn generate tens of thousands of tokens; a run then
        stalls instead of failing, which is far harder to diagnose. This was hit
        for real during the first end-to-end probe.
        """
        cap = _Capture(PLAIN_RESPONSE)
        _patch(monkeypatch, cap)
        await _client(max_tokens=800, max_output_ceiling=48000).chat(
            [ChatMessage("user", "hi")]
        )
        assert cap.payload["max_tokens"] == 800

    async def test_request_above_ceiling_fails_locally(self, monkeypatch):
        """Exceeding the declared ceiling must fail here, not at the provider."""
        cap = _Capture(PLAIN_RESPONSE)
        _patch(monkeypatch, cap)
        with pytest.raises(ValueError, match="exceeds the model"):
            await _client(max_output_ceiling=4096).chat(
                [ChatMessage("user", "hi")], max_tokens=99_999
            )
        assert cap.payload is None, "an over-ceiling request still went out"

    async def test_request_at_ceiling_is_allowed(self, monkeypatch):
        cap = _Capture(PLAIN_RESPONSE)
        _patch(monkeypatch, cap)
        await _client(max_output_ceiling=48000).chat(
            [ChatMessage("user", "hi")], max_tokens=48000
        )
        assert cap.payload["max_tokens"] == 48000

    async def test_tool_result_message_round_trip(self, monkeypatch):
        """A tool-role message must carry tool_call_id, and no null tool_calls."""
        cap = _Capture(PLAIN_RESPONSE)
        _patch(monkeypatch, cap)
        history = [
            ChatMessage("user", "weather in Beijing?"),
            ChatMessage(
                "assistant",
                "",
                tool_calls=[
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city":"Beijing"}',
                        },
                    }
                ],
            ),
            ChatMessage("tool", '{"temp_c": 21}', tool_call_id="call_abc",
                        name="get_weather"),
        ]
        await _client().chat(history)
        msgs = cap.payload["messages"]
        assert "tool_calls" not in msgs[0], "null tool_calls leaked onto a user message"
        assert msgs[1]["tool_calls"][0]["id"] == "call_abc"
        assert msgs[2]["tool_call_id"] == "call_abc"
        assert msgs[2]["name"] == "get_weather"


class TestResponseParsing:
    async def test_tool_calls_are_parsed(self, monkeypatch):
        cap = _Capture(TOOL_RESPONSE)
        _patch(monkeypatch, cap)
        res = await _client().chat([ChatMessage("user", "weather?")],
                                   tools=[WEATHER_TOOL])
        assert res.requested_tools
        assert len(res.tool_calls) == 1
        call = res.tool_calls[0]
        assert call.name == "get_weather"
        assert call.call_id == "call_abc"
        assert call.arguments == {"city": "Beijing"}
        assert call.arguments_valid
        assert res.finish_reason == "tool_calls"

    async def test_reasoning_content_is_captured_separately(self, monkeypatch):
        cap = _Capture(THINKING_RESPONSE)
        _patch(monkeypatch, cap)
        res = await _client().chat([ChatMessage("user", "17*23?")])
        assert res.content == "391"
        assert "391" in res.reasoning_content
        assert res.usage.reasoning_tokens == 56

    async def test_usage_is_parsed(self, monkeypatch):
        cap = _Capture(PLAIN_RESPONSE)
        _patch(monkeypatch, cap)
        res = await _client().chat([ChatMessage("user", "hi")])
        assert res.usage.prompt_tokens == 9
        assert res.usage.total_tokens == 11

    def test_malformed_tool_arguments_are_visible_not_silently_empty(self):
        """A model emitting invalid JSON must be detectable.

        Returning {} for both "no arguments" and "unparseable" would hide a
        malformed-output failure mode.
        """
        bad = ToolCall(call_id="c", name="f", arguments_raw="{not json")
        assert bad.arguments == {}
        assert bad.arguments_valid is False

        empty = ToolCall(call_id="c", name="f", arguments_raw="{}")
        assert empty.arguments == {}
        assert empty.arguments_valid is True

    def test_non_object_tool_arguments_are_invalid(self):
        arr = ToolCall(call_id="c", name="f", arguments_raw="[1,2]")
        assert arr.arguments == {}
        assert arr.arguments_valid is False

    def test_usage_from_wire_tolerates_missing_fields(self):
        assert TokenUsage.from_wire(None) == TokenUsage()
        assert TokenUsage.from_wire({"prompt_tokens": 5}).prompt_tokens == 5


class TestDisabledClient:
    async def test_disabled_client_does_not_call_out(self):
        res = await MiMoClient(
            api_key="", base_url="https://example.invalid/v1", enabled=False
        ).chat([ChatMessage("user", "hello")])
        assert res.provider == "disabled"
        assert res.tool_calls == []
        assert res.latency_ms == 0

    async def test_missing_key_disables_even_when_enabled(self):
        res = await MiMoClient(
            api_key="", base_url="https://example.invalid/v1", enabled=True
        ).chat([ChatMessage("user", "hello")])
        assert res.provider == "disabled"


class TestSettingsWiring:
    def test_env_capabilities_reach_the_client(self, monkeypatch):
        from app.core.config import Settings

        monkeypatch.setenv("MIMO_API_KEY", "k")
        monkeypatch.setenv("MIMO_MODEL", "Deepseek-v4-flash")
        monkeypatch.setenv("MIMO_BASE_URL", "https://chatapi.weixin.qq.com/openai/v1")
        monkeypatch.setenv("LLM_ENABLED", "true")
        monkeypatch.setenv("LLM_MAX_TOKENS", "800")
        monkeypatch.setenv("LLM_MAX_OUTPUT_CEILING", "48000")
        monkeypatch.setenv("LLM_MAX_INPUT_TOKENS", "200000")
        monkeypatch.setenv("LLM_TOOL_CALLING_ENABLED", "true")
        monkeypatch.setenv("LLM_THINKING_ENABLED", "true")

        s = Settings(_env_file=None)
        client = MiMoClient(s)
        assert client.model == "Deepseek-v4-flash"
        assert client.max_tokens == 800
        assert client.max_output_ceiling == 48_000
        assert client.max_input_tokens == 200_000
        assert client.tool_calling_enabled is True
        assert client.thinking_enabled is True
        assert client.llm_ready is True
        assert client._endpoint.endswith("/chat/completions")


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
    reason="live endpoint test; set RUN_LIVE_LLM_TESTS=1 to run",
)
class TestLiveEndpoint:
    async def test_live_tool_call_and_thinking(self):
        from app.core.config import Settings

        client = MiMoClient(Settings())
        assert client.llm_ready, "configure .env before running live tests"

        res = await client.chat(
            [ChatMessage("user", "What is the weather in Beijing? Use the tool.")],
            tools=[WEATHER_TOOL],
        )
        assert res.requested_tools, "endpoint did not return a tool call"
        assert res.tool_calls[0].name == "get_weather"
        assert res.tool_calls[0].arguments_valid

        res2 = await client.chat(
            [ChatMessage("user", "What is 17*23? Think first.")], max_tokens=512
        )
        assert res2.usage.reasoning_tokens > 0, "thinking mode did not engage"
