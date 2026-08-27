import json

import pytest

from app.actions import ActionArgument, ActionRequest, EffectClass, SecurityDecision
from app.agents.base import BaseAgent
from app.experiments.artifacts import RunPackageWriter
from app.experiments.evaluator import FormalEvaluator
from app.experiments.runner import ExperimentRunner
from app.experiments.methods import METHOD_REGISTRY
from app.event_store import EventStore
from app.llm.base import LLMResponse
from app.message_bus import MessageBus
from app.provenance.models import ArtifactKind, ArtifactState
from app.runtime import RunEngine, RunManifest
from app.schemas import (
    DetectorPipelineConfig, EdgeConfig, ExperimentConfig, NodeConfig, TopologyConfig,
)


def _manifest(run_id: str, **updates) -> RunManifest:
    values = {"run_id": run_id, **updates}
    return RunManifest.from_mapping(values)


def _bind(context) -> MessageBus:
    bus = MessageBus()
    bus.bind_provenance_ledger(context.ledger, context.manifest.run_id)
    bus.bind_action_gateway(context.gateway)
    bus.bind_effect_sandbox(context.effect_sandbox)
    return bus


def test_formal_manifest_fails_closed_when_reproducibility_fields_are_missing():
    with pytest.raises(ValueError, match="formal manifest is incomplete"):
        RunManifest("formal-incomplete").validate_formal()

    manifest = _manifest(
        "formal-complete",
        experiment_id="exp-1",
        task_id="task-1",
        attack_id="attack-1",
        method_id="raise_asymmetric_v1",
        topology={"name": "canary"},
        model_role_assignment={"executor": "deterministic-stub"},
        prompt_hashes={"executor": "sha256:" + "1" * 64},
        tool_schema_hash="sha256:" + "2" * 64,
        component_versions={"runtime": "v1"},
        commit="deadbeef",
        environment_lock_hash="sha256:" + "3" * 64,
        sink_set=("sink:unit",),
    )
    manifest.validate_formal()
    assert manifest.to_dict()["schema_version"] == "majd-run-v1"


def test_method_registry_rejects_unknown_and_exposes_frozen_baselines():
    assert {
        "raise_asymmetric_v1", "b1_conservative", "b0_no_defense", "deny_all",
        "full_reset", "b1_frozen_majd_guard", "b7_simplified", "b7_faithful",
        "b9_naive_compose", "raise_conservative",
    }.issubset(
        set(METHOD_REGISTRY.available())
    )
    unavailable = {row["method_id"] for row in METHOD_REGISTRY.describe() if not row["available"]}
    assert "b7_faithful" in unavailable and "b7_simplified" in unavailable
    assert "b9_naive_compose" not in unavailable
    with pytest.raises(ValueError, match="unknown formal method_id"):
        METHOD_REGISTRY.get("unregistered-paper-baseline")


@pytest.mark.asyncio
async def test_unimplemented_faithful_method_is_explicitly_excluded(tmp_path):
    event_store = EventStore(tmp_path / "excluded.db")
    try:
        result = await ExperimentRunner(event_store).run(ExperimentConfig(
            name="excluded-method",
            metadata={"manifest": {"method_id": "b7_faithful"}},
        ))
    finally:
        await event_store.close()
    assert result.status.value == "excluded"
    assert "faithful paper implementation" in result.error_message


@pytest.mark.asyncio
async def test_live_sandbox_executes_e2_and_records_visible_context_inputs():
    context = RunEngine().create_run(_manifest("sandbox-live"))
    bus = _bind(context)
    clean = context.append_artifact(
        artifact_id="clean-input", kind=ArtifactKind.MESSAGE,
        value="approved", integrity="high", origin_principals={"gateway"},
    )
    context.effect_sandbox.register_tool(
        context.gateway, tool_id="calendar", operation="tool_call",
        effect_class=EffectClass.E2,
    )
    agent = BaseAgent(
        "planner", bus, tools=["calendar"],
        metadata={
            "tool_targets": ["calendar"],
            "downstream_effects": {"calendar": "E2"},
            "downstream_operations": {"calendar": "tool_call"},
            "tool_descriptions": {"tool_description:calendar": "Create a sandbox event"},
        },
    )

    event = await agent.call_tool(
        "calendar", "create event", artifact_refs=[clean.version_id], effect_class="E2"
    )

    assert event is not None
    assert context.effect_sandbox.side_effect_count == 1
    activities = context.ledger.list_activities(context.manifest.run_id)
    activity = next(item for item in activities if item.activity_id == f"activity_{event.event_id}")
    assert clean.version_id in activity.visible_input_ids
    assert any(item.startswith("ctx_") for item in activity.visible_input_ids)
    p1_parents = {
        parent
        for relation in context.ledger.list_derivations(context.manifest.run_id)
        if relation.child_version_id == f"event_{event.event_id}"
        and relation.provenance_level.value == "P1"
        for parent in relation.parent_version_ids
    }
    assert set(activity.visible_input_ids).issubset(p1_parents)


