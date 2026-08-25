from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping
from uuid import uuid4

from app.actions import ActionBoundaryQueue, ActionGateway, DeterministicPolicy
from app.provenance import ProvenanceLedger
from app.provenance.models import ArtifactKind, ArtifactState, ArtifactVersion, Derivation, StateTransition


@dataclass(frozen=True)
class RunBudget:
    """Frozen per-run resource limits recorded before execution starts."""

    llm_calls: int = 30
    tokens: int = 50_000
    solver_ms: int = 1_000
    checker_ms: int = 1_000
    wall_clock_s: int = 300

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"budget.{name} must be a non-negative integer")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RunBudget":
        return cls(**{key: int(item) for key, item in dict(value or {}).items()})


@dataclass(frozen=True)
class RunManifest:
    """Immutable, serialisable contract for one experimental run.

    Minimal construction remains available for legacy/unit-test callers.  A
    formal harness must additionally call :meth:`validate_formal`, which rejects
    placeholders and incomplete reproducibility metadata before any action can
    execute.
    """

    run_id: str
    schema_version: str = "majd-run-v1"
    experiment_id: str = "legacy"
    layer: str = "E"
    task_id: str = "legacy-task"
    attack_id: str | None = None
    benign_control_id: str | None = None
    method_id: str = "raise_asymmetric_v1"
    topology: dict[str, Any] | str = "default"
    seed: int = 0
    model_role_assignment: dict[str, str] = field(default_factory=dict)
    prompt_hashes: dict[str, str] = field(default_factory=dict)
    tool_schema_hash: str = ""
    policy_version: str = "v1"
    component_versions: dict[str, str] = field(default_factory=dict)
    commit: str = ""
    environment_lock_hash: str = ""
    effect_mode: str = "live"
    provenance_mode: str = "P1_conservative"
    horizon_closure: str = "closed"
    sink_set: tuple[str, ...] = ()
    support_groups: tuple[dict[str, Any], ...] = ()
    budget: RunBudget = field(default_factory=RunBudget)

    def __post_init__(self) -> None:
        if not self.run_id or not self.run_id.strip():
            raise ValueError("run_id must be non-empty")
        if self.schema_version != "majd-run-v1":
            raise ValueError("unsupported manifest schema_version")
        if self.layer not in {"M", "E", "X"}:
            raise ValueError("layer must be one of M, E, X")
        if self.effect_mode not in {"live", "dry_run"}:
            raise ValueError("effect_mode must be live or dry_run")
        if self.horizon_closure not in {"closed", "open"}:
            raise ValueError("horizon_closure must be closed or open")
        if self.provenance_mode not in {"P0_tight", "P1_conservative", "dual"}:
            raise ValueError("unsupported provenance_mode")
        if not isinstance(self.budget, RunBudget):
            object.__setattr__(self, "budget", RunBudget.from_mapping(self.budget))
        object.__setattr__(self, "sink_set", tuple(self.sink_set))
        object.__setattr__(self, "support_groups", tuple(dict(item) for item in self.support_groups))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RunManifest":
        data = cls.migrate_mapping(value)
        data["budget"] = RunBudget.from_mapping(data.get("budget"))
        data["sink_set"] = tuple(data.get("sink_set") or ())
        data["support_groups"] = tuple(data.get("support_groups") or ())
        try:
            return cls(**data)
        except TypeError as exc:
            raise ValueError(f"invalid run manifest fields: {exc}") from exc

    @classmethod
    def migrate_mapping(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        """Upgrade the additive legacy manifest vocabulary to v1.

        Older API/strategy callers used a handful of singular or abbreviated
        keys and omitted ``schema_version``.  The migration is deliberately
        explicit: it preserves those callers without silently accepting an
        unknown future schema.
        """
        data = dict(value)
        version = str(data.pop("version", data.get("schema_version", "majd-run-v1")))
        if version in {"legacy", "v0", "majd-run-v0"}:
            data["schema_version"] = "majd-run-v1"
        elif version != "majd-run-v1":
            raise ValueError(f"unsupported manifest schema_version: {version}")

        aliases = {
            "control_id": "benign_control_id",
            "model_assignments": "model_role_assignment",
            "tool_hash": "tool_schema_hash",
            "git_commit": "commit",
            "dependency_lock_hash": "environment_lock_hash",
            "sink_ids": "sink_set",
            "horizon": "horizon_closure",
        }
        for old, new in aliases.items():
            if old in data and new not in data:
                data[new] = data.pop(old)

        if "prompt_hash" in data and "prompt_hashes" not in data:
            data["prompt_hashes"] = {"default": str(data.pop("prompt_hash"))}
        return data

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate_formal(self) -> None:
        required = {
            "experiment_id": self.experiment_id,
            "task_id": self.task_id,
            "method_id": self.method_id,
            "tool_schema_hash": self.tool_schema_hash,
            "commit": self.commit,
            "environment_lock_hash": self.environment_lock_hash,
        }
        missing = sorted(
            name for name, value in required.items()
            if not value or str(value).startswith("legacy")
        )
        if not self.model_role_assignment:
            missing.append("model_role_assignment")
        if not self.prompt_hashes:
            missing.append("prompt_hashes")
        if not self.component_versions:
            missing.append("component_versions")
        if not self.topology or self.topology == "default":
            missing.append("topology")
        if not self.sink_set:
            missing.append("sink_set")
        if self.layer in {"E", "X"} and not (
            self.attack_id or self.benign_control_id
        ):
            missing.append("attack_id|benign_control_id")
        if self.attack_id and self.benign_control_id:
            raise ValueError(
                "formal manifest must describe one condition: attack_id and "
                "benign_control_id are mutually exclusive"
            )
        if missing:
            raise ValueError(
                "formal manifest is incomplete: " + ", ".join(sorted(set(missing)))
            )
        invalid_hashes = []
        if not _is_sha256(self.tool_schema_hash):
            invalid_hashes.append("tool_schema_hash")
        if not _is_sha256(self.environment_lock_hash):
            invalid_hashes.append("environment_lock_hash")
        invalid_hashes.extend(
            f"prompt_hashes.{role}"
            for role, digest in self.prompt_hashes.items()
            if not _is_sha256(digest)
        )
        if invalid_hashes:
            raise ValueError(
                "formal manifest requires exact sha256 hashes: "
                + ", ".join(sorted(invalid_hashes))
            )
        if not (
            7 <= len(self.commit) <= 64
            and all(character in "0123456789abcdefABCDEF" for character in self.commit)
        ):
            raise ValueError("formal manifest commit must be an exact hexadecimal revision")


def _is_sha256(value: str) -> bool:
    text = str(value)
    if not text.startswith("sha256:"):
        return False
    digest = text.removeprefix("sha256:")
    return len(digest) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in digest
    )


