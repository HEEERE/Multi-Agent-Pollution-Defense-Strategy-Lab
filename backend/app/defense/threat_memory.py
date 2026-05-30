from __future__ import annotations


class ThreatMemory:
    def __init__(self) -> None:
        self.node_risk: dict[str, float] = {}
        self.node_incidents: dict[str, list[str]] = {}
        self.known_indicators: set[str] = set()
        self.contaminated_traces: set[str] = set()
        self.recent_decisions: list[dict] = []

    def record_decision(self, event, decision) -> None:
        self.recent_decisions.append(decision.model_dump(mode="json"))
        if len(self.recent_decisions) > 200:
            self.recent_decisions = self.recent_decisions[-200:]

        if decision.final_action in {"quarantine", "block", "isolate"}:
            self.node_risk[event.source_node] = min(
                1.0,
                self.node_risk.get(event.source_node, 0.0) + decision.confidence * 0.3,
            )
            self.node_incidents.setdefault(event.source_node, []).append(
                decision.decision_id
            )
            self.contaminated_traces.add(event.trace_id)

        for vote in decision.votes:
            for ev in vote.evidence:
                if len(ev) <= 200:
                    self.known_indicators.add(ev)

    def snapshot(self) -> dict:
        return {
            "node_risk": dict(self.node_risk),
            "node_incidents": dict(self.node_incidents),
            "known_indicators": list(self.known_indicators)[-100:],
            "contaminated_traces": list(self.contaminated_traces)[-100:],
            "recent_decisions": self.recent_decisions[-20:],
        }
