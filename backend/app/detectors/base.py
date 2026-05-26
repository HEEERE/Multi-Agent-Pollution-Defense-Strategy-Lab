from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.schemas import ActionTaken, AgentEvent, MonitorLevel


@dataclass
class DetectionResult:
    is_threat: bool
    confidence: float
    reason: str
    suggested_action: ActionTaken = ActionTaken.ALERT
    level: MonitorLevel = MonitorLevel.NONE
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionContext:
    event: AgentEvent
    trace_events: list[AgentEvent] = field(default_factory=list)
    node_states: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseDetector(ABC):
    detector_id: str
    level: MonitorLevel
    action_policy: ActionTaken

    @abstractmethod
    async def detect(self, event: AgentEvent, context: DetectionContext) -> DetectionResult:
        """Analyze event and return detection result."""
        ...
