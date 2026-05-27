from typing import Any

from pydantic import BaseModel, Field


class PolicyCondition(BaseModel):
    event_type: str | None = None
    source_trust_level: str | None = None
    target_node_type: str | None = None
    risk_tags_any: list[str] = Field(default_factory=list)
    min_contamination_score: float | None = None
    metadata_match: dict[str, Any] = Field(default_factory=dict)


class PolicyRule(BaseModel):
    policy_id: str
    name: str
    description: str = ""
    enabled: bool = True
    priority: int = 100
    condition: PolicyCondition
    action: str  # allow | alert | block | quarantine | isolate | human_review
    severity: str = "info"
    reason: str = ""


class PolicyDecision(BaseModel):
    policy_id: str | None = None
    action: str = "allow"
    severity: str = "info"
    reason: str = ""
    matched: bool = False
