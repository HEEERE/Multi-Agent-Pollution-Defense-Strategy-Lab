import pytest

from app.detectors.factory import create_pipeline
from app.experiments.runner import ExperimentRunner
from app.message_bus import MessageBus
from app.policy.engine import PolicyEngine
from app.schemas import (
    ActionTaken,
    AgentEvent,
    DetectorPipelineConfig,
    EdgeConfig,
    EventStatus,
    ExperimentConfig,
    TopologyConfig,
)
from app.strategy.compiler import compile_strategy


@pytest.mark.asyncio
async def test_topology_edges_block_undeclared_routes_and_record_monitors():
    bus = MessageBus()
    bus.bind_topology(
        [EdgeConfig(source="gateway", target="agent_a")],
        monitors=["auditor"],
    )

    allowed = await bus.publish(
        AgentEvent(
            event_type="input",
            source_node="gateway",
            target_node="agent_a",
            payload_snippet="allowed",
        )
    )
    blocked = await bus.publish(
        AgentEvent(
            event_type="input",
            source_node="gateway",
            target_node="agent_b",
            payload_snippet="undeclared edge",
        )
    )

    assert allowed.metadata["topology_monitors"] == ["auditor"]
    assert allowed.action_taken == ActionTaken.NONE
    assert blocked.action_taken == ActionTaken.BLOCK
    assert blocked.metadata["topology_blocked"] is True


@pytest.mark.asyncio
async def test_compiled_user_policy_is_enforced():
    config = compile_strategy(
        {
            "topology": {"nodes": [{"node_id": "gateway", "node_type": "gateway"}]},
            "policies": [
                {
                    "policy_id": "user-block",
                    "action": "block",
                    "condition": {"min_contamination_score": 0.4},
                }
            ],
        }
    )
    pipeline = create_pipeline(
        config.detector_pipeline,
        policy_engine=PolicyEngine(config.metadata["policies"]),
    )
    result = await pipeline.inspect(
        AgentEvent(
            event_type="input",
            source_node="gateway",
            target_node="agent",
            payload_snippet="policy test",
            contamination_score=0.8,
        )
    )

    assert result.action_taken == ActionTaken.BLOCK
    assert result.policy_id == "user-block"


class FakeExperimentStore:
    def __init__(self):
        self.experiments: list[dict] = []

    async def store_experiment(self, value: dict) -> None:
        self.experiments.append(value)


@pytest.mark.asyncio
async def test_num_runs_generates_multiple_traces_and_aggregate(monkeypatch):
    counter = 0

    class StubEngine:
        def __init__(self, bus, llm_client):
            pass

        async def run_experiment(self, config, label_sink=None):
            nonlocal counter
            counter += 1
            event_id = f"event-{counter}"
            # Labels go to the write-only oracle sink, never into metadata.
            if label_sink is not None:
                label_sink(event_id, False, "benign")
            return [
                AgentEvent(
                    event_id=event_id,
                    trace_id=f"trace-{counter}",
                    event_type="input",
                    source_node="gateway",
                    target_node="agent",
                    payload_snippet="safe",
                    status=EventStatus.SAFE,
                    metadata={},
                )
            ]

    monkeypatch.setattr("app.experiments.runner.SimulationEngine", StubEngine)
    config = ExperimentConfig(
        name="repeated",
        topology=TopologyConfig(),
        detector_pipeline=DetectorPipelineConfig(),
        num_runs=3,
        metadata={"seed": 7, "policies": []},
    )
    result = await ExperimentRunner(FakeExperimentStore(), llm_client=None).run(config)

    assert result.status.value == "completed"
    assert result.metrics.metadata["n_runs"] == 3
    assert result.metrics.metadata["trace_ids"] == ["trace-1", "trace-2", "trace-3"]
    assert result.metrics.metadata["seed"] == 7
