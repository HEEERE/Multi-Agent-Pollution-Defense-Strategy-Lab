from __future__ import annotations

from app.defense.base import BaseDefenderAgent, DefenseContext
from app.defense.schemas import DefenderVerdict
from app.schemas import AgentEvent


class MemoryGuardAgent(BaseDefenderAgent):
    def __init__(self, weight: float = 1.2) -> None:
        super().__init__(
            defender_id="memory_guard",
            role="Memory Integrity Guard",
            weight=weight,
            veto_enabled=False,
        )

    async def evaluate(
        self, event: AgentEvent, context: DefenseContext
    ) -> DefenderVerdict:
        evidence: list[str] = []
        malicious_indicators = 0

        memory_op = event.metadata.get("memory_op")
        is_memory_target = (
            "Memory" in event.target_node or "KnowledgeGraph" in event.target_node
        )
        is_memory_source = (
            "Memory" in event.source_node or "KnowledgeGraph" in event.source_node
        )

        if not (memory_op or is_memory_target or is_memory_source):
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="safe",
                confidence=0.95,
                evidence=["not a memory operation"],
                recommended_action="allow",
                weight=self.weight,
            )

        if memory_op in {"write", "update"}:
            evidence.append(f"memory {memory_op} operation")
            malicious_indicators += 1

        if event.trust_level == "untrusted" and memory_op in {"write", "update"}:
            evidence.append("untrusted source writing to memory")
            malicious_indicators += 2

        payload = event.payload_snippet.lower()
        backdoor_markers = [
            "backdoor",
            "hidden instruction",
            "stored command",
            "persistent payload",
            "trigger word",
            "activation phrase",
        ]
        for marker in backdoor_markers:
            if marker in payload:
                evidence.append(f"potential backdoor: '{marker}'")
                malicious_indicators += 1

        if "memory_poisoning" in (event.risk_tags or []):
            evidence.append("risk_tags contain memory_poisoning")
            malicious_indicators += 1

        # Check detection log for related threats
        for d in context.detection_log:
            if d.get("is_threat") and d.get("detector_id") in (
                "regex",
                "semantic",
                "llm_intent",
            ):
                if malicious_indicators > 0:
                    evidence.append(
                        f"detector {d['detector_id']} supports memory threat"
                    )
                    malicious_indicators += 1
                    break

        if malicious_indicators >= 3:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="malicious",
                confidence=min(0.95, 0.65 + malicious_indicators * 0.1),
                evidence=evidence,
                recommended_action="block",
                weight=self.weight,
            )

        if malicious_indicators >= 1:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="suspicious",
                confidence=min(0.7, 0.4 + malicious_indicators * 0.15),
                evidence=evidence,
                recommended_action="quarantine",
                weight=self.weight,
            )

        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict="safe",
            confidence=0.9,
            evidence=["no memory poisoning detected"],
            recommended_action="allow",
            weight=self.weight,
        )
