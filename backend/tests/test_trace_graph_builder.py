import pytest

from app.schemas import AgentEvent, EventStatus, EventType
from app.trace_graph.builder import TraceGraphBuilder


def _make_event(
    event_id: str = "evt_001",
    trace_id: str = "trace_001",
    event_type: str = "input",
    source: str = "gateway",
    target: str = "agent_a",
    status: str = "safe",
    metadata: dict | None = None,
    timestamp: float = 1000.0,
) -> AgentEvent:
    return AgentEvent(
        event_id=event_id,
        trace_id=trace_id,
        event_type=event_type,
        source_node=source,
        target_node=target,
        payload_snippet="test payload",
        status=status,
        metadata=metadata or {},
        timestamp=timestamp,
    )


class TestTraceGraphBuilder:
    def test_empty_events_returns_empty_graph(self):
        builder = TraceGraphBuilder()
        graph = builder.build([])
        assert graph.trace_id == ""
        assert graph.nodes == []
        assert graph.edges == []

    def test_single_input_event_creates_two_nodes_and_edge(self):
        builder = TraceGraphBuilder()
        event = _make_event()
        graph = builder.build([event])

        assert graph.trace_id == "trace_001"
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert graph.edges[0].edge_kind == "message"

    def test_infected_event_sets_target_contamination(self):
        builder = TraceGraphBuilder()
        event = _make_event(status="infected")
        graph = builder.build([event])

        target_node = next(n for n in graph.nodes if n.node_id == "agent_a")
        assert target_node.contamination_score >= 0.8

    def test_memory_metadata_generates_memory_write_edge(self):
        builder = TraceGraphBuilder()
        event = _make_event(
            event_type="tool_call",
            target="memory_store",
            metadata={"memory_op": "write"},
        )
        graph = builder.build([event])

        assert graph.edges[0].edge_kind == "memory_write"

    def test_rag_metadata_generates_rag_retrieval_edge(self):
        builder = TraceGraphBuilder()
        event = _make_event(
            event_type="tool_call",
            target="vector_db",
            metadata={"rag_op": "retrieve"},
        )
        graph = builder.build([event])

        assert graph.edges[0].edge_kind == "rag_retrieval"
