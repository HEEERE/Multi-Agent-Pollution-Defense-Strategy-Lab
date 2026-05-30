from __future__ import annotations

from app.defense.base import BaseDefenderAgent, DefenseContext
from app.defense.schemas import DefenderVerdict
from app.schemas import AgentEvent, EventType


class ToolGuardAgent(BaseDefenderAgent):
    def __init__(self, weight: float = 1.3) -> None:
        super().__init__(
            defender_id="tool_guard",
            role="Tool Call Guard",
            weight=weight,
            veto_enabled=True,
        )

    async def evaluate(
        self, event: AgentEvent, context: DefenseContext
    ) -> DefenderVerdict:
        if event.event_type != EventType.TOOL_CALL:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="safe",
                confidence=0.95,
                evidence=["not a tool call"],
                recommended_action="allow",
                weight=self.weight,
            )

        evidence: list[str] = []
        malicious_indicators = 0

        payload = event.payload_snippet.lower()

        dangerous_patterns = {
            "delete": ("destructive operation: delete", 2),
            "rm -rf": ("destructive operation: rm -rf", 3),
            "drop table": ("destructive operation: drop", 3),
            "exfiltrate": ("data exfiltration", 2),
            "dump": ("data dump", 1),
            "token": ("credential access: token", 2),
            "password": ("credential access: password", 2),
            "api_key": ("credential access: api_key", 2),
            "secret": ("credential access: secret", 2),
            "eval(": ("code execution: eval", 3),
            "exec(": ("code execution: exec", 3),
            "__import__": ("code execution: __import__", 2),
            "os.system": ("command execution: os.system", 3),
            "subprocess": ("command execution: subprocess", 3),
            "write_file": ("file write operation", 2),
            "overwrite": ("file overwrite", 2),
            "sudo": ("privilege escalation", 2),
        }

        for pattern, (desc, weight) in dangerous_patterns.items():
            if pattern in payload:
                evidence.append(desc)
                malicious_indicators += weight

        if "tool_pollution" in (event.risk_tags or []):
            evidence.append("risk_tags contain tool_pollution")
            malicious_indicators += 1

        if event.trust_level == "untrusted":
            evidence.append("source is untrusted")
            malicious_indicators += 1

        if malicious_indicators >= 4:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="malicious",
                confidence=min(0.98, 0.75 + malicious_indicators * 0.04),
                evidence=evidence,
                recommended_action="block",
                weight=self.weight,
            )

        if malicious_indicators >= 2:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="malicious",
                confidence=min(0.85, 0.55 + malicious_indicators * 0.08),
                evidence=evidence,
                recommended_action="quarantine",
                weight=self.weight,
            )

        if malicious_indicators >= 1:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="suspicious",
                confidence=0.55 + malicious_indicators * 0.1,
                evidence=evidence,
                recommended_action="challenge",
                weight=self.weight,
            )

        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict="safe",
            confidence=0.9,
            evidence=["no dangerous tool patterns detected"],
            recommended_action="allow",
            weight=self.weight,
        )
