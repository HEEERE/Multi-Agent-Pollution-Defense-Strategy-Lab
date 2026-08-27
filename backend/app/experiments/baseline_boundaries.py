"""Frozen non-RAISE boundary strategies for the formal E-layer baselines."""

from __future__ import annotations

import time

from app.provenance.models import ArtifactState
from app.state.boundary_repair import (
    BoundaryOutcome,
    CONTAMINATION_REASONS,
    TERMINAL_STATES,
)


class BaselineBoundaryStrategy:
    """A small, auditable strategy adapter with the BoundaryRepair contract."""

    def __init__(self, mode: str, context) -> None:
        self.mode = mode
        self.context = context
        self.outcomes: list[BoundaryOutcome] = []

    async def at_boundary(self, request, reason_code: str):
        if reason_code not in CONTAMINATION_REASONS:
            return None
        sinks = frozenset(
            ref for argument in request.arguments for ref in argument.artifact_refs
        )
        if not sinks:
            return None

        started = time.perf_counter()
        controller = self.context.state_controller
        ledger = self.context.ledger
        artifacts = ledger.list_artifacts(request.run_id)
        active = {
            item.version_id for item in artifacts
            if ledger.current_state(item.version_id) not in TERMINAL_STATES
        }
        conservative, _ = controller.graphs()
        reachable = set().union(*(
            conservative.ancestors(sink) | {sink} for sink in sinks
        ))

        if self.mode == "full_reset":
            selected = active
            stages = ("detect", "reset_all")
        elif self.mode == "naive_compose":
            selected = {
                version_id for version_id in active
                if ledger.has_low_integrity_ancestor(version_id)
            }
            stages = ("detect", "rollback_all_tainted", "full_replay")
        elif self.mode == "conservative":
            selected = active & reachable
            stages = ("conservative_witness_cover", "selective_replay")
        else:
            raise ValueError(f"unsupported baseline boundary mode: {self.mode}")

        invalidated: set[str] = set()
        with ledger.atomic():
            for version_id in sorted(selected):
                if ledger.current_state(version_id) in TERMINAL_STATES:
                    continue
                controller.apply_state(
                    version_id, ArtifactState.INVALIDATED,
                    f"baseline:{self.mode}", request.action_id,
                )
                invalidated.add(version_id)

        scopes = frozenset()
        if invalidated and self.context.boundary_queue is not None:
            scopes = self.context.boundary_queue.affected_scopes(request)
            await self.context.boundary_queue.invalidate_scopes(set(scopes))

        elapsed_ms = (time.perf_counter() - started) * 1000
        c_op = float(len(invalidated))
        l_task = float(len({item.artifact_id for item in artifacts if item.version_id in invalidated}))
        c_replay = float(self.mode in {"naive_compose", "conservative"})
        ledger.increment_metric(request.run_id, "boundary_repairs")
        ledger.increment_metric(request.run_id, "requeue_count", float(len(scopes)))
        ledger.increment_metric(request.run_id, "solver_latency_ms", elapsed_ms)
        ledger.increment_metric(request.run_id, "c_op", c_op)
        ledger.increment_metric(request.run_id, "l_task", l_task)
        ledger.increment_metric(request.run_id, "c_replay", c_replay)
        ledger.increment_metric(request.run_id, f"baseline_stage_count:{self.mode}", float(len(stages)))

        outcome = BoundaryOutcome(
            run_id=request.run_id,
            action_id=request.action_id,
            reason_code=reason_code,
            sink_versions=sinks,
            invalidated=frozenset(invalidated),
            plan_status="COVERED",
            scopes=frozenset(scopes),
            witnesses=int(bool(reachable)),
            exhaustive=True,
            c_op=c_op,
            l_task=l_task,
            c_replay=c_replay,
            solver_latency_ms=elapsed_ms,
        )
        self.outcomes.append(outcome)

        if self.mode in {"naive_compose", "conservative"}:
            try:
                await self.context.recovery_coordinator.at_boundary(outcome, request)
            except Exception:
                ledger.increment_metric(request.run_id, "recovery_failures")
                ledger.increment_metric(request.run_id, "unknown_count")
        return outcome


def build_boundary_strategy(mode: str, context) -> BaselineBoundaryStrategy:
    if mode not in {"full_reset", "naive_compose", "conservative"}:
        raise ValueError(f"unsupported baseline boundary mode: {mode}")
    return BaselineBoundaryStrategy(mode, context)
