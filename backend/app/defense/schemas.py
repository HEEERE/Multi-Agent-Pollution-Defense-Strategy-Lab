from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Verdict = Literal["safe", "suspicious", "malicious", "unknown"]
RecommendedAction = Literal[
    "allow",
    "alert",
    "challenge",
    "quarantine",
    "block",
    "isolate",
    "decoy",
    "recover",
]
ConsensusType = Literal[
    "majority",
    "weighted",
    "veto",
    "quorum",
    "fallback",
]


class DefenderVerdict(BaseModel):
    defender_id: str
    role: str
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    recommended_action: RecommendedAction = "allow"
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContainmentPlan(BaseModel):
    infected_nodes: list[str] = Field(default_factory=list)
    suspect_edges: list[str] = Field(default_factory=list)
    quarantine_nodes: list[str] = Field(default_factory=list)
    isolate_tools: list[str] = Field(default_factory=list)
    revoke_memory_keys: list[str] = Field(default_factory=list)
    block_edges: list[tuple[str, str]] = Field(default_factory=list)
    notify_agents: list[str] = Field(default_factory=list)
    recovery_required: bool = False
    rationale: str = ""


class JointDefenseDecision(BaseModel):
    decision_id: str
    source_event_id: str
    trace_id: str
    final_action: RecommendedAction
    confidence: float = Field(ge=0.0, le=1.0)
    votes: list[DefenderVerdict]
    consensus_type: ConsensusType
    containment_plan: ContainmentPlan | None = None
    rationale: str
    metadata: dict[str, Any] = Field(default_factory=dict)
