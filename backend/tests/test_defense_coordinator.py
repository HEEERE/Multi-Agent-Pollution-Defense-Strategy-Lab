import pytest

from app.defense.base import DefenseContext
from app.defense.schemas import DefenderVerdict
from app.defense.threat_memory import ThreatMemory
from app.schemas import ActionTaken, AgentEvent, EventStatus, EventSeverity


def _make_event(
    source: str = "Red_Attacker",
    target: str = "Task_Agent_A",
    event_type: str = "input",
    trace_id: str = "trace_test",
    severity: str = "warning",
    action_taken: str = "alert",
    contamination_score: float = 0.5,
    risk_tags: list[str] | None = None,
    metadata: dict | None = None,
) -> AgentEvent:
    return AgentEvent(
        event_id="evt_test",
        trace_id=trace_id,
        event_type=event_type,
        source_node=source,
        target_node=target,
        payload_snippet="test payload",
        severity=severity,
        action_taken=action_taken,
        contamination_score=contamination_score,
        risk_tags=risk_tags or [],
        metadata=metadata or {},
    )


class StubDefender:
    def __init__(self, defender_id: str, role: str, verdict: str, confidence: float, recommended_action: str = "allow"):
        self.defender_id = defender_id
        self.role = role
        self.weight = 1.0
        self._verdict = verdict
        self._confidence = confidence
        self._action = recommended_action

    async def evaluate(self, event, context):
        return DefenderVerdict(
            defender_id=self.defender_id,
            role=self.role,
            verdict=self._verdict,
            confidence=self._confidence,
            evidence=[f"stub: {self._verdict}"],
            recommended_action=self._action,
            weight=self.weight,
        )


class FailingDefender:
    def __init__(self, defender_id: str):
        self.defender_id = defender_id
        self.role = "failing"
        self.weight = 0.0

    async def evaluate(self, event, context):
        raise RuntimeError("simulated failure")


class TestDefenseCoordinator:
    def test_coordinator_collects_all_votes(self):
        from app.defense.coordinator import DefenseCoordinator

        defenders = [
            StubDefender("d1", "guard1", "safe", 0.9),
            StubDefender("d2", "guard2", "suspicious", 0.6, "alert"),
            StubDefender("d3", "guard3", "safe", 0.85),
        ]
        coordinator = DefenseCoordinator(defenders=defenders, bus=None)
        event = _make_event()

        import asyncio
        decision = asyncio.run(coordinator.evaluate(event))

        assert decision is not None
        assert len(decision.votes) == 3
        assert decision.votes[0].defender_id == "d1"
        assert decision.votes[1].defender_id == "d2"
        assert decision.votes[2].defender_id == "d3"

    def test_coordinator_handles_defender_exception_as_unknown(self):
        from app.defense.coordinator import DefenseCoordinator

        defenders = [
            StubDefender("d1", "guard1", "safe", 0.9),
            FailingDefender("d2"),
            StubDefender("d3", "guard3", "safe", 0.85),
        ]
        coordinator = DefenseCoordinator(defenders=defenders, bus=None)
        event = _make_event()

        import asyncio
        decision = asyncio.run(coordinator.evaluate(event))

        assert decision is not None
        assert len(decision.votes) == 3
        d2_vote = next(v for v in decision.votes if v.defender_id == "d2")
        assert d2_vote.verdict == "unknown"
        assert d2_vote.confidence == 0.0

    def test_joint_decision_written_to_event_metadata(self):
        from app.defense.coordinator import DefenseCoordinator

        defenders = [
            StubDefender("d1", "guard1", "safe", 0.9),
        ]
        coordinator = DefenseCoordinator(defenders=defenders, bus=None)
        event = _make_event()

        import asyncio
        decision = asyncio.run(coordinator.evaluate(event))
        modified = coordinator.apply_decision(event, decision)

        assert "joint_defense" in modified.metadata
        assert modified.metadata["joint_defense"]["decision_id"] == decision.decision_id

    def test_block_action_sets_quarantined_status(self):
        from app.defense.coordinator import DefenseCoordinator
        from app.defense.schemas import JointDefenseDecision

        coordinator = DefenseCoordinator(defenders=[], bus=None)
        event = _make_event()
        decision = JointDefenseDecision(
            decision_id="jdd_test",
            source_event_id=event.event_id,
            trace_id=event.trace_id,
            final_action="block",
            confidence=0.9,
            votes=[],
            consensus_type="veto",
            rationale="test block",
        )
        modified = coordinator.apply_decision(event, decision)
        assert modified.status == EventStatus.QUARANTINED
        assert modified.action_taken == ActionTaken.BLOCK
        assert modified.severity == EventSeverity.CRITICAL
        assert modified.trust_level == "untrusted"
        assert modified.contamination_score >= 0.75

    def test_isolate_action_sets_isolated_status(self):
        from app.defense.coordinator import DefenseCoordinator
        from app.defense.schemas import JointDefenseDecision

        coordinator = DefenseCoordinator(defenders=[], bus=None)
        event = _make_event()
        decision = JointDefenseDecision(
            decision_id="jdd_test",
            source_event_id=event.event_id,
            trace_id=event.trace_id,
            final_action="isolate",
            confidence=0.95,
            votes=[],
            consensus_type="weighted",
            rationale="test isolate",
        )
        modified = coordinator.apply_decision(event, decision)
        assert modified.status == EventStatus.ISOLATED
        assert modified.action_taken == ActionTaken.ISOLATE
        assert modified.contamination_score >= 0.9

    def test_decoy_action_sets_honeypotted_status(self):
        from app.defense.coordinator import DefenseCoordinator
        from app.defense.schemas import JointDefenseDecision

        coordinator = DefenseCoordinator(defenders=[], bus=None)
        event = _make_event()
        decision = JointDefenseDecision(
            decision_id="jdd_test",
            source_event_id=event.event_id,
            trace_id=event.trace_id,
            final_action="decoy",
            confidence=0.55,
            votes=[],
            consensus_type="weighted",
            rationale="test decoy",
        )
        modified = coordinator.apply_decision(event, decision)
        assert modified.status == EventStatus.HONEYPOTTED
        assert modified.action_taken == ActionTaken.DECOY

    def test_threat_memory_records_decision(self):
        from app.defense.coordinator import DefenseCoordinator

        tm = ThreatMemory()
        coordinator = DefenseCoordinator(defenders=[], bus=None, threat_memory=tm)
        event = _make_event()

        import asyncio
        decision = asyncio.run(coordinator.evaluate(event))

        assert len(tm.recent_decisions) >= 1
        assert tm.recent_decisions[-1]["decision_id"] == decision.decision_id
