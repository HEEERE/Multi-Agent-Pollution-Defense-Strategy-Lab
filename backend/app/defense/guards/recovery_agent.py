from __future__ import annotations

from app.defense.base import BaseDefenderAgent, DefenseContext
from app.defense.schemas import DefenderVerdict
from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventSeverity,
    EventStatus,
    EventType,
    MonitorLevel,
    new_id,
)


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
        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict="safe",
            confidence=0.5,
            evidence=["recovery agent is not a voting guard"],
            recommended_action="allow",
            weight=self.weight,
        )

    def can_recover(self, node_id: str) -> tuple[bool, str]:
        if not self._threat_memory:
            return False, "threat memory not available"

        node_risk = self._threat_memory.node_risk.get(node_id, 0.0)
        if node_risk >= 0.5:
            return False, f"node risk too high: {node_risk:.2f} >= 0.5"

        recent_decisions = self._threat_memory.recent_decisions or []
        recent_ids = self._threat_memory.node_incidents.get(node_id, [])
        relevant = [
            d for d in recent_decisions if d.get("decision_id") in recent_ids
        ]
        recent = relevant[-10:]
        malicious_recent = sum(
            1
            for d in recent
            if d.get("final_action") in {"block", "isolate", "quarantine"}
        )
        if malicious_recent >= 2:
            return False, f"too many recent malicious decisions: {malicious_recent}"

        return True, "recovery checks passed"

    def build_recovery_event(
        self, node_id: str, trace_id: str | None = None
    ) -> AgentEvent | None:
        can_recover, reason = self.can_recover(node_id)
        if not can_recover:
            return None

        return AgentEvent(
            event_id=f"rec_{new_id()}",
            trace_id=trace_id or f"recovery_{new_id()}",
            event_type=EventType.RECOVERY,
            source_node="RecoveryAgent",
            target_node=node_id,
            payload_snippet=f"Node {node_id} recovery approved: {reason}",
            status=EventStatus.RECOVERED,
            action_taken=ActionTaken.RECOVER,
            severity=EventSeverity.INFO,
            monitor_level=MonitorLevel.LLM_INTENT,
            metadata={
                "recovered_node": node_id,
                "recovery_reason": reason,
            },
        )
