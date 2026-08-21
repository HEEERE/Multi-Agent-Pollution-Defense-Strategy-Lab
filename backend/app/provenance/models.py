from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ArtifactKind(StrEnum):
    MESSAGE = "message"
    RAG_CHUNK = "rag_chunk"
    MEMORY = "memory"
    SUMMARY = "summary"
    PLAN = "plan"
    TOOL_RESULT = "tool_result"
    ARGUMENT = "argument"
    EXTERNAL_EFFECT = "external_effect"


class ArtifactState(StrEnum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    INVALIDATED = "invalidated"
    RECOVERED = "recovered"
    RETAINED = "retained"


class TaintClass(StrEnum):
    CLEAN = "clean"
    CONTAMINATED_REACHABLE = "contaminated_reachable"
    CONTAMINATED_UNREACHABLE = "contaminated_unreachable"


class ProvenanceLevel(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


@dataclass(frozen=True)
class ArtifactVersion:
    version_id: str
    artifact_id: str
    run_id: str
    kind: ArtifactKind
    value_hash: str
    origin_principals: frozenset[str] = frozenset()
    integrity: str = "unknown"
    confidentiality: str = "internal"
    scope: str = "default"
    expiry: float | None = None
    derivation_ids: tuple[str, ...] = ()
    taint_class: TaintClass = TaintClass.CLEAN
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Derivation:
    relation_id: str
    run_id: str
    child_version_id: str
    parent_version_ids: tuple[str, ...]
    activity_id: str
    relation_type: str = "derived_from"
    parent_roles: tuple[str, ...] = ()
    provenance_level: ProvenanceLevel = ProvenanceLevel.P0
    effect_class: str = "E0"


@dataclass(frozen=True)
class ActivityRecord:
    activity_id: str
    run_id: str
    actor_agent_id: str
    kind: str
    visible_input_ids: tuple[str, ...] = ()
    tool_id: str | None = None
    operation: str | None = None
    effect_class: str = "E0"
    seq: int = 0


@dataclass(frozen=True)
class SupportGroup:
    support_id: str
    run_id: str
    goal_id: str
    member_version_ids: tuple[str, ...]
    verifier_id: str
    verified: bool
    provenance_level: ProvenanceLevel = ProvenanceLevel.P0


@dataclass(frozen=True)
class LabelEnforcementRecord:
    enforcement_id: str
    run_id: str
    version_id: str
    certificate_hash: str
    confidentiality: str
    blocked_effects: tuple[str, ...] = ("E2", "E3")
    seq: int = 0


@dataclass(frozen=True)
class StateTransition:
    transition_id: str
    run_id: str
    version_id: str
    from_state: ArtifactState | None
    to_state: ArtifactState
    seq: int
    reason: str
    action_id: str | None = None


@dataclass(frozen=True)
class ProvenanceSnapshot:
    run_id: str
    ledger_seq: int
    state_seq: int
    policy_version: str
    component_versions: tuple[tuple[str, str], ...]
    snapshot_hash: str
