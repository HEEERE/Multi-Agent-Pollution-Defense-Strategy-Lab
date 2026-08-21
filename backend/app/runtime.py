from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from uuid import uuid4

from app.actions import ActionBoundaryQueue, ActionGateway, DeterministicPolicy
from app.provenance import ProvenanceLedger
from app.provenance.models import ArtifactKind, ArtifactState, ArtifactVersion, Derivation, StateTransition


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    seed: int = 0
    policy_version: str = "v1"
    component_versions: dict[str, str] = field(default_factory=dict)
    provenance_mode: str = "P1_conservative"
    horizon_closure: str = "closed"
    model_role_assignment: dict[str, str] = field(default_factory=dict)


@dataclass
class RunContext:
    manifest: RunManifest
    ledger: ProvenanceLedger
    gateway: ActionGateway
    state_controller: object | None = None
    boundary_queue: ActionBoundaryQueue | None = None
    created_at: float = field(default_factory=time.time)

    def append_artifact(self, *, artifact_id: str, kind: ArtifactKind, value: object, integrity: str = "unknown", origin_principals: set[str] | None = None, metadata: dict | None = None) -> ArtifactVersion:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
        version = ArtifactVersion(f"av_{uuid4().hex[:16]}", artifact_id, self.manifest.run_id, kind, hashlib.sha256(raw).hexdigest(), frozenset(origin_principals or set()), integrity, metadata=metadata or {})
        return self.ledger.append_artifact(version)

    def derive(self, child: ArtifactVersion, parents: list[ArtifactVersion], *, activity_id: str, relation_type: str = "derived_from") -> Derivation:
        derivation = Derivation(f"rel_{uuid4().hex[:16]}", self.manifest.run_id, child.version_id, tuple(p.version_id for p in parents), activity_id, relation_type)
        self.ledger.append_derivation(derivation)
        return derivation

    def transition(self, version: ArtifactVersion, to_state: ArtifactState, reason: str, action_id: str | None = None) -> StateTransition:
        current = self.ledger.current_state(version.version_id) or ArtifactState.ACTIVE
        return self.ledger.transition_state(StateTransition(f"st_{uuid4().hex[:16]}", self.manifest.run_id, version.version_id, current, to_state, 0, reason, action_id))


class RunEngine:
    """Owns one isolated runtime context and serializes action boundaries."""

    def __init__(self, ledger: ProvenanceLedger | None = None) -> None:
        self.ledger = ledger or ProvenanceLedger()
        self._contexts: dict[str, RunContext] = {}
        self._queues: dict[str, asyncio.Lock] = {}

    def create_run(self, manifest: RunManifest, *, effect_mode: str = "live", policy: DeterministicPolicy | None = None) -> RunContext:
        if manifest.run_id in self._contexts:
            raise ValueError(f"run already exists: {manifest.run_id}")
        self.ledger.ensure_run(manifest.run_id, manifest.policy_version)
        queue = ActionBoundaryQueue(self.ledger)
        gateway = ActionGateway(self.ledger, policy=policy, effect_mode=effect_mode, boundary_queue=queue)
        from app.state import StateController
        context = RunContext(manifest, self.ledger, gateway, StateController(self.ledger, manifest.run_id), queue)
        self._contexts[manifest.run_id] = context
        self._queues[manifest.run_id] = asyncio.Lock()
        return context

    def get_run(self, run_id: str) -> RunContext:
        return self._contexts[run_id]

    async def at_action_boundary(self, run_id: str, operation):
        lock = self._queues[run_id]
        async with lock:
            return await operation()
