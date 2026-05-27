import pytest

from app.policy.engine import PolicyEngine
from app.policy.models import PolicyDecision
from app.schemas import ActionTaken, AgentEvent, EventType


def _make_event(
    event_type: str = "input",
    source: str = "gateway",
    target: str = "agent_a",
    trust_level: str = "unknown",
    contamination_score: float = 0.0,
    risk_tags: list[str] | None = None,
    action_taken: str = "none",
    metadata: dict | None = None,
) -> AgentEvent:
    return AgentEvent(
        event_id="evt_test",
        trace_id="trace_test",
        event_type=event_type,
        source_node=source,
        target_node=target,
        payload_snippet="test",
        trust_level=trust_level,
        contamination_score=contamination_score,
        risk_tags=risk_tags or [],
        action_taken=action_taken,
        metadata=metadata or {},
    )


class TestPolicyEngine:
    def test_default_allow(self):
        engine = PolicyEngine()
        event = _make_event()
        decision = engine.evaluate(event)
        assert decision.action == "allow"
        assert decision.matched is False

    def test_untrusted_memory_write_triggers_quarantine(self):
        engine = PolicyEngine()
        event = _make_event(
            event_type="tool_call",
            target="memory_store",
            trust_level="untrusted",
            metadata={"target_node_type": "memory"},
        )
        decision = engine.evaluate(event)
        assert decision.action == "quarantine"
        assert decision.matched is True
        assert decision.policy_id == "deny-untrusted-memory-write"

    def test_high_contamination_score_triggers_quarantine(self):
        engine = PolicyEngine()
        event = _make_event(contamination_score=0.85)
        decision = engine.evaluate(event)
        assert decision.action == "quarantine"
        assert decision.policy_id == "quarantine-high-contamination"

    def test_rag_poisoning_tag_triggers_alert(self):
        engine = PolicyEngine()
        event = _make_event(risk_tags=["rag_poisoning"])
        decision = engine.evaluate(event)
        assert decision.action == "alert"
        assert decision.policy_id == "alert-rag-poisoning"

    def test_higher_priority_policy_wins(self):
        custom = [
            {
                "policy_id": "low-prio-alert",
                "name": "Low priority alert",
                "priority": 100,
                "condition": {"risk_tags_any": ["test_tag"]},
                "action": "alert",
                "severity": "warning",
                "reason": "Low prio.",
            },
            {
                "policy_id": "high-prio-quarantine",
                "name": "High priority quarantine",
                "priority": 5,
                "condition": {"risk_tags_any": ["test_tag"]},
                "action": "quarantine",
                "severity": "critical",
                "reason": "High prio.",
            },
        ]
        engine = PolicyEngine(policies=custom)
        event = _make_event(risk_tags=["test_tag"])
        decision = engine.evaluate(event)
        assert decision.action == "quarantine"
        assert decision.policy_id == "high-prio-quarantine"

    def test_block_not_downgraded_by_policy(self):
        engine = PolicyEngine()
        event = _make_event(
            risk_tags=["rag_poisoning"],
            action_taken="block",
        )
        decision = engine.evaluate(event)
        assert decision.action == "block"