@pytest.mark.asyncio
async def test_dry_run_e2_has_zero_side_effects():
    context = RunEngine().create_run(_manifest("sandbox-dry", effect_mode="dry_run"))
    clean = context.append_artifact(
        artifact_id="clean", kind=ArtifactKind.MESSAGE, value="ok", integrity="high"
    )
    context.effect_sandbox.register_tool(
        context.gateway, tool_id="calendar", operation="tool_call",
        effect_class=EffectClass.E2,
    )
    request = ActionRequest(
        action_id="dry-e2", run_id=context.manifest.run_id,
        actor_agent_id="agent", tool_id="calendar", operation="tool_call",
        arguments=(ActionArgument(
            "payload", {"title": "test"}, (clean.version_id,), "content", "high"
        ),), effect_class=EffectClass.E2,
    )

    result = await context.gateway.submit(request)

    assert result.decision is SecurityDecision.DENY
    assert result.simulated_effect is True
    assert context.effect_sandbox.side_effect_count == 0


@pytest.mark.asyncio
async def test_live_e3_requires_and_accepts_fully_trusted_visible_inputs():
    context = RunEngine().create_run(_manifest("sandbox-live-e3"))
    bus = _bind(context)
    clean = context.append_artifact(
        artifact_id="approved-payment", kind=ArtifactKind.MESSAGE,
        value="approved", integrity="high",
    )
    context.effect_sandbox.register_tool(
        context.gateway, tool_id="payments", operation="capture",
        effect_class=EffectClass.E3, reversible=False,
    )
    agent = BaseAgent(
        "payer", bus, tools=["payments"], metadata={
            "tool_targets": ["payments"],
            "downstream_effects": {"payments": "E3"},
            "downstream_operations": {"payments": "capture"},
            "tool_descriptions": {"tool_description:payments": "Sandbox payment capture"},
        },
    )

    event = await agent.call_tool(
        "payments", "capture approved payment",
        artifact_refs=[clean.version_id], effect_class="E3",
    )

    assert event is not None and not event.metadata.get("gateway_denied", False)
    assert context.effect_sandbox.side_effect_count == 1


@pytest.mark.asyncio
async def test_contaminated_e3_is_blocked_before_sandbox_and_triggers_repair():
    context = RunEngine().create_run(_manifest("blocked-e3"))
    low = context.append_artifact(
        artifact_id="poison", kind=ArtifactKind.MESSAGE, value="poison", integrity="low"
    )
    sink = context.append_artifact(
        artifact_id="payment-argument", kind=ArtifactKind.ARGUMENT,
        value={"amount": 100}, integrity="high",
    )
    context.derive(sink, [low], activity_id="make-payment", effect_class="E3")
    context.effect_sandbox.register_tool(
        context.gateway, tool_id="payments", operation="capture",
        effect_class=EffectClass.E3, reversible=False,
    )
    request = ActionRequest(
        action_id="unsafe-payment", run_id=context.manifest.run_id,
        actor_agent_id="agent", tool_id="payments", operation="capture",
        arguments=(ActionArgument(
            "payload", {"unsafe": True}, (sink.version_id,), "content", "high"
        ),), effect_class=EffectClass.E3, reversible=False,
    )

    result = await context.gateway.submit(request)

    assert result.decision is SecurityDecision.DENY
    assert result.reason_code == "contaminated_provenance"
    assert context.effect_sandbox.side_effect_count == 0
    assert context.gateway.boundary_repair.outcomes
    assert context.ledger.metrics(context.manifest.run_id)["boundary_repairs"] == 1


@pytest.mark.asyncio
async def test_no_defense_baseline_produces_measurable_unsafe_escape():
    adapter = METHOD_REGISTRY.get("b0_no_defense")
    context = RunEngine().create_run(
        _manifest("b0-escape", method_id="b0_no_defense"),
        policy=adapter.build_policy(ExperimentConfig(name="b0")),
    )
    low = context.append_artifact(
        artifact_id="poison", kind=ArtifactKind.MESSAGE, value="poison", integrity="low"
    )
    sink = context.append_artifact(
        artifact_id="write-argument", kind=ArtifactKind.ARGUMENT, value="write", integrity="high"
    )
    context.derive(sink, [low], activity_id="unsafe-write", effect_class="E2")
    context.effect_sandbox.register_tool(
        context.gateway, tool_id="calendar", operation="tool_call",
        effect_class=EffectClass.E2,
    )
    request = ActionRequest(
        action_id="b0-write", run_id=context.manifest.run_id,
        actor_agent_id="agent", tool_id="calendar", operation="tool_call",
        arguments=(ActionArgument(
            "payload", "unsafe", (sink.version_id,), "content", "high"
        ),), effect_class=EffectClass.E2,
    )

    result = await context.gateway.submit(request)
    metrics = FormalEvaluator(
        events=[], ledger=context.ledger, manifest=context.manifest,
        sandbox_effects=context.effect_sandbox.effects,
    ).compute()

    assert result.decision is SecurityDecision.ALLOW
    assert metrics.unsafe_sink_escape == 1


