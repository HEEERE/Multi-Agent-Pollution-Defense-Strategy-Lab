"""Executable acceptance tests for Phase 6 FR-001..015 and NFR-001..008.

This module concentrates requirements that were previously uncovered.  The
traceability matrix also references stronger pre-existing mechanism tests where
duplicating a large oracle scenario here would reduce, rather than improve,
clarity.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import stat

import pytest

from app.actions import (
    ActionArgument,
    ActionRequest,
    DeterministicPolicy,
    EffectClass,
    SecurityDecision,
)
from app.event_store import EventStore
from app.experiments.artifacts import RunPackageWriter
from app.experiments.evaluator import FormalEvaluator
from app.experiments.external_archive import ExternalRawArchive
from app.experiments.methods import METHOD_REGISTRY
from app.experiments.runner import ExperimentRunner
from app.provenance.models import ArtifactKind, ArtifactState
from app.research.scale.graph import GenSpec, generate
from app.runtime import RunEngine, RunManifest
from app.schemas import ExperimentConfig, ExperimentMetrics, TopologyConfig


BACKEND = Path(__file__).resolve().parent.parent


def _manifest(run_id: str, **updates) -> RunManifest:
    return RunManifest.from_mapping({"run_id": run_id, **updates})


def _hash_files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _package_context(run_id: str, experiment_id: str = "requirements"):
    manifest = _manifest(
        run_id, experiment_id=experiment_id,
        topology={"name": "requirements"}, sink_set=("sink",),
    )
    context = RunEngine().create_run(manifest)
    metrics = FormalEvaluator(
        events=[], ledger=context.ledger, manifest=manifest,
        sandbox_effects=context.effect_sandbox.effects,
    ).compute()
    return context, metrics


@pytest.mark.asyncio
async def test_fr002_concurrent_runs_do_not_share_ledger_queue_state_or_actions():
    first = RunEngine().create_run(_manifest("isolated-first"))
    second = RunEngine().create_run(_manifest("isolated-second"))
    assert first.ledger is not second.ledger
    assert first.boundary_queue is not second.boundary_queue
    assert first.state_controller is not second.state_controller
    assert first.effect_sandbox is not second.effect_sandbox

    async def execute(context, suffix):
        artifact = context.append_artifact(
            artifact_id=f"input-{suffix}", kind=ArtifactKind.MESSAGE,
            value=suffix, integrity="high",
        )
        context.effect_sandbox.register_tool(
            context.gateway, tool_id="memory", operation="write",
            effect_class=EffectClass.E1,
        )
        result = await context.gateway.submit(ActionRequest(
            action_id=f"action-{suffix}", run_id=context.manifest.run_id,
            actor_agent_id=f"agent-{suffix}", tool_id="memory", operation="write",
            arguments=(ActionArgument(
                "payload", {"value": suffix}, (artifact.version_id,),
                "content", "high",
            ),),
            effect_class=EffectClass.E1,
        ))
        return artifact, result

    (artifact_a, result_a), (artifact_b, result_b) = await asyncio.gather(
        execute(first, "a"), execute(second, "b")
    )
    assert result_a.decision is result_b.decision is SecurityDecision.ALLOW
    assert first.ledger.get_artifact(artifact_b.version_id) is None
    assert second.ledger.get_artifact(artifact_a.version_id) is None
    assert {row["action_id"] for row in first.ledger.list_action_records("isolated-first")} == {"action-a"}
    assert {row["action_id"] for row in second.ledger.list_action_records("isolated-second")} == {"action-b"}
    first.transition(artifact_a, ArtifactState.QUARANTINED, "run-a-only")
    assert second.ledger.current_state(artifact_b.version_id) is ArtifactState.ACTIVE


@pytest.mark.asyncio
async def test_fr003_protected_sandbox_effect_cannot_bypass_action_gateway():
    context = RunEngine().create_run(_manifest("gateway-only"))
    artifact = context.append_artifact(
        artifact_id="approved", kind=ArtifactKind.MESSAGE,
        value="approved", integrity="high",
    )
    context.effect_sandbox.register_tool(
        context.gateway, tool_id="calendar", operation="create",
        effect_class=EffectClass.E2,
    )
    request = ActionRequest(
        action_id="calendar-create", run_id=context.manifest.run_id,
        actor_agent_id="planner", tool_id="calendar", operation="create",
        arguments=(ActionArgument(
            "payload", {"title": "meeting"}, (artifact.version_id,),
            "content", "high",
        ),),
        effect_class=EffectClass.E2,
    )

    with pytest.raises(PermissionError, match="ActionGateway"):
        context.effect_sandbox._execute(request)
    assert context.effect_sandbox.side_effect_count == 0

    result = await context.gateway.submit(request)
    assert result.decision is SecurityDecision.ALLOW
    assert result.executed is True
    assert context.effect_sandbox.side_effect_count == 1


@pytest.mark.asyncio
async def test_fr006_every_effect_contract_mismatch_is_rejected():
    policy = DeterministicPolicy(
        capabilities={"agent": {"write"}}, scopes={"agent": {"tenant-a"}}
    )
    context = RunEngine().create_run(_manifest("contract-matrix"), policy=policy)
    artifact = context.append_artifact(
        artifact_id="approved", kind=ArtifactKind.MESSAGE,
        value="approved", integrity="high",
    )
    context.effect_sandbox.register_tool(
        context.gateway, tool_id="calendar", operation="create",
        effect_class=EffectClass.E2, resource_scopes={"tenant-a"},
        required_capabilities={"write"}, reversible=True,
        required_integrity="high",
    )

    def request(action_id: str, **changes) -> ActionRequest:
        values = {
            "action_id": action_id,
            "run_id": context.manifest.run_id,
            "actor_agent_id": "agent",
            "tool_id": "calendar",
            "operation": "create",
            "arguments": (ActionArgument(
                "payload", {"title": "meeting"}, (artifact.version_id,),
                "content", "high",
            ),),
            "capability_requested": frozenset({"write"}),
            "resource_scope": "tenant-a",
            "effect_class": EffectClass.E2,
            "reversible": True,
        }
        values.update(changes)
        return ActionRequest(**values)

    allowed = await context.gateway.submit(request("valid-contract"))
    assert allowed.decision is SecurityDecision.ALLOW
    assert context.effect_sandbox.side_effect_count == 1

    cases = (
        (request("wrong-effect", effect_class=EffectClass.E1), "effect_contract_mismatch"),
        (request("wrong-capability", capability_requested=frozenset()), "required_capability_missing"),
        (request("wrong-scope", resource_scope="tenant-b"), "contract_resource_out_of_scope"),
        (request("wrong-reversible", reversible=False), "reversibility_contract_mismatch"),
        (request(
            "wrong-role", arguments=(ActionArgument(
                "payload", {}, (artifact.version_id,), "authority", "high"
            ),)
        ), "argument_role_mismatch"),
    )
    for candidate, reason in cases:
        result = await context.gateway.submit(candidate)
        assert result.decision is not SecurityDecision.ALLOW
        assert result.reason_code == reason
    assert context.effect_sandbox.side_effect_count == 1


@pytest.mark.asyncio
async def test_fr007_dry_run_and_selective_replay_create_no_e2_e3_effects():
    for effect in (EffectClass.E2, EffectClass.E3):
        context = RunEngine().create_run(
            _manifest(f"dry-{effect.value}", effect_mode="dry_run")
        )
        artifact = context.append_artifact(
            artifact_id="approved", kind=ArtifactKind.MESSAGE,
            value="approved", integrity="high",
        )
        context.effect_sandbox.register_tool(
            context.gateway, tool_id="external", operation="commit",
            effect_class=effect, reversible=effect is not EffectClass.E3,
            required_integrity="high",
        )
        result = await context.gateway.submit(ActionRequest(
            action_id=f"dry-{effect.value}", run_id=context.manifest.run_id,
            actor_agent_id="agent", tool_id="external", operation="commit",
            arguments=(ActionArgument(
                "payload", {"value": "x"}, (artifact.version_id,),
                "content", "high",
            ),), effect_class=effect, reversible=effect is not EffectClass.E3,
        ))
        assert result.reason_code == "dry_run_external_effect"
        assert context.effect_sandbox.side_effect_count == 0

    replay = RunEngine().create_run(_manifest("replay-no-external-effect"))
    replay.append_artifact(
        artifact_id="clean", kind=ArtifactKind.MESSAGE,
        value="clean", integrity="high",
    )
    outcome = await replay.recovery_coordinator.recover(
        sink_versions=set(), revoked_versions=set(),
        required_goals={"required-goal"}, action_id="replay",
    )
    assert outcome.replayed_versions
    assert replay.effect_sandbox.side_effect_count == 0


@pytest.mark.asyncio
async def test_fr013_same_case_switches_every_registered_method_without_silent_substitution(tmp_path):
    store = EventStore(tmp_path / "method-switch.db")
    observed = {}
    try:
        for method in METHOD_REGISTRY.describe():
            result = await ExperimentRunner(store).run(ExperimentConfig(
                name="same-empty-case",
                topology=TopologyConfig(name="empty", max_turns=0),
                metadata={"manifest": {"method_id": method["method_id"]}},
            ))
            observed[method["method_id"]] = result.status.value
            persisted = await store.get_experiment(result.experiment_id)
            assert persisted is not None
            assert persisted["status"] == result.status.value
            if method["available"]:
                assert result.status.value == "completed"
                assert result.metrics.metadata["n_runs"] == 1
            else:
                assert result.status.value == "excluded"
                assert method["unavailable_reason"] in result.error_message
    finally:
        await store.close()
    assert set(observed) == set(METHOD_REGISTRY.available())


@pytest.mark.asyncio
async def test_fr014_failure_timeout_unknown_and_excluded_statuses_roundtrip(tmp_path):
    store = EventStore(tmp_path / "terminal-statuses.db")
    statuses = ("failed", "timeout", "unknown", "excluded")
    try:
        for index, status in enumerate(statuses):
            run_id = f"terminal-{status}"
            await store.store_run({
                "run_id": run_id, "status": status,
                "error": f"reason:{status}", "created_at": index + 1,
                "finished_at": index + 2,
            })
            row = await store.get_run(run_id)
            assert row is not None
            assert row["status"] == status
            assert row["error"] == f"reason:{status}"
            assert row["finished_at"] == index + 2
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_fr014_runner_enforces_wall_clock_budget_and_persists_timeout(tmp_path):
    store = EventStore(tmp_path / "runner-timeout.db")
    try:
        result = await ExperimentRunner(store).run(ExperimentConfig(
            name="timeout-case",
            topology=TopologyConfig(name="timeout", max_turns=1),
            metadata={
                "manifest": {
                    "method_id": "raise_asymmetric_v1",
                    "budget": {"wall_clock_s": 0},
                }
            },
        ))
        persisted = await store.get_experiment(result.experiment_id)
    finally:
        await store.close()
    assert result.status.value == "timeout"
    assert "wall-clock budget" in result.error_message
    assert persisted is not None and persisted["status"] == "timeout"


def test_fr015_external_official_raw_output_is_write_once_and_checksummed(tmp_path):
    archive = ExternalRawArchive(tmp_path / "外部 Benchmark 原始包")
    raw = "官方结果：安全\n".encode("utf-8")
    path = archive.archive_bytes(
        benchmark_id="AgentDojo-workspace",
        run_id="trial-001", filename="official-output.json", content=raw,
    )
    assert ExternalRawArchive.verify(path)
    metadata = json.loads(
        (path / ExternalRawArchive.METADATA).read_text(encoding="utf-8")
    )
    assert metadata["sha256"] == hashlib.sha256(raw).hexdigest()
    assert not ((path / metadata["filename"]).stat().st_mode & stat.S_IWUSR)
    with pytest.raises(FileExistsError):
        archive.archive_bytes(
            benchmark_id="AgentDojo-workspace", run_id="trial-001",
            filename="official-output.json", content=b"replacement",
        )
    # Restore write bits so Windows can clean the pytest temporary directory.
    for item in path.iterdir():
        item.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_nfr001_same_manifest_seed_replays_deterministic_graph_exactly():
    manifest = _manifest(
        "deterministic-replay", experiment_id="deterministic",
        topology={"name": "graph"}, seed=42,
    )
    spec = GenSpec(context_size=4, hops=3, n_sinks=2, seed=manifest.seed)
    first = generate(spec, conservative=True)
    second = generate(spec, conservative=True)
    assert manifest.to_dict() == RunManifest.from_mapping(manifest.to_dict()).to_dict()
    assert first.versions == second.versions
    assert first.derivations == second.derivations
    assert first.sinks == second.sinks
    assert first.interventions == second.interventions
    assert first.support == second.support


def test_nfr002_run_package_commits_complete_directory_or_failed_status(tmp_path, monkeypatch):
    context, metrics = _package_context("atomic-success", "atomic")
    writer = RunPackageWriter(tmp_path / "packages")
    package = writer.write(context=context, events=[], metrics=metrics)
    assert RunPackageWriter.REQUIRED_FILES.issubset(
        {path.name for path in package.iterdir()}
    )
    assert not list(package.parent.glob(".*.staging"))

    failed_context, failed_metrics = _package_context("atomic-failure", "atomic")
    failed_writer = RunPackageWriter(tmp_path / "packages")

    def explode(*_args, **_kwargs):
        raise OSError("injected package failure")

    monkeypatch.setattr(failed_writer, "_populate", explode)
    with pytest.raises(OSError, match="injected package failure"):
        failed_writer.write(
            context=failed_context, events=[], metrics=failed_metrics
        )
    failed_package = tmp_path / "packages" / "atomic" / "atomic-failure"
    status = json.loads(
        (failed_package / "status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "failed"
    assert "injected package failure" in status["error"]
    assert not list(failed_package.parent.glob(".*.staging"))


def test_nfr003_formal_manifest_rejects_placeholder_versions_and_hashes():
    manifest = _manifest(
        "bad-hashes", experiment_id="formal", layer="E", task_id="task",
        attack_id="attack", method_id="raise_asymmetric_v1",
        topology={"name": "formal"},
        model_role_assignment={"executor": "model-snapshot-2026-08-25"},
        prompt_hashes={"executor": "sha256:placeholder"},
        tool_schema_hash="sha256:placeholder", policy_version="v1",
        component_versions={"runtime": "majd-run-v1"}, commit="deadbeef",
        environment_lock_hash="sha256:placeholder", sink_set=("sink",),
    )
    with pytest.raises(ValueError, match="exact sha256"):
        manifest.validate_formal()


def test_nfr004_recompute_is_read_only_and_summary_is_separate(tmp_path):
    context, metrics = _package_context("raw-read-only", "raw-summary")
    package = RunPackageWriter(tmp_path / "raw").write(
        context=context, events=[], metrics=metrics
    )
    before = _hash_files(package)
    output = RunPackageWriter.write_summary(
        package, tmp_path / "summary" / "metrics.json"
    )
    assert output.is_file()
    assert _hash_files(package) == before
    assert package not in output.parents
    with pytest.raises(ValueError, match="outside"):
        RunPackageWriter.write_summary(package, package / "summary.json")
    with pytest.raises(FileExistsError):
        RunPackageWriter.write_summary(package, output)


def test_nfr007_tests_and_unicode_windows_style_paths_are_utf8_without_bom(tmp_path):
    for path in sorted((BACKEND / "tests").glob("*.py")):
        content = path.read_bytes()
        assert not content.startswith(b"\xef\xbb\xbf"), path
        content.decode("utf-8")

    root = tmp_path / "Windows 路径 含空格"
    context, metrics = _package_context("utf8-run", "中文实验")
    package = RunPackageWriter(root).write(
        context=context, events=[], metrics=metrics
    )
    manifest_bytes = (package / "manifest.yaml").read_bytes()
    assert not manifest_bytes.startswith(b"\xef\xbb\xbf")
    assert json.loads(manifest_bytes.decode("utf-8"))["experiment_id"] == "中文实验"


@pytest.mark.asyncio
async def test_nfr008_sandbox_is_trial_scoped_local_and_resettable():
    first = RunEngine().create_run(_manifest("sandbox-trial-a"))
    second = RunEngine().create_run(_manifest("sandbox-trial-b"))
    artifact = first.append_artifact(
        artifact_id="approved", kind=ArtifactKind.MESSAGE,
        value="approved", integrity="high",
    )
    first.effect_sandbox.register_tool(
        first.gateway, tool_id="ticket", operation="create",
        effect_class=EffectClass.E2,
    )
    result = await first.gateway.submit(ActionRequest(
        action_id="ticket-a", run_id=first.manifest.run_id,
        actor_agent_id="agent", tool_id="ticket", operation="create",
        arguments=(ActionArgument(
            "payload", {"title": "local"}, (artifact.version_id,),
            "content", "high",
        ),), effect_class=EffectClass.E2,
    ))
    assert result.executed is True
    assert first.effect_sandbox.side_effect_count == 1
    assert second.effect_sandbox.side_effect_count == 0
    assert first.effect_sandbox.snapshot()["run_id"] == "sandbox-trial-a"
    first.effect_sandbox.reset()
    assert first.effect_sandbox.snapshot() == {
        "run_id": "sandbox-trial-a",
        "mutable_state": {}, "commitments": [], "effects": [],
    }
