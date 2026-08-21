"""Phase 0 regression tests for the three reproduced repository defects.

These assert *semantics*, not the historical reproduction scripts. That
distinction matters for F-C1: the containment branch in ``MessageBus.publish``
rewrites blocked events to ``ActionTaken.BLOCK``, so a script that only drives
the containment path can pass while the underlying defect — an event carrying
``ActionTaken.QUARANTINE`` still being delivered — remains live. The
``DefenseCoordinator`` does produce ``QUARANTINE`` directly, so the delivery path
must treat it exactly like BLOCK/ISOLATE.

* F-C1  quarantined event must not be delivered to handlers or all-listeners.
* F-C2  a store failure must not be swallowed: publish must not report success
        and must not deliver.
* F-C3  a single run must not hold two ContainmentRegistry instances.
"""

from __future__ import annotations

import pytest

from app.message_bus import MessageBus
from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventSeverity,
    EventStatus,
    EventType,
)


def _event(
    *,
    action_taken: ActionTaken = ActionTaken.NONE,
    status: EventStatus = EventStatus.SAFE,
    source: str = "agent_a",
    target: str = "agent_b",
    event_id: str = "evt_regression",
) -> AgentEvent:
    return AgentEvent(
        event_id=event_id,
        trace_id="trace_regression",
        event_type=EventType.COMMUNICATION,
        source_node=source,
        target_node=target,
        payload_snippet="regression probe",
        trust_level="untrusted",
        contamination_score=0.9,
        risk_tags=["regression"],
        action_taken=action_taken,
        status=status,
        severity=EventSeverity.CRITICAL,
        metadata={},
    )


class _RecordingSink:
    """Captures every delivery route out of the bus."""

    def __init__(self) -> None:
        self.handler_calls: list[str] = []
        self.listener_calls: list[str] = []

    async def handler(self, event: AgentEvent) -> None:
        self.handler_calls.append(event.event_id)

    async def listener(self, event: AgentEvent) -> None:
        self.listener_calls.append(event.event_id)

    @property
    def delivered(self) -> bool:
        return bool(self.handler_calls or self.listener_calls)


# ---------------------------------------------------------------------------
# F-C1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [ActionTaken.BLOCK, ActionTaken.ISOLATE, ActionTaken.QUARANTINE],
)
async def test_fc1_contained_actions_are_never_delivered(action):
    """BLOCK, ISOLATE and QUARANTINE must all stop delivery.

    QUARANTINE is the regression: it is produced by DefenseCoordinator for the
    ``quarantine`` decision, and reaches ``publish`` without going through the
    containment rewrite, so it must be intercepted on its own merit.
    """
    bus = MessageBus()
    sink = _RecordingSink()
    bus.subscribe("agent_b", sink.handler)
    bus.subscribe_all(sink.listener)

    result = await bus.publish(_event(action_taken=action))

    assert result is not None
    assert result.action_taken is action
    assert sink.handler_calls == [], (
        f"{action.value} event was delivered to the target handler"
    )
    assert sink.listener_calls == [], (
        f"{action.value} event was delivered to all-listeners"
    )
    assert sink.delivered is False


async def test_fc1_quarantined_status_is_not_delivered():
    """A QUARANTINED/ISOLATED status must also stop delivery.

    Status and action_taken are set independently in several code paths, so the
    guard cannot rely on action_taken alone.
    """
    for status in (EventStatus.QUARANTINED, EventStatus.ISOLATED):
        bus = MessageBus()
        sink = _RecordingSink()
        bus.subscribe("agent_b", sink.handler)
        bus.subscribe_all(sink.listener)

        await bus.publish(_event(status=status, action_taken=ActionTaken.NONE))

        assert sink.delivered is False, f"status={status.value} was delivered"


async def test_fc1_benign_event_is_still_delivered():
    """Negative control: the guard must not block ordinary traffic."""
    bus = MessageBus()
    sink = _RecordingSink()
    bus.subscribe("agent_b", sink.handler)
    bus.subscribe_all(sink.listener)

    await bus.publish(_event(action_taken=ActionTaken.NONE, status=EventStatus.SAFE))

    assert sink.handler_calls == ["evt_regression"]
    assert sink.listener_calls == ["evt_regression"]


async def test_fc1_alert_and_challenge_remain_deliverable():
    """ALERT/CHALLENGE are observation actions, not containment actions."""
    for action in (ActionTaken.ALERT, ActionTaken.CHALLENGE):
        bus = MessageBus()
        sink = _RecordingSink()
        bus.subscribe("agent_b", sink.handler)

        await bus.publish(_event(action_taken=action))

        assert sink.handler_calls == ["evt_regression"], (
            f"{action.value} must not be treated as containment"
        )


