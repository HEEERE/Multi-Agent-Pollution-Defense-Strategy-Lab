import pytest

from app.defense.containment import ContainmentRegistry
from app.defense.schemas import ContainmentPlan
from app.schemas import ActionTaken, AgentEvent, EventType


def _make_event(
    source: str = "Red_Attacker",
    target: str = "Task_Agent_A",
    event_type: str = "input",
    metadata: dict | None = None,
) -> AgentEvent:
    return AgentEvent(
        event_id="evt_test",
        trace_id="trace_test",
        event_type=event_type,
        source_node=source,
        target_node=target,
        payload_snippet="test",
        metadata=metadata or {},
    )


class TestContainmentRegistry:
    def test_quarantine_source_blocks_future_event(self):
        registry = ContainmentRegistry()
        registry.quarantined_nodes.add("Red_Attacker")

        event = _make_event(source="Red_Attacker", target="Task_Agent_A")
        blocked, reason = registry.blocks_event(event)
        assert blocked is True
        assert "quarantined" in reason

    def test_quarantine_target_blocks_future_event(self):
        registry = ContainmentRegistry()
        registry.quarantined_nodes.add("Task_Agent_A")

        event = _make_event(source="Gateway", target="Task_Agent_A")
        blocked, reason = registry.blocks_event(event)
        assert blocked is True
        assert "quarantined" in reason

    def test_safe_event_passes_when_nothing_quarantined(self):
        registry = ContainmentRegistry()
        event = _make_event(source="Gateway", target="Task_Agent_A")
        blocked, _ = registry.blocks_event(event)
        assert blocked is False

    def test_isolate_tool_blocks_tool_call(self):
        registry = ContainmentRegistry()
        registry.isolated_tools.add("Tool_RAG_Vector")

        event = _make_event(
            source="Task_Agent_A",
            target="Tool_RAG_Vector",
            event_type="tool_call",
        )
        blocked, reason = registry.blocks_event(event)
        assert blocked is True
        assert "isolated" in reason

    def test_block_edge_blocks_only_specific_pair(self):
        registry = ContainmentRegistry()
        registry.blocked_edges.add(("Red_Attacker", "Task_Agent_A"))

        blocked_event = _make_event(source="Red_Attacker", target="Task_Agent_A")
        blocked, _ = registry.blocks_event(blocked_event)
        assert blocked is True

        safe_event = _make_event(source="Red_Attacker", target="Task_Agent_B")
        blocked, _ = registry.blocks_event(safe_event)
        assert blocked is False

    def test_revoke_memory_key_blocks_memory_write(self):
        registry = ContainmentRegistry()
        registry.revoked_memory_keys.add("key_123")

        event = _make_event(
            source="Task_Agent_A",
            target="Tool_KnowledgeGraph",
            event_type="tool_call",
            metadata={"memory_op": "write", "memory_key": "key_123"},
        )
        blocked, reason = registry.blocks_event(event)
        assert blocked is True
        assert "revoked" in reason

    def test_different_memory_key_passes(self):
        registry = ContainmentRegistry()
        registry.revoked_memory_keys.add("key_123")

        event = _make_event(
            source="Task_Agent_A",
            target="Tool_KnowledgeGraph",
            event_type="tool_call",
            metadata={"memory_op": "write", "memory_key": "key_456"},
        )
        blocked, _ = registry.blocks_event(event)
        assert blocked is False

    def test_apply_plan_updates_sets(self):
        registry = ContainmentRegistry()
        plan = ContainmentPlan(
            quarantine_nodes=["Red_Attacker"],
            isolate_tools=["Tool_RAG_Vector"],
            block_edges=[("Red_Attacker", "Task_Agent_A")],
            revoke_memory_keys=["key_001"],
        )
        registry.apply_plan(plan)
        assert "Red_Attacker" in registry.quarantined_nodes
        assert "Tool_RAG_Vector" in registry.isolated_tools
        assert ("Red_Attacker", "Task_Agent_A") in registry.blocked_edges
        assert "key_001" in registry.revoked_memory_keys

    def test_release_node_removes_quarantine(self):
        registry = ContainmentRegistry()
        registry.quarantined_nodes.add("Task_Agent_A")
        registry.release_node("Task_Agent_A")
        assert "Task_Agent_A" not in registry.quarantined_nodes
