from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.actions.models import ActionRequest, EffectClass
from app.provenance.ledger import ProvenanceLedger


@dataclass(frozen=True)
class BoundaryLease:
    ticket: int
    scopes: frozenset[str]
    generation: int


class ActionBoundaryQueue:
    """FIFO for overlapping scopes; disjoint scopes can proceed concurrently."""

    def __init__(self, ledger: ProvenanceLedger) -> None:
        self.ledger = ledger
        self._condition = asyncio.Condition()
        self._next_ticket = 0
        self._pending: list[tuple[int, str, frozenset[str], int]] = []
        self._active: dict[int, BoundaryLease] = {}
        self._generation = 0
        self._quarantined_agents: set[str] = set()

    @staticmethod
    def affected_scopes(request: ActionRequest) -> frozenset[str]:
        prefix = "platform" if request.scope_level.value == "platform" else request.run_id
        return frozenset({f"{prefix}:{request.resource_scope}"})

    @staticmethod
    def _overlap(left: frozenset[str], right: frozenset[str]) -> bool:
        return bool(left & right) or "*" in left or "*" in right

    async def acquire(self, request: ActionRequest) -> BoundaryLease | None:
        if request.effect_class is EffectClass.E0:
            return BoundaryLease(-1, self.affected_scopes(request), self._generation)
        scopes = self.affected_scopes(request)
        async with self._condition:
            ticket = self._next_ticket
            self._next_ticket += 1
            generation = self._generation
            self._pending.append((ticket, request.actor_agent_id, scopes, generation))
            while True:
                if request.actor_agent_id in self._quarantined_agents:
                    self._pending = [item for item in self._pending if item[0] != ticket]
                    self.ledger.increment_metric(request.run_id, "starvation_count")
                    return None
                if request.deadline is not None and time.time() > request.deadline:
                    self._pending = [item for item in self._pending if item[0] != ticket]
                    self.ledger.increment_metric(request.run_id, "starvation_count")
                    self.ledger.increment_metric(request.run_id, "deadline_miss_rate")
                    return None
                if generation != self._generation:
                    generation = self._generation
                    self.ledger.increment_metric(request.run_id, "requeue_count")
                earlier_conflict = any(
                    other_ticket < ticket and self._overlap(other_scopes, scopes)
                    for other_ticket, _actor, other_scopes, _generation in self._pending
                )
                active_conflict = any(self._overlap(active.scopes, scopes) for active in self._active.values())
                if not earlier_conflict and not active_conflict:
                    self._pending = [item for item in self._pending if item[0] != ticket]
                    lease = BoundaryLease(ticket, scopes, generation)
                    self._active[ticket] = lease
                    return lease
                timeout = None if request.deadline is None else max(0.001, request.deadline - time.time())
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=timeout)
                except TimeoutError:
                    continue

    async def release(self, lease: BoundaryLease) -> None:
        if lease.ticket < 0:
            return
        async with self._condition:
            self._active.pop(lease.ticket, None)
            self._condition.notify_all()

    async def invalidate_scopes(self, _scopes: set[str]) -> None:
        async with self._condition:
            self._generation += 1
            self._condition.notify_all()

    async def quarantine_agent(self, agent_id: str) -> None:
        async with self._condition:
            self._quarantined_agents.add(agent_id)
            self._generation += 1
            self._condition.notify_all()
