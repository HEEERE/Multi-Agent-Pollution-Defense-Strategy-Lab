import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

from app.detectors.factory import create_default_pipeline
from app.detectors.pipeline import DetectorPipeline
from app.event_store import EventStore
from app.message_bus import MessageBus
from app.policy.engine import PolicyEngine
from app.replay.engine import ReplayEngine
from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventSpec,
    EventStatus,
    EventType,
)
from app.tools.base import BaseTool


# ── Helpers ─────────────────────────────────────────────────────

def _make_event(
    trace_id: str = "trace_test",
    event_id: str | None = None,
    source: str = "Gateway",
    target: str = "Task_Agent_A",
    action_taken: ActionTaken = ActionTaken.NONE,
    status: EventStatus = EventStatus.SAFE,
    payload: str = "test payload",
) -> AgentEvent:
    return AgentEvent(
        event_id=event_id or uuid.uuid4().hex[:16],
        trace_id=trace_id,
        event_type=EventType.INPUT,
        source_node=source,
        target_node=target,
        payload_snippet=payload,
        action_taken=action_taken,
        status=status,
    )


def _temp_db() -> str:
    return str(Path(tempfile.gettempdir()) / f"test_events_{uuid.uuid4().hex[:8]}.db")


# ── Fix 1: Playbook generates new trace each run ─────────────────

class TestPlaybookTraceIsolation:
    def test_event_spec_does_not_generate_ids(self):
        """EventSpec is a plain dataclass with no ID generation."""
        spec = EventSpec(
            event_type=EventType.INPUT,
            source_node="Gateway",
            target_node="Agent_A",
            payload_snippet="test",
            status=EventStatus.SAFE,
            action_taken=ActionTaken.NONE,
        )
        assert not hasattr(spec, "event_id")
        assert not hasattr(spec, "trace_id")

    def test_build_event_generates_fresh_ids(self):
        """Each build_event() call creates a new AgentEvent with unique IDs."""
        from app.playbooks import build_event

        spec = EventSpec(
            event_type=EventType.INPUT,
            source_node="Gateway",
            target_node="Task_Agent_A",
            payload_snippet="test",
            status=EventStatus.SAFE,
            action_taken=ActionTaken.NONE,
        )

        trace_id = f"trace_{uuid.uuid4().hex[:8]}"
        e1 = build_event(spec, trace_id)
        e2 = build_event(spec, trace_id)

        assert e1.event_id != e2.event_id
        assert e1.trace_id == trace_id
        assert e2.trace_id == trace_id

    @pytest.mark.asyncio
    async def test_run_playbook_generates_unique_trace_ids(self):
        """Running the same playbook twice produces different trace_ids in the store."""
        from app.playbooks import run_playbook

        db_path = _temp_db()
        store = EventStore(db_path)
        await store._get_conn()

        bus = MessageBus()
        bus.bind_event_store(store)

        # Patch message_bus in playbooks module
        import app.playbooks as pb
        orig_bus = pb.message_bus
        pb.message_bus = bus

        try:
            events_a = await run_playbook("d-safe-collaboration", delay_seconds=0.01)
            events_b = await run_playbook("d-safe-collaboration", delay_seconds=0.01)

            assert events_a
            assert events_b
            assert events_a[0].trace_id != events_b[0].trace_id

            trace_ids = await store.get_trace_ids()
            assert len(trace_ids) >= 2
        finally:
            pb.message_bus = orig_bus
            await store.close()
            try:
                os.remove(db_path)
            except OSError:
                pass


# ── Fix 2: Block event not delivered to tool ────────────────────

class TestBlockNotDeliveredToTool:
    @pytest.mark.asyncio
    async def test_block_event_not_routed_to_tool_handler(self):
        """MessageBus does not deliver BLOCK events to target handlers."""
        bus = MessageBus()

        received: list[AgentEvent] = []

        class SpyTool(BaseTool):
            async def handle_event(self, event: AgentEvent) -> None:
                received.append(event)
                await super().handle_event(event)

        tool = SpyTool("TestTool", bus)
        event = _make_event(
            target="TestTool",
            action_taken=ActionTaken.BLOCK,
        )

        result = await bus.publish(event)
        assert result is not None  # Still returned (stored/broadcast)
        assert len(received) == 0  # But never delivered to handler

    @pytest.mark.asyncio
    async def test_isolate_event_not_routed_to_tool_handler(self):
        """MessageBus does not deliver ISOLATE events to target handlers."""
        bus = MessageBus()

        received: list[AgentEvent] = []

        class SpyTool(BaseTool):
            async def handle_event(self, event: AgentEvent) -> None:
                received.append(event)
                await super().handle_event(event)

        tool = SpyTool("TestTool", bus)
        event = _make_event(
            target="TestTool",
            action_taken=ActionTaken.ISOLATE,
        )

        result = await bus.publish(event)
        assert len(received) == 0


# ── Fix 6: Tool result inherits trace_id ────────────────────────

