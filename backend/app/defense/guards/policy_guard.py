from __future__ import annotations

from app.defense.base import BaseDefenderAgent, DefenseContext
from app.defense.schemas import DefenderVerdict
from app.schemas import AgentEvent


class PolicyGuardAgent(BaseDefenderAgent):
    def __init__(self, policy_engine=None, weight: float = 1.4) -> None:
        super().__init__(
            defender_id="policy_guard",
            role="Policy Enforcement Guard",
            weight=weight,
            veto_enabled=True,
        )
        self._policy_engine = policy_engine

    async def evaluate(
        self, event: AgentEvent, context: DefenseContext
    ) -> DefenderVerdict:
        if self._policy_engine is None:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="unknown",
                confidence=0.0,
                evidence=["policy engine not configured"],
                recommended_action="allow",
                weight=self.weight,
            )

        decision = self._policy_engine.evaluate(event)

        if decision.action in {"block", "deny"}:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="malicious",
                confidence=0.9,
                evidence=[f"policy {decision.policy_id}: {decision.reason}"],
                recommended_action="block",
                weight=self.weight,
            )

        if decision.action in {"quarantine", "isolate"}:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="malicious",
                confidence=0.85,
                evidence=[f"policy {decision.policy_id}: {decision.reason}"],
                recommended_action=decision.action,
                weight=self.weight,
            )

        if decision.action == "alert":
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="suspicious",
                confidence=0.6,
                evidence=[f"policy {decision.policy_id}: {decision.reason}"],
                recommended_action="alert",
                weight=self.weight,
            )

        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict="safe",
            confidence=0.85,
            evidence=["no policy matched"],
            recommended_action="allow",
            weight=self.weight,
        )