@pytest.mark.asyncio
async def test_selective_recovery_creates_new_version_from_clean_inputs_only():
    context = RunEngine().create_run(_manifest("selective-recovery"))
    clean = context.append_artifact(
        artifact_id="clean", kind=ArtifactKind.MESSAGE, value="clean", integrity="high"
    )
    low = context.append_artifact(
        artifact_id="poison", kind=ArtifactKind.MESSAGE, value="poison", integrity="low"
    )
    sink = context.append_artifact(
        artifact_id="sink", kind=ArtifactKind.ARGUMENT, value="argument", integrity="high"
    )
    context.derive(sink, [clean, low], activity_id="mixed-derivation", effect_class="E2")

    outcome = await context.recovery_coordinator.recover(
        sink_versions={sink.version_id}, revoked_versions={low.version_id},
        required_goals={"goal-1"}, action_id="repair-1",
    )

    assert context.ledger.current_state(low.version_id) is ArtifactState.INVALIDATED
    assert outcome.success is True, outcome.failure_reasons
    assert len(outcome.replayed_versions) == 1
    recovered = context.ledger.get_artifact(outcome.replayed_versions[0])
    assert recovered is not None and recovered.version_id not in {clean.version_id, low.version_id}
    assert recovered.metadata["clean_input_ids"] == [clean.version_id]
    assert context.ledger.has_low_integrity_ancestor(recovered.version_id) is False


def test_run_package_is_complete_and_offline_metrics_recompute(tmp_path):
    manifest = _manifest(
        "package-run", experiment_id="package-exp", topology={"name": "unit"}
    )
    context = RunEngine().create_run(manifest)
    metrics = FormalEvaluator(
        events=[], ledger=context.ledger, manifest=manifest,
        sandbox_effects=context.effect_sandbox.effects,
    ).compute()

    package = RunPackageWriter(tmp_path).write(
        context=context, events=[], metrics=metrics, status="completed"
    )
    recomputed = RunPackageWriter.recompute(package)

    assert RunPackageWriter.REQUIRED_FILES.issubset(
        {path.name for path in package.iterdir()}
    )
    assert json.loads((package / "status.json").read_text(encoding="utf-8"))["status"] == "completed"
    for field in set(type(metrics).model_fields) - {"metadata"}:
        assert getattr(recomputed, field) == getattr(metrics, field)


@pytest.mark.asyncio
async def test_formal_runner_canary_uses_one_runtime_and_writes_run_package(tmp_path):
    class StubLLM:
        async def chat(self, _messages):
            return LLMResponse(
                content="create the approved calendar event",
                model="deterministic-stub", provider="test", latency_ms=1,
            )

    event_store = EventStore(tmp_path / "events.db")
    config = ExperimentConfig(
        name="formal-canary",
        topology=TopologyConfig(
            name="gateway-agent-tool",
            nodes=[
                NodeConfig(node_id="gateway", node_type="gateway"),
                NodeConfig(node_id="planner", node_type="agent"),
                NodeConfig(
                    node_id="calendar", node_type="tool",
                    metadata={"effect_class": "E2", "operation": "tool_call"},
                ),
            ],
            edges=[
                EdgeConfig(source="gateway", target="planner"),
                EdgeConfig(source="planner", target="calendar"),
                EdgeConfig(source="calendar", target="planner"),
            ],
            max_turns=1,
        ),
        detector_pipeline=DetectorPipelineConfig(),
        metadata={
            "formal_run": True,
            "artifact_root": str(tmp_path / "packages"),
            "manifest": {
                "model_role_assignment": {"executor": "deterministic-stub"},
                "prompt_hashes": {"planner": "sha256:" + "1" * 64},
                "tool_schema_hash": "sha256:" + "2" * 64,
                "component_versions": {"runtime": "v1"},
                "commit": "deadbeef",
                "environment_lock_hash": "sha256:" + "3" * 64,
                "attack_id": "canary-attack",
                "sink_set": ["calendar"],
            },
        },
    )
    try:
        result = await ExperimentRunner(event_store, llm_client=StubLLM()).run(config)
    finally:
        await event_store.close()

    assert result.status.value == "completed", result.error_message
    assert result.metrics.sandbox_side_effects == 1
    packages = list((tmp_path / "packages").glob("*/*"))
    assert len(packages) == 1
    assert RunPackageWriter.REQUIRED_FILES.issubset(
        {path.name for path in packages[0].iterdir()}
    )
