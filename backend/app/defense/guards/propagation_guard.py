from __future__ import annotations

from app.defense.base import BaseDefenderAgent, DefenseContext
from app.defense.schemas import DefenderVerdict
from app.schemas import AgentEvent


class PropagationGuardAgent(BaseDefenderAgent):
    def __init__(self, weight: float = 1.5) -> None:
        super().__init__(
            defender_id="propagation_guard",
            role="Propagation Guard",
            weight=weight,
            veto_enabled=True,
        )

    async def evaluate(
        self, event: AgentEvent, context: DefenseContext
    ) -> DefenderVerdict:
        trace_graph = context.trace_graph
        if not trace_graph or not trace_graph.get("edges"):
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="safe",
                confidence=0.9,
                evidence=["no trace graph available"],
                recommended_action="allow",
                weight=self.weight,
            )

        evidence: list[str] = []
        malicious_indicators = 0

        # Check propagation depth
        edges = trace_graph.get("edges", [])
        nodes = trace_graph.get("nodes", [])

        source_edges = [e for e in edges if e.get("source") == event.source_node]
        if len(source_edges) >= 3:
            evidence.append(f"source node has {len(source_edges)} outgoing edges (high fan-out)")
            malicious_indicators += 1

        # Blast radius: contaminated nodes
        contaminated_count = sum(
            1 for n in nodes if n.get("contamination_score", 0) >= 0.5
        )
        if contaminated_count >= 3:
            evidence.append(f"blast radius: {contaminated_count} contaminated nodes")
            malicious_indicators += 1

        # Chain contamination detection: memory_write → rag_retrieval → tool_call
        chain_indicators = 0
        has_memory_write = any(
            e.get("edge_kind") == "memory_write" for e in edges
        )
        has_rag_retrieval = any(
            e.get("edge_kind") == "rag_retrieval" for e in edges
        )
        has_tool_call = any(
            e.get("edge_kind") == "tool_call" for e in edges
        )
        if has_memory_write:
            chain_indicators += 1
        if has_rag_retrieval:
            chain_indicators += 1
        if has_tool_call:
            chain_indicators += 1

        if chain_indicators >= 2:
            evidence.append(f"chain contamination detected ({chain_indicators}/3 link types)")
            malicious_indicators += 1

        # Check contamination score of source/target nodes
        for n in nodes:
            if n.get("node_id") == event.source_node:
                score = n.get("contamination_score", 0)
                if score >= 0.7:
                    evidence.append(f"source node contamination score: {score}")
                    malicious_indicators += 2
                elif score >= 0.4:
                    evidence.append(f"source node contamination score: {score}")
                    malicious_indicators += 1

        if event.contamination_score >= 0.6:
            evidence.append(f"event contamination score: {event.contamination_score}")
            malicious_indicators += 1

        if malicious_indicators >= 3:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="malicious",
                confidence=min(0.95, 0.65 + malicious_indicators * 0.08),
                evidence=evidence,
                recommended_action="isolate",
                weight=self.weight,
            )

        if malicious_indicators >= 1:
            return DefenderVerdict(
                defender_id=self.defender_id,
                role=self.role,
                verdict="suspicious",
                confidence=min(0.75, 0.45 + malicious_indicators * 0.12),
                evidence=evidence,
                recommended_action="quarantine",
                weight=self.weight,
            )

        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict="safe",
            confidence=0.85,
            evidence=["no propagation anomalies detected"],
            recommended_action="allow",
            weight=self.weight,
        )
