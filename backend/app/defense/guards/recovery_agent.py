from __future__ import annotations

from app.defense.base import BaseDefenderAgent, DefenseContext
from app.defense.schemas import DefenderVerdict
from app.schemas import AgentEvent


class RecoveryAgent(BaseDefenderAgent):
    def __init__(self, threat_memory=None, weight: float = 0.9) -> None:
        super().__init__(
            defender_id="recovery_agent",
            role="Recovery Agent",
            weight=weight,
            veto_enabled=False,
        )
        self._threat_memory = threat_memory

    async def evaluate(
        self, event: AgentEvent, context: DefenseContext
    ) -> DefenderVerdict:
        # RecoveryAgent is not a voting guard — it provides recovery recommendations
        # It is invoked separately by the coordinator for post-containment recovery checks
        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict="safe",
            confidence=0.5,
            evidence=["recovery evaluation not requested"],
            recommended_action="allow",
            weight=self.weight,
        )

    def can_recover(self, node_id: str, recent_decisions: list[dict]) -> bool:
        if not self._threat_memory:
            return False

        node_risk = self._threat_memory.node_risk.get(node_id, 0.0)
        if node_risk >= 0.5:
            return False

        # Check last 10 decisions for this node
        recent_ids = self._threat_memory.node_incidents.get(node_id, [])
        relevant_decisions = [
            d for d in recent_decisions if d.get("decision_id") in recent_ids
        ]
        recent = relevant_decisions[-10:]
        malicious_recent = sum(
            1
            for d in recent
            if d.get("final_action") in {"block", "isolate", "quarantine"}
        )
        if malicious_recent >= 2:
            return False

        return True
