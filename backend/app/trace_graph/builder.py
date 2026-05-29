import uuid

from app.schemas import AgentEvent
from app.trace_graph.models import TraceEdge, TraceGraph, TraceNode

STATUS_SCORE: dict[str, float] = {
    "safe": 0.0,
    "exposed": 0.25,
    "challenged": 0.35,
    "honeypotted": 0.2,
    "infected": 0.8,
    "quarantined": 0.65,
    "isolated": 0.9,
    "recovered": 0.1,
}

TAG_BONUS: dict[str, float] = {
    "prompt_injection": 0.2,
    "rag_poisoning": 0.2,
    "memory_poisoning": 0.25,
    "tool_pollution": 0.2,
    "inter_agent_spoofing": 0.2,
    "cascading_failure": 0.15,
}

EDGE_KIND_MAP: dict[str, str] = {
    "input": "message",
    "communication": "message",
    "tool_call": "tool_call",
    "intervention": "intervention",
    "challenge": "message",
}


def _compute_contamination_score(event: AgentEvent) -> float:
    if event.contamination_score > 0:
        return event.contamination_score
    base = STATUS_SCORE.get(event.status.value, 0.0)
    bonus = 0.0
    risk_tags = event.risk_tags or event.metadata.get("risk_tags", [])
    if isinstance(risk_tags, list):
        for tag in risk_tags:
            bonus += TAG_BONUS.get(tag, 0.0)
    return min(base + bonus, 1.0)


def _infer_node_type(node_id: str) -> str:
    if node_id.startswith("Tool_") or node_id.startswith("FakeTool_"):
        return "tool"
    if node_id.startswith("Auditor_"):
        return "monitor"
    if node_id == "Gateway":
        return "gateway"
    if node_id.startswith("Honeypot_"):
        return "agent"
    if node_id.startswith("Red_"):
        return "agent"
    return "agent"


def _infer_edge_kind(event: AgentEvent) -> str:
    if event.edge_kind:
        return event.edge_kind
    meta = event.metadata
    if meta.get("memory_op") == "write":
        return "memory_write"
    if meta.get("memory_op") == "read":
        return "memory_read"
    if meta.get("rag_op"):
        return "rag_retrieval"
    return EDGE_KIND_MAP.get(event.event_type.value, "message")


class TraceGraphBuilder:
    def build(self, events: list[AgentEvent]) -> TraceGraph:
        if not events:
            return TraceGraph(trace_id="")

        trace_id = events[0].trace_id
        node_map: dict[str, TraceNode] = {}
        edges: list[TraceEdge] = []
        node_scores: dict[str, list[float]] = {}

        for event in events:
            score = _compute_contamination_score(event)

            for node_id in (event.source_node, event.target_node):
                if node_id not in node_map:
                    node_map[node_id] = TraceNode(
                        node_id=node_id,
                        node_type=_infer_node_type(node_id),
                        label=node_id,
                        contamination_score=0.0,
                    )
                node_scores.setdefault(node_id, []).append(score)

            edge_kind = _infer_edge_kind(event)
            risk_tags = event.risk_tags or event.metadata.get("risk_tags", [])
            if isinstance(risk_tags, str):
                risk_tags = []

            source_score = STATUS_SCORE.get(
                event.metadata.get("source_status", "safe"), 0.0
            )
            delta = score - source_score

            edges.append(
                TraceEdge(
                    edge_id=uuid.uuid4().hex[:16],
                    trace_id=trace_id,
                    source=event.source_node,
                    target=event.target_node,
                    event_id=event.event_id,
                    edge_kind=edge_kind,
                    timestamp=event.timestamp,
                    risk_tags=risk_tags if isinstance(risk_tags, list) else [],
                    contamination_delta=round(delta, 4),
                    metadata={
                        "event_type": event.event_type.value,
                        "status": event.status.value,
                    },
                )
            )

        for node_id, scores in node_scores.items():
            node_map[node_id].contamination_score = round(max(scores), 4)

        nodes = list(node_map.values())

        return TraceGraph(
            trace_id=trace_id,
            nodes=nodes,
            edges=edges,
            metrics={
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "total_events": len(events),
            },
        )
