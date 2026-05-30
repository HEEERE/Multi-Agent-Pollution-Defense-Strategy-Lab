from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from app.defense.schemas import DefenderVerdict
from app.schemas import AgentEvent


class DefenseContext(BaseModel):
    detection_log: list[dict] = Field(default_factory=list)
    policy_decision: dict | None = None
    threat_memory: dict = Field(default_factory=dict)
    trace_events: list[AgentEvent] = Field(default_factory=list)
    trace_graph: dict | None = None
    metadata: dict = Field(default_factory=dict)


class BaseDefenderAgent(ABC):
    def __init__(
        self,
        defender_id: str,
        role: str,
        weight: float = 1.0,
        veto_enabled: bool = False,
    ) -> None:
        self.defender_id = defender_id
        self.role = role
        self.weight = weight
        self.veto_enabled = veto_enabled

    @abstractmethod
    async def evaluate(
        self,
        event: AgentEvent,
        context: DefenseContext,
    ) -> DefenderVerdict:
        ...