@dataclass
class RunContext:
    manifest: RunManifest
    ledger: ProvenanceLedger
    gateway: ActionGateway
    state_controller: object | None = None
    boundary_queue: ActionBoundaryQueue | None = None
    effect_sandbox: object | None = None
    recovery_coordinator: object | None = None
    created_at: float = field(default_factory=time.time)

    def append_artifact(self, *, artifact_id: str, kind: ArtifactKind, value: object, integrity: str = "unknown", origin_principals: set[str] | None = None, metadata: dict | None = None) -> ArtifactVersion:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
        version = ArtifactVersion(f"av_{uuid4().hex[:16]}", artifact_id, self.manifest.run_id, kind, hashlib.sha256(raw).hexdigest(), frozenset(origin_principals or set()), integrity, metadata=metadata or {})
        return self.ledger.append_artifact(version)

    def derive(self, child: ArtifactVersion, parents: list[ArtifactVersion], *, activity_id: str, relation_type: str = "derived_from", effect_class: str = "E0") -> Derivation:
        derivation = Derivation(f"rel_{uuid4().hex[:16]}", self.manifest.run_id, child.version_id, tuple(p.version_id for p in parents), activity_id, relation_type, effect_class=effect_class)
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

    def create_run(self, manifest: RunManifest, *, effect_mode: str | None = None, policy: DeterministicPolicy | None = None) -> RunContext:
        if manifest.run_id in self._contexts:
            raise ValueError(f"run already exists: {manifest.run_id}")
        selected_effect_mode = effect_mode or manifest.effect_mode
        if selected_effect_mode != manifest.effect_mode:
            raise ValueError("runtime effect_mode disagrees with immutable manifest")
        self.ledger.ensure_run(manifest.run_id, manifest.policy_version)
        queue = ActionBoundaryQueue(self.ledger)
        from app.state.boundary_repair import BoundaryRepair
        boundary_repair = BoundaryRepair(
            self.ledger, horizon_closure=manifest.horizon_closure, boundary_queue=queue
        )
        gateway = ActionGateway(
            self.ledger, policy=policy, effect_mode=selected_effect_mode, boundary_queue=queue,
            boundary_repair=boundary_repair,
        )
        from app.state import StateController
        from app.sandbox import SideEffectSandbox
        context = RunContext(
            manifest=manifest,
            ledger=self.ledger,
            gateway=gateway,
            state_controller=StateController(self.ledger, manifest.run_id),
            boundary_queue=queue,
            effect_sandbox=SideEffectSandbox(manifest.run_id),
        )
        from app.recovery import RecoveryCoordinator
        context.recovery_coordinator = RecoveryCoordinator(context)
        boundary_repair.bind_recovery(context.recovery_coordinator.at_boundary)
        self._contexts[manifest.run_id] = context
        self._queues[manifest.run_id] = asyncio.Lock()
        return context

    def get_run(self, run_id: str) -> RunContext:
        return self._contexts[run_id]

    async def at_action_boundary(self, run_id: str, operation):
        lock = self._queues[run_id]
        async with lock:
            return await operation()
