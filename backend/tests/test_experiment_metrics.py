import pytest

from app.experiments.metrics import MetricsComputer
from app.schemas import ActionTaken, AgentEvent, EventStatus, EventType


def make_event(
    event_id: str,
    source: str,
    target: str,
    *,
    status: EventStatus = EventStatus.SAFE,
    action: ActionTaken = ActionTaken.NONE,
    parent_event_id: str | None = None,
    ground_truth: bool | None = None,
    event_type: EventType = EventType.INPUT,
    latency_ms: float | None = None,
) -> AgentEvent:
    metadata = {}
    if ground_truth is not None:
        metadata["ground_truth_threat"] = ground_truth
    if latency_ms is not None:
        metadata["detection"] = {"latency_ms": latency_ms}
    return AgentEvent(
        event_id=event_id,
        trace_id="trace_metrics",
        parent_event_id=parent_event_id,
        event_type=event_type,
        source_node=source,
        target_node=target,
        payload_snippet=event_id,
        status=status,
        action_taken=action,
        metadata=metadata,
    )


def test_metrics_use_labels_and_bounded_spread_rate():
    events = [
        make_event(
            "e1", "gateway", "agent_a",
            status=EventStatus.QUARANTINED,
            action=ActionTaken.BLOCK,
            ground_truth=False,
            latency_ms=12,
        ),
        make_event("e2", "agent_a", "agent_b", ground_truth=False),
        make_event(
            "e3", "agent_a", "agent_b",
            status=EventStatus.EXPOSED,
            parent_event_id="e1",
            ground_truth=True,
            latency_ms=8,
        ),
        make_event(
            "i1", "monitor", "agent_a",
            status=EventStatus.QUARANTINED,
            action=ActionTaken.BLOCK,
            event_type=EventType.INTERVENTION,
        ),
    ]

    metrics = MetricsComputer(events).compute()

    assert metrics.false_positive_rate == 0.5
    assert metrics.propagation_depth == 1
    assert 0 < metrics.contamination_spread_rate <= 1
    assert metrics.detection_latency_ms == 10
    assert metrics.threats_detected == 1
