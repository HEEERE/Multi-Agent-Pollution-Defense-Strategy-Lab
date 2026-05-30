from __future__ import annotations

from app.defense.base import BaseDefenderAgent, DefenseContext
from app.defense.schemas import DefenderVerdict
from app.schemas import AgentEvent


class PromptGuardAgent(BaseDefenderAgent):
    def __init__(self, weight: float = 1.2) -> None:
        super().__init__(
            defender_id="prompt_guard",
            role="Prompt Injection Guard",
            weight=weight,
            veto_enabled=False,
        )

    async def evaluate(
        self, event: AgentEvent, context: DefenseContext
    ) -> DefenderVerdict:
        evidence: list[str] = []
        malicious_indicators = 0

        payload = event.payload_snippet.lower()
        risk_tags = event.risk_tags or []

        injection_patterns = [
            "ignore previous instructions",
            "ignore all prior",
            "disregard previous",
            "forget your instructions",
            "you are now",
            "pretend you are",
            "act as if",
            "new instructions:",
            "system prompt",
            "reveal your prompt",
            "show me your instructions",
            "developer mode",
            "jailbreak",
            "dan mode",
            "sudo mode",
            "override safety",
            "bypass restrictions",
            "role hijack",
            "you must obey",
        ]

        for pattern in injection_patterns:
            if pattern in payload:
                evidence.append(f"payload contains '{pattern}'")
                malicious_indicators += 1

        if "prompt_injection" in risk_tags:
            evidence.append("risk_tags contain prompt_injection")
            malicious_indicators += 1

        # Check L1/L3 detector results
        for d in context.detection_log:
            if d.get("is_threat") and d.get("detector_id") in ("regex", "llm_intent"):
                evidence.append(
                    f"{d['detector_id']} detector flagged threat: {d.get('reason', '')}"
                )
                malicious_indicators += 1

        if malicious_indicators >= 3:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="malicious",
                confidence=min(0.98, 0.7 + malicious_indicators * 0.08),
                evidence=evidence,
                recommended_action="block",
                weight=self.weight,
            )

        if malicious_indicators >= 1:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="suspicious",
                confidence=min(0.75, 0.45 + malicious_indicators * 0.15),
                evidence=evidence,
                recommended_action="alert",
                weight=self.weight,
            )

        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict="safe",
            confidence=0.9,
            evidence=evidence if evidence else ["no injection patterns detected"],
            recommended_action="allow",
            weight=self.weight,
        )
