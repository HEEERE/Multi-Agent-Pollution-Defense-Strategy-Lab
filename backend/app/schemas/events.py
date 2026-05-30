from dataclasses import dataclass
from time import time
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import (
    ActionTaken,
    EventSeverity,
    EventStatus,
    EventType,
    MonitorLevel,
    new_id,
    new_trace_id,
)


# ── Event spec (template for playbooks) ────────────────────────

@dataclass(frozen=True)
class EventSpec:
    event_type: EventType
    source_node: str
    target_node: str
    payload_snippet: str
    status: EventStatus
    action_taken: ActionTaken


# ── Core event model ─────────────────────────────────────────

class AgentEvent(BaseModel):
    event_id: str = Field(default_factory=new_id)
    trace_id: str = Field(default_factory=new_trace_id)
    parent_event_id: str | None = None
    timestamp: float = Field(default_factory=time)
    event_type: EventType
    source_node: str
    target_node: str
    payload_snippet: str
    status: EventStatus = EventStatus.SAFE
    action_taken: ActionTaken = ActionTaken.NONE
    severity: EventSeverity = EventSeverity.INFO
    monitor_level: MonitorLevel = MonitorLevel.NONE
    metadata: dict[str, Any] = Field(default_factory=dict)
    # ── v2 fields (additive, backward-compatible) ──
    event_category: str | None = None
    risk_tags: list[str] = Field(default_factory=list)
    trust_level: str = "unknown"  # trusted | untrusted | unknown
    contamination_score: float = 0.0
    policy_decision: str | None = None
    policy_id: str | None = None
    edge_kind: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
