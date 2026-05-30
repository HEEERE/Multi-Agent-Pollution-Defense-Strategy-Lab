from __future__ import annotations

from app.defense.base import BaseDefenderAgent, DefenseContext
from app.defense.schemas import DefenderVerdict
from app.schemas import AgentEvent


class HoneypotGuardAgent(BaseDefenderAgent):
    def __init__(self, weight: float = 0.8) -> None:
        super().__init__(
            defender_id="honeypot_guard",
            role="Honeypot Routing Guard",
            weight=weight,
            veto_enabled=False,
        )

    async def evaluate(
        self, event: AgentEvent, context: DefenseContext
    ) -> DefenderVerdict:
        evidence: list[str] = []

        # Check if any detector hit the gray zone
        gray_zone_hits = []
        for d in context.detection_log:
            if d.get("honeypot_routed"):
                gray_zone_hits.append(d)
            elif (
                not d.get("is_threat")
                and not d.get("skipped")
                and 0.45 <= d.get("confidence", 0) < 0.75
            ):
                gray_zone_hits.append(d)

        if not gray_zone_hits:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="safe",
                confidence=0.9,
                evidence=["no gray-zone detections"],
                recommended_action="allow",
                weight=self.weight,
            )

        # Check for strong malicious indicators elsewhere
        has_strong_block = False
        for d in context.detection_log:
            if d.get("is_threat") and d.get("confidence", 0) >= 0.8:
                has_strong_block = True
                break

        if event.contamination_score >= 0.5 and not has_strong_block:
            evidence.append(f"contamination score {event.contamination_score} in gray zone")
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="suspicious",
                confidence=0.55,
                evidence=evidence,
                recommended_action="decoy",
                weight=self.weight,
            )

        # In gray zone without strong block evidence → recommend decoy
        if not has_strong_block:
            avg_confidence = sum(d.get("confidence", 0) for d in gray_zone_hits) / len(gray_zone_hits)
            evidence.append(f"gray-zone detection: avg confidence {avg_confidence:.2f}")
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="suspicious",
                confidence=min(0.65, avg_confidence),
                evidence=evidence,
                recommended_action="decoy",
                weight=self.weight,
            )

        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict="unknown",
            confidence=0.4,
            evidence=evidence,
            recommended_action="allow",
            weight=self.weight,
        )
