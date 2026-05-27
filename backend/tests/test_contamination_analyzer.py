import pytest

from app.schemas import AgentEvent, EventStatus, EventType
from app.trace_graph.analyzer import ContaminationAnalyzer
from app.trace_graph.builder import TraceGraphBuilder


def _make_event(
    event_id: str = "evt_001",
    trace_id: str = "trace_001",
    source: str = "gateway",
    target: str = "agent_a",
    status: str = "safe",
    event_type: str = "input",
    metadata: dict | None = None,
    timestamp: float = 1000.0,
) -> AgentEvent:
    return AgentEvent(
        event_id=event_id,
        trace_id=trace_id,
        event_type=event_type,
        source_node=source,
        target_node=target,
        payload_snippet="test",
        status=status,
        metadata=metadata or {},
        timestamp=timestamp,
    )


class TestContaminationAnalyzer:
    def test_no_contamination_blast_radius_zero(self):
        events = [
            _make_event(event_id="e1", source="gw", target="a", status="safe"),
            _make_event(event_id="e2", source="a", target="b", status="safe", timestamp=1001.0),
        ]
        builder = TraceGraphBuilder()
        graph = builder.build(events)
        analyzer = ContaminationAnalyzer()
        metrics = analyzer.analyze(graph)

        assert metrics.blast_radius == 0
        assert metrics.max_contamination_score == 0.0

    def test_one_hop_propagation_depth(self):
        events = [
            _make_event(event_id="e1", source="gw", target="a", status="infected"),
            _make_event(event_id="e2", source="a", target="b", status="safe", timestamp=1001.0),
        ]
        builder = TraceGraphBuilder()
        graph = builder.build(events)
        analyzer = ContaminationAnalyzer()
        metrics = analyzer.analyze(graph)

        assert metrics.propagation_depth >= 1

    def test_multi_hop_propagation_depth(self):
        events = [
            _make_event(event_id="e1", source="gw", target="a", status="infected"),
            _make_event(event_id="e2", source="a", target="b", status="exposed", timestamp=1001.0),
            _make_event(event_id="e3", source="b", target="c", status="exposed", timestamp=1002.0),
        ]
        builder = TraceGraphBuilder()
        graph = builder.build(events)
        analyzer = ContaminationAnalyzer()
        metrics = analyzer.analyze(graph)

        assert metrics.propagation_depth > 1

    def test_quarantine_recovery_success(self):
        events = [
            _make_event(event_id="e1", source="gw", target="a", status="infected"),
            _make_event(
                event_id="e2", source="monitor", target="a",
                status="quarantined", event_type="intervention", timestamp=1001.0,
            ),
            _make_event(
                event_id="e3", source="a", target="b",
                status="recovered", timestamp=1002.0,
            ),
        ]
        builder = TraceGraphBuilder()
        graph = builder.build(events)
        analyzer = ContaminationAnalyzer()
        metrics = analyzer.analyze(graph)

        assert metrics.recovery_success is True

    def test_persistence_when_tail_contaminated(self):
        events = []
        for i in range(10):
            events.append(
                _make_event(
                    event_id=f"e{i}",
                    source="gw",
                    target=f"agent_{i}",
                    status="infected" if i >= 7 else "safe",
                    timestamp=1000.0 + i,
                )
            )
        builder = TraceGraphBuilder()
        graph = builder.build(events)
        analyzer = ContaminationAnalyzer()
        metrics = analyzer.analyze(graph)

        assert metrics.contamination_persistence > 0