# ---------------------------------------------------------------------------
# F-C2
# ---------------------------------------------------------------------------


class _FailingEventStore:
    """Event store whose writes always fail."""

    def __init__(self) -> None:
        self.attempts = 0

    async def store_event(self, event: AgentEvent) -> None:
        self.attempts += 1
        raise RuntimeError("simulated sqlite commit failure")

    async def store_run_event(self, payload: dict) -> None:
        self.attempts += 1
        raise RuntimeError("simulated sqlite commit failure")


async def test_fc2_store_failure_is_not_swallowed():
    """A persistence failure must not be reported as a successful publish.

    The historical defect returned the event and delivered it anyway, so the run
    looked healthy while the ledger had lost the record.
    """
    bus = MessageBus()
    store = _FailingEventStore()
    bus.bind_event_store(store)
    sink = _RecordingSink()
    bus.subscribe("agent_b", sink.handler)
    bus.subscribe_all(sink.listener)

    with pytest.raises(Exception) as excinfo:
        await bus.publish(_event())

    assert store.attempts >= 1, "the store was never called"
    assert sink.delivered is False, (
        "event was delivered to downstream despite the store failure"
    )
    assert "commit failure" in str(excinfo.value) or isinstance(
        excinfo.value, RuntimeError
    )


async def test_fc2_store_failure_marks_history_consistently():
    """History must not retain an event whose persistence failed."""
    bus = MessageBus()
    bus.bind_event_store(_FailingEventStore())

    with pytest.raises(Exception):
        await bus.publish(_event())

    assert len(bus.history) == 0, (
        "failed event remained in history, so the in-memory view disagrees "
        "with the ledger"
    )


async def test_fc2_healthy_store_still_delivers():
    """Negative control: a working store must not break delivery."""

    class _OkStore:
        def __init__(self) -> None:
            self.events: list[str] = []

        async def store_event(self, event: AgentEvent) -> None:
            self.events.append(event.event_id)

        async def store_run_event(self, payload: dict) -> None:
            pass

    bus = MessageBus()
    store = _OkStore()
    bus.bind_event_store(store)
    sink = _RecordingSink()
    bus.subscribe("agent_b", sink.handler)

    result = await bus.publish(_event())

    assert result is not None
    assert store.events == ["evt_regression"]
    assert sink.handler_calls == ["evt_regression"]
    assert len(bus.history) == 1


# ---------------------------------------------------------------------------
# F-C3
# ---------------------------------------------------------------------------


def test_fc3_single_containment_registry_per_coordinator():
    """The coordinator and the bus must share one ContainmentRegistry.

    The historical defect kept a module-level singleton *and* built a fresh
    registry inside ``create_defense_coordinator``, so a plan applied through one
    was invisible to the other.
    """
    from app.defense.containment import ContainmentRegistry
    from app.defense.manager import create_defense_coordinator

    bus = MessageBus()
    coordinator = create_defense_coordinator(bus=bus)

    registry = getattr(coordinator, "containment_registry", None)
    assert isinstance(registry, ContainmentRegistry), (
        "coordinator does not expose its ContainmentRegistry"
    )
    assert bus._containment_registry is registry, (
        "bus and coordinator hold different ContainmentRegistry instances"
    )


def test_fc3_no_module_level_registry_singleton():
    """No global getter may hand out a second registry.

    A module-level singleton makes state leak across runs, which breaks the
    run-isolation invariant the research design depends on.
    """
    import app.defense.manager as manager

    assert not hasattr(manager, "get_containment_registry"), (
        "global get_containment_registry() still exists; it lets two runs share "
        "containment state"
    )
    assert not hasattr(manager, "get_threat_memory"), (
        "global get_threat_memory() still exists"
    )


def test_fc3_two_coordinators_do_not_share_state():
    """Two runs must get independent containment state."""
    from app.defense.manager import create_defense_coordinator

    bus_a, bus_b = MessageBus(), MessageBus()
    coord_a = create_defense_coordinator(bus=bus_a)
    coord_b = create_defense_coordinator(bus=bus_b)

    reg_a = coord_a.containment_registry
    reg_b = coord_b.containment_registry

    assert reg_a is not reg_b
    reg_a.quarantined_nodes.add("agent_x")
    assert "agent_x" not in reg_b.quarantined_nodes, (
        "containment state leaked between runs"
    )
