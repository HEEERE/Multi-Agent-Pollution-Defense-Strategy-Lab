from __future__ import annotations

from app.defense.base import BaseDefenderAgent, DefenseContext
from app.defense.schemas import DefenderVerdict
from app.schemas import AgentEvent


class RAGGuardAgent(BaseDefenderAgent):
    def __init__(self, weight: float = 1.1) -> None:
        super().__init__(
            defender_id="rag_guard",
            role="RAG Context Guard",
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
        rag_op = event.metadata.get("rag_op")

        rag_markers = [
            "priority override",
            "trusted paragraph",
            "hidden appendix",
            "ignore source",
            "authoritative answer",
            "override context",
            "disregard previous context",
            "the correct answer is",
            "trusted source says",
            "confidential instruction",
        ]

        for marker in rag_markers:
            if marker in payload:
                evidence.append(f"payload contains '{marker}'")
                malicious_indicators += 1

        if "rag_poisoning" in risk_tags or "context_poisoning" in risk_tags:
            evidence.append("risk_tags contain rag/context poisoning")
            malicious_indicators += 1

        if rag_op:
            evidence.append(f"RAG operation detected: {rag_op}")
            if rag_op in ("retrieve", "query") and malicious_indicators > 0:
                malicious_indicators += 1

        target_rag = (
            "RAG" in event.target_node
            or "Vector" in event.target_node
            or "rag" in event.edge_kind
        )
        if target_rag and malicious_indicators > 0:
            evidence.append("target is a RAG/Vector node")
            malicious_indicators += 1

        # Check L2 RAG detector results
        for d in context.detection_log:
            if d.get("is_threat") and d.get("detector_id") in ("rag_feature",):
                evidence.append(f"RAG detector flagged threat: {d.get('reason', '')}")
                malicious_indicators += 1

        if malicious_indicators >= 3:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="malicious",
                confidence=min(0.95, 0.65 + malicious_indicators * 0.1),
                evidence=evidence,
                recommended_action="quarantine",
                weight=self.weight,
            )

        if malicious_indicators >= 1:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="suspicious",
                confidence=min(0.7, 0.4 + malicious_indicators * 0.15),
                evidence=evidence,
                recommended_action="alert",
                weight=self.weight,
            )

        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict="safe",
            confidence=0.9,
            evidence=["no RAG poisoning indicators"],
            recommended_action="allow",
            weight=self.weight,
        )
