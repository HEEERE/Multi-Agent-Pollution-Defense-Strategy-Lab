from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable


class EffectClass(StrEnum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"


class SecurityDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    QUARANTINE = "quarantine"
    REQUIRE_APPROVAL = "require_approval"
    UNKNOWN = "unknown"
    OBSERVE = "observe"


class ScopeLevel(StrEnum):
    RUN = "run"
    PLATFORM = "platform"


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_type: str
    source: str
    outcome: str
    deterministic: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def vetoes(self) -> bool:
        return self.outcome in {"deny", "hold", "quarantine", "unknown"}


@dataclass(frozen=True)
class ArgumentContract:
    name: str
    semantic_role: str
    allowed_origins: frozenset[str] = frozenset()
    required_integrity: str = "unknown"
    required: bool = True


@dataclass(frozen=True)
class ActionContract:
    tool_id: str
    operation: str
    effect_class: EffectClass
    arguments: tuple[ArgumentContract, ...] = ()
    required_capabilities: frozenset[str] = frozenset()
    allowed_resource_scopes: frozenset[str] = frozenset({"default"})
    reversible: bool = True
    allow_unbound_e0: bool = True


@dataclass(frozen=True)
class ActionArgument:
    name: str
    value: Any = None
    artifact_refs: tuple[str, ...] = ()
    semantic_role: str = "content"
    integrity: str = "unknown"


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    run_id: str
    actor_agent_id: str
    tool_id: str
    operation: str
    arguments: tuple[ActionArgument, ...] = ()
    capability_requested: frozenset[str] = frozenset()
    resource_scope: str = "default"
    effect_class: EffectClass = EffectClass.E0
    idempotency_key: str = ""
    reversible: bool = True
    deadline: float | None = None
    scope_level: ScopeLevel = ScopeLevel.RUN
    approval_id: str | None = None
    model_evidence: tuple[EvidenceRecord, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    decision: SecurityDecision
    executed: bool
    value: Any = None
    reason_code: str = ""
    snapshot_hash: str | None = None
    authority_eligible: bool = True
    simulated_effect: bool = False
    public_reason: str | None = None


Handler = Callable[[ActionRequest], Awaitable[Any]]
