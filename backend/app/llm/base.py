from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str

    # Tool-calling plumbing. ``tool_calls`` is set on assistant messages that
    # requested a call; ``tool_call_id`` and ``name`` are set on the ``tool``
    # role message carrying the result back.
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_wire(self) -> dict[str, Any]:
        """Serialise to the OpenAI chat-completions message shape.

        Only non-empty optional fields are emitted: some providers reject a
        ``null`` ``tool_calls`` on a plain user message.
        """
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        if self.name:
            out["name"] = self.name
        return out


@dataclass(frozen=True)
class ToolCall:
    """One requested tool invocation."""

    call_id: str
    name: str
    arguments_raw: str
    """Raw JSON string as returned by the model. Kept verbatim so a malformed
    payload is visible to the caller instead of being silently coerced."""

    @property
    def arguments(self) -> dict[str, Any]:
        """Parsed arguments, or ``{}`` when the model emitted invalid JSON.

        Callers that must distinguish "no arguments" from "unparseable" should
        inspect ``arguments_raw`` and ``arguments_valid``.
        """
        import json

        try:
            parsed = json.loads(self.arguments_raw or "{}")
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @property
    def arguments_valid(self) -> bool:
        import json

        try:
            return isinstance(json.loads(self.arguments_raw or "{}"), dict)
        except (ValueError, TypeError):
            return False


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_wire(cls, usage: dict[str, Any] | None) -> "TokenUsage":
        u = usage or {}
        return cls(
            prompt_tokens=int(u.get("prompt_tokens") or 0),
            completion_tokens=int(u.get("completion_tokens") or 0),
            reasoning_tokens=int(u.get("reasoning_tokens") or 0),
            total_tokens=int(u.get("total_tokens") or 0),
        )


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    provider: str
    latency_ms: int

    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str = ""
    """Separated chain of thought, when the provider returns one.

    Treated as untrusted model output like ``content``: it is recorded for
    analysis and never used as an authorisation input.
    """
    finish_reason: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)

    @property
    def requested_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMClient(Protocol):
    async def chat(self, messages: list[ChatMessage]) -> LLMResponse:
        raise NotImplementedError
