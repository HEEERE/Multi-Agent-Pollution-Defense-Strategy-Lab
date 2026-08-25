"""Selective, version-creating recovery after an asymmetric boundary repair."""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import uuid4

from app.actions import ActionArgument, ActionRequest, EffectClass, SecurityDecision
from app.provenance.models import ArtifactKind, ArtifactState, TaintClass


@dataclass(frozen=True)
class RecoveryOutcome:
    run_id: str
    action_id: str
    required_goals: frozenset[str]
    replayed_versions: tuple[str, ...]
    success: bool
    recontamination: int
    residual_status: str
    residual_versions: frozenset[str]
    time_to_recovery_ms: float
    failure_reasons: tuple[str, ...] = ()


class RecoveryCoordinator:
    """Rebuild unsupported goals from clean inputs through the action boundary."""

    def __init__(self, context) -> None:
        self.context = context
        self.outcomes: list[RecoveryOutcome] = []

    async def at_boundary(self, boundary_outcome, request) -> RecoveryOutcome:
        return await self._replay_after_applied_repair(
            action_id=request.action_id,
            sink_versions=set(boundary_outcome.sink_versions),
            invalidated=set(boundary_outcome.invalidated) | set(boundary_outcome.demoted),
        )

    async def recover(
        self,
        *,
        sink_versions: set[str],
        revoked_versions: set[str],
        required_goals: set[str] | None = None,
        action_id: str = "manual_recovery",
    ) -> RecoveryOutcome:
        applied = self.context.state_controller.repair(
            sink_versions=sink_versions,
            revoked_versions=revoked_versions,
            required_goals=None,
            replay=None,
        )
        return await self._replay_after_applied_repair(
            action_id=action_id,
            sink_versions=sink_versions,
            invalidated=set(applied["invalidated"]),
            required_goals=required_goals,
        )

    async def _replay_after_applied_repair(
        self,
        *,
        action_id: str,
        sink_versions: set[str],
        invalidated: set[str],
        required_goals: set[str] | None = None,
    ) -> RecoveryOutcome:
        started = time.perf_counter()
        ledger = self.context.ledger
        run_id = self.context.manifest.run_id
        goals = set(required_goals) if required_goals is not None else self._unsupported_goals()
        classifications = self.context.state_controller.classify(sink_versions)
        clean_inputs = tuple(sorted(
            version_id
            for version_id, taint in classifications.items()
            if taint is TaintClass.CLEAN
            and version_id not in sink_versions
            and ledger.get_artifact(version_id) is not None
            and ledger.get_artifact(version_id).kind is not ArtifactKind.ARGUMENT
            and ledger.current_state(version_id) in {
                ArtifactState.ACTIVE, ArtifactState.RETAINED, ArtifactState.RECOVERED
            }
        ))

        replayed: list[str] = []
        failure_reasons: list[str] = []
        for goal in sorted(goals):
            request = ActionRequest(
                action_id=f"replay_{uuid4().hex[:16]}",
                run_id=run_id,
                actor_agent_id="recovery_coordinator",
                tool_id="recovery",
                operation="replay_goal",
                arguments=(ActionArgument(
                    "payload", {"goal_id": goal}, clean_inputs,
                    semantic_role="content", integrity="high",
                ),),
                effect_class=EffectClass.E1,
                reversible=True,
                idempotency_key=f"{run_id}:replay:{action_id}:{goal}",
            )
            authorized = await self.context.gateway.authorize(request)
            if authorized.decision is not SecurityDecision.ALLOW:
                failure_reasons.append(f"{goal}:{authorized.reason_code}")
                await self.context.gateway.complete_mediated(request, succeeded=False)
                continue
            version = self.context.append_artifact(
                artifact_id=f"recovered_goal:{goal}",
                kind=ArtifactKind.SUMMARY,
                value={"goal_id": goal, "replayed_from": clean_inputs},
                integrity="high",
                origin_principals={"recovery_coordinator"},
                metadata={
                    "replay": True,
                    "goal_id": goal,
                    "source_action_id": action_id,
                    "clean_input_ids": list(clean_inputs),
                },
            )
            parents = [
                artifact for version_id in clean_inputs
                if (artifact := ledger.get_artifact(version_id)) is not None
            ]
            if parents:
                self.context.derive(
                    version, parents, activity_id=request.action_id,
                    relation_type="selective_replay", effect_class="E1",
                )
            await self.context.gateway.complete_mediated(request, succeeded=True)
            replayed.append(version.version_id)

        check = self.context.state_controller.runtime_check(
            sink_versions=sink_versions,
            blocked_versions=invalidated,
        )
        residual_versions = frozenset(
            version_id for witness in check.witnesses
            for version_id in witness.low_integrity_versions
        )
        recontamination = sum(
            1 for version_id in replayed if ledger.has_low_integrity_ancestor(version_id)
        )
        success = (
            check.status == "COVERED"
            and check.exhaustive
            and recontamination == 0
            and len(replayed) == len(goals)
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        ledger.increment_metric(run_id, "recovery_attempts")
        ledger.increment_metric(run_id, "recovery_success", float(success))
        ledger.increment_metric(run_id, "replayed_goals", float(len(replayed)))
        ledger.increment_metric(run_id, "recontamination", float(recontamination))
        ledger.increment_metric(run_id, "time_to_recovery_ms", elapsed_ms)
        ledger.increment_metric(run_id, "checker_latency_ms", elapsed_ms)
        outcome = RecoveryOutcome(
            run_id=run_id,
            action_id=action_id,
            required_goals=frozenset(goals),
            replayed_versions=tuple(replayed),
            success=success,
            recontamination=recontamination,
            residual_status=check.status,
            residual_versions=residual_versions,
            time_to_recovery_ms=elapsed_ms,
            failure_reasons=tuple(failure_reasons),
        )
        self.outcomes.append(outcome)
        return outcome

    def _unsupported_goals(self) -> set[str]:
        ledger = self.context.ledger
        run_id = self.context.manifest.run_id
        groups = ledger.list_support_groups(run_id)
        goals = {group.goal_id for group in groups}
        supported = {
            group.goal_id
            for group in groups
            if group.verified
            and all(
                ledger.get_artifact(member) is not None
                and ledger.current_state(member) in {
                    ArtifactState.ACTIVE, ArtifactState.RETAINED, ArtifactState.RECOVERED
                }
                and not ledger.has_low_integrity_ancestor(member)
                for member in group.member_version_ids
            )
        }
        return goals - supported
