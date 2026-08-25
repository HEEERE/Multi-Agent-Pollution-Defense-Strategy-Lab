from __future__ import annotations

from dataclasses import dataclass, field
import time

from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import ArtifactState
from app.state.controller import StateController

# Denials that mean "contamination reached this action's arguments". Only these
# call for repair; the other reason codes (missing capability, expired artifact,
# retained version reaching for E2/E3 authority) are not contamination findings
# and repairing on them would churn state for nothing.
CONTAMINATION_REASONS = frozenset({"contaminated_provenance", "low_integrity_e3_argument"})

TERMINAL_STATES = frozenset({ArtifactState.INVALIDATED, ArtifactState.QUARANTINED})


@dataclass(frozen=True)
class BoundaryOutcome:
    """What the repair did at one action boundary."""

    run_id: str
    action_id: str
    reason_code: str
    sink_versions: frozenset[str] = frozenset()
    demoted: frozenset[str] = frozenset()
    invalidated: frozenset[str] = frozenset()
    retained: frozenset[str] = frozenset()
    vetoed: frozenset[str] = frozenset()
    certificate_issued: bool = False
    plan_status: str = "SKIPPED"
    scopes: frozenset[str] = frozenset()
    witnesses: int = 0
    exhaustive: bool = True
    c_op: float = 0.0
    l_task: float = 0.0
    c_replay: float = 0.0
    c_human: float = 0.0
    objective_j: float = 0.0
    solver_latency_ms: float = 0.0


class BoundaryRepair:
    """Invoke the asymmetric repair mechanism at the action boundary (v4 §8.4).

    The gateway denies a contaminated action, which is the moment the run learns
    something new about reachability. v4 requires three things to happen here and
    nowhere else:

    * §5.3 定理 5 only holds for a frozen ``Q_sigma``, so every previously
      retained version must be re-adjudicated against the new sink set;
    * §3.7 then repairs: revoke what the conservative graph says reaches a sink,
      and let the tight graph propose the ``contaminated_unreachable`` remainder
      for retention under conservative veto;
    * §8.4 rule 5 requeues every pending action in the affected scope, because
      their earlier adjudication used the pre-intervention scope.
    """

    def __init__(self, ledger: ProvenanceLedger, *, horizon_closure: str = "closed",
                 boundary_queue=None) -> None:
        if horizon_closure not in {"closed", "open"}:
            raise ValueError("horizon_closure must be closed or open")
        self._ledger = ledger
        self._horizon_closure = horizon_closure
        self._boundary_queue = boundary_queue
        self._recovery_handler = None
        self.outcomes: list[BoundaryOutcome] = []

    def bind_recovery(self, handler) -> None:
        self._recovery_handler = handler

    async def at_boundary(self, request, reason_code: str) -> BoundaryOutcome | None:
        """Repair after a contamination denial. Returns ``None`` if not applicable."""
        if reason_code not in CONTAMINATION_REASONS:
            return None
        sinks = frozenset(ref for argument in request.arguments for ref in argument.artifact_refs)
        if not sinks:
            return None

        controller = StateController(self._ledger, request.run_id)
        demoted = controller.recheck_retained(self._retained_versions(request.run_id), set(sinks))

        solver_started = time.perf_counter()
        plan = controller.plan_repair(sink_versions=set(sinks))
        solver_latency_ms = (time.perf_counter() - solver_started) * 1000
        invalidated = self._invalidate(controller, plan.invalidate)

        retained: frozenset[str] = frozenset()
        vetoed: frozenset[str] = frozenset()
        certificate_issued = False
        # A version the plan revoked, or one an earlier boundary already ended,
        # is not a retention candidate; retention only moves out of ACTIVE.
        candidates = {
            version_id for version_id in plan.retain
            if self._ledger.current_state(version_id) not in TERMINAL_STATES
        } - set(plan.invalidate)
        if candidates:
            result = controller.certify_and_retain(
                sink_versions=set(sinks),
                blocked_versions=set(plan.invalidate) | set(invalidated),
                candidate_versions=candidates,
                horizon_closure=self._horizon_closure,
            )
            retained, vetoed = result.retained, result.vetoed
            certificate_issued = bool(result.retained)

        scopes = await self._requeue(request, demoted or invalidated or retained)
        self._ledger.increment_metric(request.run_id, "requeue_count", float(len(scopes)))
        self._ledger.increment_metric(request.run_id, "boundary_repairs")
        self._ledger.increment_metric(request.run_id, "solver_latency_ms", solver_latency_ms)
        self._ledger.increment_metric(request.run_id, "c_op", plan.cost.op_cost)
        self._ledger.increment_metric(request.run_id, "l_task", plan.cost.task_loss)
        self._ledger.increment_metric(request.run_id, "c_replay", plan.cost.replay_cost)
        self._ledger.increment_metric(request.run_id, "c_human", plan.cost.human_cost)
        self._ledger.increment_metric(request.run_id, "objective_j", plan.cost.j())
        if plan.status == "UNKNOWN":
            self._ledger.increment_metric(request.run_id, "unknown_count")
        if plan.status == "UNSATISFIABLE":
            self._ledger.increment_metric(request.run_id, "unsatisfiable_count")
        outcome = BoundaryOutcome(
            run_id=request.run_id, action_id=request.action_id, reason_code=reason_code,
            sink_versions=sinks, demoted=demoted, invalidated=invalidated,
            retained=retained, vetoed=vetoed, certificate_issued=certificate_issued,
            plan_status=plan.status, scopes=scopes, witnesses=plan.witnesses,
            exhaustive=plan.exhaustive, c_op=plan.cost.op_cost,
            l_task=plan.cost.task_loss, c_replay=plan.cost.replay_cost,
            c_human=plan.cost.human_cost, objective_j=plan.cost.j(),
            solver_latency_ms=solver_latency_ms,
        )
        self.outcomes.append(outcome)
        if self._recovery_handler is not None:
            try:
                await self._recovery_handler(outcome, request)
            except Exception:
                # The denied action stays denied.  Recovery failure is surfaced
                # as an explicit UNKNOWN metric rather than erasing that result.
                self._ledger.increment_metric(request.run_id, "recovery_failures")
                self._ledger.increment_metric(request.run_id, "unknown_count")
        return outcome

    def _retained_versions(self, run_id: str) -> set[str]:
        return {
            artifact.version_id
            for artifact in self._ledger.list_artifacts(run_id)
            if self._ledger.current_state(artifact.version_id) is ArtifactState.RETAINED
        }

    def _invalidate(self, controller: StateController, versions) -> frozenset[str]:
        applied = set()
        with controller.ledger.atomic():
            for version_id in versions:
                if controller.ledger.current_state(version_id) in TERMINAL_STATES:
                    continue
                controller.apply_state(version_id, ArtifactState.INVALIDATED, "boundary_repair_reachable")
                applied.add(version_id)
        return frozenset(applied)

    async def _requeue(self, request, changed) -> frozenset[str]:
        """§8.4 rule 5: pending actions in the affected scope lose their verdict."""
        if not changed or self._boundary_queue is None:
            return frozenset()
        scopes = self._boundary_queue.affected_scopes(request)
        await self._boundary_queue.invalidate_scopes(set(scopes))
        return frozenset(scopes)
