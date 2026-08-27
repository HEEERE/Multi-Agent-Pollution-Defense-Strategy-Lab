from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from uuid import uuid4

from app.actions.models import ActionContract, ActionRequest, ActionResult, EffectClass, Handler, SecurityDecision
from app.actions.policy import DeterministicPolicy
from app.actions.queue import ActionBoundaryQueue
from app.actions.security import SecurityKernel
from app.provenance.ledger import ProvenanceLedger


@dataclass(frozen=True)
class GatewayConfig:
    effect_mode: str = "live"
    constant_denial_delay_ms: int = 25
    denial_budget_charge: int = 1
    probing_quarantine_threshold: int = 5


class ActionGateway:
    """The sole authorization and execution boundary for protected effects."""

    def __init__(self, ledger: ProvenanceLedger, *, policy: DeterministicPolicy | None = None,
                 effect_mode: str = "live", config: GatewayConfig | None = None,
                 security_kernel: SecurityKernel | None = None,
                 boundary_queue: ActionBoundaryQueue | None = None,
                 boundary_repair=None) -> None:
        config = config or GatewayConfig(effect_mode=effect_mode)
        if effect_mode != config.effect_mode:
            raise ValueError("effect_mode and config.effect_mode disagree")
        if effect_mode not in {"live", "dry_run"}:
            raise ValueError("effect_mode must be live or dry_run")
        self._ledger = ledger
        self._policy = policy or DeterministicPolicy()
        self._effect_mode = effect_mode
        self._config = config
        self._security_kernel = security_kernel or SecurityKernel()
        self._boundary_queue = boundary_queue or ActionBoundaryQueue(ledger)
        # Injected rather than imported: the gateway must not depend on the state
        # authority, and v4 §11.1 keeps that direction one-way. ``RunEngine``
        # supplies it because only the run knows its ``horizon_closure``.
        self._boundary_repair = boundary_repair
        self._handlers: dict[tuple[str, str], Handler] = {}
        self._denial_counts: dict[str, int] = {}

    @property
    def effect_mode(self) -> str:
        return self._effect_mode

    @property
    def boundary_queue(self) -> ActionBoundaryQueue:
        return self._boundary_queue

    @property
    def boundary_repair(self):
        return self._boundary_repair

    def bind_boundary_repair(self, boundary_repair) -> None:
        """Select the frozen per-method boundary strategy before execution.

        ``RunEngine`` installs the RAISE asymmetric strategy by default. Formal
        baseline adapters may replace it during ``prepare``; doing this through
        an explicit method keeps method selection out of policy internals.
        """
        self._boundary_repair = boundary_repair

    def has_handler(self, tool_id: str, operation: str) -> bool:
        return (tool_id, operation) in self._handlers

    def register(self, tool_id: str, operation: str, handler: Handler) -> None:
        self._handlers[(tool_id, operation)] = handler

    def register_contract(self, contract: ActionContract) -> None:
        self._policy.register_contract(contract)

    @staticmethod
    def request_hash(request: ActionRequest) -> str:
        material = json.dumps(asdict(request), sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(material.encode()).hexdigest()

    async def authorize(self, request: ActionRequest) -> ActionResult:
        started = time.perf_counter()
        normalized = self._security_kernel.normalize(request)
        evidence = await self._security_kernel.collect(normalized)
        normalized = normalized.__class__(
            normalized.action_id, normalized.run_id, normalized.actor_agent_id,
            normalized.tool_id, normalized.operation, normalized.arguments,
            normalized.capability_requested, normalized.resource_scope,
            normalized.effect_class, normalized.idempotency_key, normalized.reversible,
            normalized.deadline, normalized.scope_level, normalized.approval_id, evidence,
        )
        self._ledger.ensure_run(normalized.run_id)
        request_hash = self.request_hash(normalized)
        if not self._ledger.has_action_lifecycle(normalized.run_id, normalized.action_id, "proposed"):
            self._ledger.record_action(action_id=normalized.action_id, run_id=normalized.run_id,
                                       lifecycle="proposed", request_hash=request_hash,
                                       effect_class=normalized.effect_class.value,
                                       resource_scope=normalized.resource_scope,
                                       idempotency_key=normalized.idempotency_key)
        for item in evidence:
            self._ledger.record_evidence(record_id=f"ev_{uuid4().hex}", run_id=normalized.run_id,
                                         action_id=normalized.action_id,
                                         evidence_type=item.evidence_type, source=item.source,
                                         outcome=item.outcome, details=item.details)
        if self._effect_mode == "dry_run" and normalized.effect_class in {EffectClass.E2, EffectClass.E3}:
            self._ledger.record_action(action_id=normalized.action_id, run_id=normalized.run_id,
                                       lifecycle="simulated_effect", request_hash=request_hash,
                                       effect_class=normalized.effect_class.value,
                                       resource_scope=normalized.resource_scope,
                                       idempotency_key=normalized.idempotency_key)
            return await self._deny(normalized, SecurityDecision.DENY, "dry_run_external_effect", started, simulated_effect=True)
        decision = self._policy.evaluate(normalized, self._ledger)
        snapshot = self._ledger.snapshot(normalized.run_id)
        self._ledger.record_decision(record_id=f"dec_{uuid4().hex}", run_id=normalized.run_id,
                                     action_id=normalized.action_id, decision=decision.decision.value,
                                     reason_code=decision.reason_code, snapshot_hash=snapshot.snapshot_hash)
        if decision.decision is not SecurityDecision.ALLOW:
            return await self._deny(normalized, decision.decision, decision.reason_code, started)
        self._ledger.record_action(action_id=normalized.action_id, run_id=normalized.run_id,
                                   lifecycle="authorized", request_hash=request_hash,
                                   effect_class=normalized.effect_class.value,
                                   resource_scope=normalized.resource_scope,
                                   idempotency_key=normalized.idempotency_key,
                                   details={"snapshot_hash": snapshot.snapshot_hash})
        return ActionResult(normalized.action_id, SecurityDecision.ALLOW, False,
                            reason_code="authorized", snapshot_hash=snapshot.snapshot_hash,
                            authority_eligible=decision.authority_eligible)

    async def submit(self, request: ActionRequest) -> ActionResult:
        cached = self._ledger.idempotent_result(request.run_id, request.idempotency_key)
        if cached is not None:
            return ActionResult(request.action_id, SecurityDecision.ALLOW, True,
                                value=cached.get("value"), reason_code="executed",
                                snapshot_hash=cached.get("snapshot_hash"),
                                authority_eligible=bool(cached.get("authority_eligible", True)))
        lease = await self._boundary_queue.acquire(request)
        if lease is None:
            return await self._deny(request, SecurityDecision.DENY, "deadline_or_quarantine", time.perf_counter())
        try:
            authorized = await self.authorize(request)
            if authorized.decision is not SecurityDecision.ALLOW:
                return authorized
            if request.scope_level.value == "platform" and request.effect_class in {EffectClass.E2, EffectClass.E3}:
                self._ledger.increment_metric(request.run_id, "platform_externality_cost")
            handler = self._handlers.get((request.tool_id, request.operation))
            if handler is None:
                return await self._deny(request, SecurityDecision.DENY, "unknown_action", time.perf_counter())
            snapshot = self._ledger.snapshot(request.run_id)
            decision = self._policy.evaluate(request, self._ledger)
            if decision.decision is not SecurityDecision.ALLOW:
                return await self._deny(request, decision.decision, decision.reason_code, time.perf_counter())
            try:
                value = await handler(request)
            except Exception as exc:
                self._ledger.record_action(action_id=request.action_id, run_id=request.run_id,
                                           lifecycle="failed", request_hash=self.request_hash(request),
                                           effect_class=request.effect_class.value,
                                           resource_scope=request.resource_scope,
                                           idempotency_key=request.idempotency_key,
                                           details={"error_type": type(exc).__name__})
                return await self._deny(request, SecurityDecision.UNKNOWN, "handler_failure", time.perf_counter())
            if not self._ledger.verify_snapshot(snapshot):
                escaped = request.effect_class in {EffectClass.E2, EffectClass.E3}
                self._ledger.record_action(action_id=request.action_id, run_id=request.run_id,
                                           lifecycle="failed", request_hash=self.request_hash(request),
                                           effect_class=request.effect_class.value,
                                           resource_scope=request.resource_scope,
                                           idempotency_key=request.idempotency_key,
                                           details={
                                               "reason": "snapshot_changed",
                                               "external_effect_escape": escaped,
                                               "compensation_required": escaped,
                                           })
                if escaped:
                    self._ledger.increment_metric(request.run_id, "external_effect_escape_count")
                    self._ledger.record_compensation(
                        record_id=f"comp_{uuid4().hex}",
                        run_id=request.run_id,
                        action_id=request.action_id,
                        effect_class=request.effect_class.value,
                        status="required",
                        details={"reason": "snapshot_changed"},
                    )
                return await self._deny(request, SecurityDecision.UNKNOWN, "snapshot_changed", time.perf_counter())
            details = {"value": value, "snapshot_hash": snapshot.snapshot_hash,
                       "authority_eligible": authorized.authority_eligible}
            self._ledger.record_action(action_id=request.action_id, run_id=request.run_id,
                                       lifecycle="executed", request_hash=self.request_hash(request),
                                       effect_class=request.effect_class.value,
                                       resource_scope=request.resource_scope,
                                       idempotency_key=request.idempotency_key, details=details)
            return ActionResult(request.action_id, SecurityDecision.ALLOW, True, value=value,
                                reason_code="executed", snapshot_hash=snapshot.snapshot_hash,
                                authority_eligible=authorized.authority_eligible)
        finally:
            await self._boundary_queue.release(lease)

    async def complete_mediated(self, request: ActionRequest, *, succeeded: bool) -> None:
        self._ledger.record_action(action_id=request.action_id, run_id=request.run_id,
                                   lifecycle="executed" if succeeded else "failed",
                                   request_hash=self.request_hash(request),
                                   effect_class=request.effect_class.value,
                                   resource_scope=request.resource_scope,
                                   idempotency_key=request.idempotency_key)

    async def _deny(self, request: ActionRequest, decision: SecurityDecision,
                    internal_reason: str, started: float, *, simulated_effect: bool = False) -> ActionResult:
        public_reason = "held: pending_review" if decision is SecurityDecision.REQUIRE_APPROVAL else "denied: policy"
        remaining = self._config.constant_denial_delay_ms / 1000 - (time.perf_counter() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)
        self._ledger.record_denial(record_id=f"deny_{uuid4().hex}", run_id=request.run_id,
                                   action_id=request.action_id, public_reason=public_reason,
                                   internal_reason=internal_reason,
                                   latency_bucket_ms=self._config.constant_denial_delay_ms,
                                   budget_charge=self._config.denial_budget_charge)
        count = self._denial_counts.get(request.actor_agent_id, 0) + 1
        self._denial_counts[request.actor_agent_id] = count
        if count >= self._config.probing_quarantine_threshold:
            await self._boundary_queue.quarantine_agent(request.actor_agent_id)
        # A contamination denial is new reachability information. v4 §5.3 requires
        # retention to be re-adjudicated here, and §8.4 rule 5 requires the scope
        # to be requeued; the repair itself decides whether this reason applies.
        if self._boundary_repair is not None:
            await self._boundary_repair.at_boundary(request, internal_reason)
        return ActionResult(request.action_id, decision, False, reason_code=internal_reason,
                            snapshot_hash=self._ledger.snapshot(request.run_id).snapshot_hash,
                            authority_eligible=False, simulated_effect=simulated_effect,
                            public_reason=public_reason)
