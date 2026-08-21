from __future__ import annotations

import pytest

from app.message_bus import MessageBus
from app.provenance import ProvenanceLedger
from app.actions import ActionGateway
from app.schemas import ActionTaken, AgentEvent, EventStatus, EventType


@pytest.mark.asyncio
async def test_committed_bus_events_are_versioned_and_linked():
    ledger = ProvenanceLedger()
    bus = MessageBus()
    bus.bind_provenance_ledger(ledger, "r1")
    first = await bus.publish(AgentEvent(event_type=EventType.INPUT, source_node="external", target_node="agent", payload_snippet="input", trust_level="untrusted"))
    second = await bus.publish(AgentEvent(event_type=EventType.COMMUNICATION, source_node="agent", target_node="tool", payload_snippet="derived", parent_event_id=first.event_id, status=EventStatus.INFECTED))
    assert ledger.get_artifact(f"event_{first.event_id}") is not None
    assert ledger.get_artifact(f"event_{second.event_id}") is not None
    assert any(d.child_version_id == f"event_{second.event_id}" for d in ledger.list_derivations("r1"))


@pytest.mark.asyncio
async def test_quarantine_event_creates_state_transition():
    ledger = ProvenanceLedger()
    bus = MessageBus()
    bus.bind_provenance_ledger(ledger, "r1")
    event = await bus.publish(AgentEvent(event_type=EventType.INPUT, source_node="external", target_node="agent", payload_snippet="blocked", action_taken=ActionTaken.QUARANTINE, status=EventStatus.QUARANTINED))
    assert ledger.current_state(f"event_{event.event_id}").value == "quarantined"


@pytest.mark.asyncio
async def test_bus_gateway_denies_low_integrity_e3_before_delivery():
    ledger = ProvenanceLedger()
    bus = MessageBus()
    bus.bind_provenance_ledger(ledger, "r1")
    bus.bind_action_gateway(ActionGateway(ledger))
    delivered = False

    async def handler(_event):
        nonlocal delivered
        delivered = True

    bus.subscribe("sink", handler)
    event = await bus.publish(AgentEvent(
        event_type=EventType.TOOL_CALL, source_node="agent", target_node="sink",
        payload_snippet="send secret", trust_level="untrusted",
        metadata={"effect_class": "E3"},
    ))
    assert event.action_taken is ActionTaken.BLOCK
    assert delivered is False


@pytest.mark.asyncio
async def test_public_broadcast_redacts_unavailable_artifact_refs():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    bus = MessageBus()
    bus.bind_provenance_ledger(ledger, "r1")
    projected = []

    async def capture(event):
        projected.append(event)

    bus.attach_broadcast_hook(capture)
    event = await bus.publish(AgentEvent(
        event_type=EventType.INPUT,
        source_node="external",
        target_node="agent",
        payload_snippet="secret",
        artifact_refs=["missing-version"],
    ))
    assert event.payload_snippet == "secret"
    assert projected[0].payload_snippet == "[REDACTED: unavailable provenance]"
    assert projected[0].metadata["projection_filtered"] is True


@pytest.mark.asyncio
async def test_event_origin_inherits_visible_parent_principals():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    bus = MessageBus()
    bus.bind_provenance_ledger(ledger, "r1")
    first = await bus.publish(AgentEvent(
        event_type=EventType.INPUT,
        source_node="external",
        target_node="agent",
        payload_snippet="input",
    ))
    second = await bus.publish(AgentEvent(
        event_type=EventType.COMMUNICATION,
        source_node="agent",
        target_node="tool",
        payload_snippet="derived",
        parent_event_id=first.event_id,
        artifact_refs=[f"event_{first.event_id}"],
    ))
    artifact = ledger.get_artifact(f"event_{second.event_id}")
    assert artifact is not None
    assert {"external", "agent"}.issubset(artifact.origin_principals)
