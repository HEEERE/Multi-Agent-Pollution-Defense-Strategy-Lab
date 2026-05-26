from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    provider: str
    latency_ms: int


class LLMClient(Protocol):
    async def chat(self, messages: list[ChatMessage]) -> LLMResponse:
        raise NotImplementedError