class TestToolTraceInheritance:
    @pytest.mark.asyncio
    async def test_tool_result_inherits_trace_id(self):
        """Tool response carries the same trace_id and parent_event_id."""
        bus = MessageBus()

        results: list[AgentEvent] = []

        class CollectTool(BaseTool):
            async def return_result(self, **kwargs) -> AgentEvent | None:
                result = await super().return_result(**kwargs)
                if result:
                    results.append(result)
                return result

        tool = CollectTool("TestTool", bus)

        parent_event = _make_event(
            trace_id="trace_abc123",
            target="TestTool",
            event_id="evt_parent_001",
        )

        await bus.publish(parent_event)

        # Wait for async processing
        await asyncio.sleep(0.05)

        assert len(results) >= 1
        response = results[0]
        assert response.trace_id == "trace_abc123"
        assert response.parent_event_id == "evt_parent_001"


# ── Fix 4+9: Replay / trace ordering ─────────────────────────────

class TestReplayAndTraceOrdering:
    @pytest.mark.asyncio
    async def test_replay_start_returns_valid_session(self):
        """ReplayEngine.get_state() returns correct shape."""
        events = [
            _make_event(trace_id="trace_r1", event_id="e1"),
            _make_event(trace_id="trace_r1", event_id="e2"),
        ]
        engine = ReplayEngine(events)
        state = engine.get_state()
        assert state.trace_id == "trace_r1"
        assert state.total_events == 2
        assert state.current_index == 0

    @pytest.mark.asyncio
    async def test_trace_ids_sorted_by_max_timestamp(self):
        """get_trace_ids() returns traces ordered by most recent event."""
        db_path = _temp_db()
        store = EventStore(db_path)
        await store._get_conn()

        import time

        # Insert two traces with different timestamps
        old_trace = _make_event(trace_id="trace_old", event_id="old_1")
        old_trace2 = _make_event(trace_id="trace_old", event_id="old_2")
        old_trace2.timestamp = old_trace.timestamp  # same trace

        new_trace = _make_event(trace_id="trace_new", event_id="new_1")
        new_trace.timestamp = time.time() + 100  # much newer

        await store.store_event(old_trace)
        await store.store_event(new_trace)

        trace_ids = await store.get_trace_ids()
        # Newest trace should come first
        assert trace_ids[0] == "trace_new"
        assert trace_ids[1] == "trace_old"

        await store.close()
        try:
            os.remove(db_path)
        except OSError:
            pass


# ── Fix 5: Policy engine applied in pipeline ────────────────────

class TestPolicyEngineInPipeline:
    @pytest.mark.asyncio
    async def test_policy_engine_sets_policy_decision(self):
        """Events passing through pipeline with PolicyEngine get policy_decision set."""
        from app.detectors.base import BaseDetector, DetectionContext, DetectionResult
        from app.schemas import MonitorLevel

        class NoOpDetector(BaseDetector):
            @property
            def detector_id(self) -> str:
                return "noop"

            @property
            def level(self) -> MonitorLevel:
                return MonitorLevel.NONE

            async def detect(self, event: AgentEvent, context: DetectionContext) -> DetectionResult:
                return DetectionResult(
                    is_threat=False,
                    confidence=0.0,
                    reason="noop",
                    suggested_action=ActionTaken.NONE,
                )

        pipeline = DetectorPipeline(
            detectors=[NoOpDetector()],
            bus=None,
            policy_engine=PolicyEngine(),
        )

        event = _make_event()
        result = await pipeline.inspect(event)

        assert result is not None
        assert result.policy_decision is not None
        assert "policy" in result.metadata

    @pytest.mark.asyncio
    async def test_pipeline_without_policy_engine_still_works(self):
        """Pipeline without PolicyEngine does not crash."""
        from app.detectors.base import BaseDetector, DetectionContext, DetectionResult
        from app.schemas import MonitorLevel

        class NoOpDetector(BaseDetector):
            @property
            def detector_id(self) -> str:
                return "noop"

            @property
            def level(self) -> MonitorLevel:
                return MonitorLevel.NONE

            async def detect(self, event: AgentEvent, context: DetectionContext) -> DetectionResult:
                return DetectionResult(
                    is_threat=False,
                    confidence=0.0,
                    reason="noop",
                    suggested_action=ActionTaken.NONE,
                )

        pipeline = DetectorPipeline(
            detectors=[NoOpDetector()],
            bus=None,
            policy_engine=None,
        )

        event = _make_event()
        result = await pipeline.inspect(event)
        assert result is not None


# ── Fix 4: Settings update rebuilds pipeline ─────────────────────

class TestSettingsRebuildPipeline:
    def test_rebuild_runtime_pipeline_clears_and_recreates(self):
        """rebuild_runtime_pipeline() replaces monitors on the bus."""
        from app.demo_topology import rebuild_runtime_pipeline

        bus = MessageBus()
        # Simulate: attach initial monitor, then rebuild
        bus.attach_monitor(lambda e: e)
        assert len(bus._monitors) == 1

        # Patch message_bus used by demo_topology
        import app.demo_topology as dt
        orig_bus = dt.message_bus
        dt.message_bus = bus

        try:
            rebuild_runtime_pipeline()
            # After rebuild, old monitors cleared, new pipeline attached
            assert len(bus._monitors) == 1
        finally:
            dt.message_bus = orig_bus
