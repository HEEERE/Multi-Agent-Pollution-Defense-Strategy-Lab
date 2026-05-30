import pytest

from app.defense.base import DefenseContext
from app.defense.schemas import DefenderVerdict
from app.detectors.pipeline import DetectorPipeline
from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventSeverity,
    EventStatus,
)


def _make_event(
    source: str = "Red_Attacker",
    target: str = "Task_Agent_A",
    event_type: str = "input",
    severity: str = "info",
    action_taken: str = "none",
    contamination_score: float = 0.0,
    risk_tags: list[str] | None = None,
    trust_level: str = "unknown",
) -> AgentEvent:
    return AgentEvent(
        event_id="evt_test",
        trace_id="trace_test",
        event_type=event_type,
        source_node=source,
        target_node=target,
        payload_snippet="test payload",
        severity=severity,
        action_taken=action_taken,
        contamination_score=contamination_score,
        risk_tags=risk_tags or [],
        trust_level=trust_level,
    )


class StubCoordinator:
    def __init__(self):
        self.evaluated = False
        self.decision_applied = False
        self.final_action = "allow"

    async def evaluate(self, event):
        self.evaluated = True
        from app.defense.schemas import JointDefenseDecision
        return JointDefenseDecision(
            decision_id="jdd_stub",
            source_event_id=event.event_id,
            trace_id=event.trace_id,
            final_action=self.final_action,
            confidence=0.5,
            votes=[],
            consensus_type="fallback",
            rationale="stub",
        )

    def apply_decision(self, event, decision):
        self.decision_applied = True
        return event.model_copy(update={
            "status": EventStatus.QUARANTINED,
            "action_taken": ActionTaken.BLOCK,
            "severity": EventSeverity.CRITICAL,
            "trust_level": "untrusted",
            "metadata": {
                **event.metadata,
                "joint_defense": decision.model_dump(mode="json"),
            },
        })


class NoopDetector:
    def __init__(self, detector_id="noop", level=None):
        self.detector_id = detector_id
        from app.schemas import MonitorLevel
        self.level = level if level is not None else MonitorLevel.HEURISTIC

    async def detect(self, event, context):
        from app.detectors.base import DetectionResult
        from app.schemas import ActionTaken, MonitorLevel
        return DetectionResult(
            is_threat=False,
            confidence=0.1,
            reason="noop",
            suggested_action=ActionTaken.NONE,
            level=MonitorLevel.HEURISTIC,
        )


class ThreatDetector:
    def __init__(self, detector_id="threat", level=None):
        self.detector_id = detector_id
        from app.schemas import MonitorLevel
        self.level = level if level is not None else MonitorLevel.HEURISTIC

    async def detect(self, event, context):
        from app.detectors.base import DetectionResult
        from app.schemas import ActionTaken, MonitorLevel
        return DetectionResult(
            is_threat=True,
            confidence=0.85,
            reason="detected threat",
            suggested_action=ActionTaken.BLOCK,
            level=MonitorLevel.HEURISTIC,
        )


class TestPipelineJointDefense:
    def test_low_risk_event_skips_joint_defense(self):
        coordinator = StubCoordinator()
        pipeline = DetectorPipeline(
            detectors=[NoopDetector()],
            defense_coordinator=coordinator,
            bus=None,
        )
        event = _make_event(severity="info", action_taken="none")

        import asyncio
        result = asyncio.run(pipeline.inspect(event))

        assert result is not None
        assert coordinator.evaluated is False

    def test_detector_suspicious_event_invokes_coordinator(self):
        coordinator = StubCoordinator()
        pipeline = DetectorPipeline(
            detectors=[ThreatDetector()],
            defense_coordinator=coordinator,
            bus=None,
        )
        event = _make_event()

        import asyncio
        result = asyncio.run(pipeline.inspect(event))

        assert result is not None
        assert coordinator.evaluated is True
        assert coordinator.decision_applied is True

    def test_already_warning_event_invokes_coordinator(self):
        coordinator = StubCoordinator()
        pipeline = DetectorPipeline(
            detectors=[NoopDetector()],
            defense_coordinator=coordinator,
            bus=None,
        )
        event = _make_event(severity="warning", contamination_score=0.4)

        import asyncio
        result = asyncio.run(pipeline.inspect(event))

        assert result is not None
        assert coordinator.evaluated is True

    def test_untrusted_event_invokes_coordinator(self):
        coordinator = StubCoordinator()
        pipeline = DetectorPipeline(
            detectors=[NoopDetector()],
            defense_coordinator=coordinator,
            bus=None,
        )
        event = _make_event(trust_level="untrusted")

        import asyncio
        result = asyncio.run(pipeline.inspect(event))

        assert result is not None
        assert coordinator.evaluated is True

    def test_joint_block_status_reflected_in_event(self):
        coordinator = StubCoordinator()
        coordinator.final_action = "block"
        pipeline = DetectorPipeline(
            detectors=[NoopDetector()],
            defense_coordinator=coordinator,
            bus=None,
        )
        event = _make_event(severity="warning", contamination_score=0.4)

        import asyncio
        result = asyncio.run(pipeline.inspect(event))

        assert result is not None
        assert result.action_taken == ActionTaken.BLOCK
        assert "joint_defense" in result.metadata

    def test_pipeline_works_without_coordinator(self):
        """Backward compatibility: pipeline with no coordinator works as before."""
        pipeline = DetectorPipeline(
            detectors=[NoopDetector()],
            defense_coordinator=None,
            bus=None,
        )
        event = _make_event()

        import asyncio
        result = asyncio.run(pipeline.inspect(event))

        assert result is not None
        assert result.action_taken == ActionTaken.NONE
