from __future__ import annotations

import pytest

from app.actions import ActionArgument, ActionGateway, ActionRequest, DeterministicPolicy, EffectClass, SecurityDecision, estimate_human_approval_cost
from app.provenance import ProvenanceLedger
from app.provenance.models import ArtifactKind, ArtifactState, ArtifactVersion, Derivation, ProvenanceLevel, StateTransition, SupportGroup
from app.provenance.projection import build_conservative, build_tight
from app.runtime import RunEngine, RunManifest
from app.verification import CertificateChecker, ReissuePolicy, ResidualChecker, RuntimeCheckStatus, RuntimeWitnessChecker


def _artifact(run_id: str, vid: str, integrity: str) -> ArtifactVersion:
    return ArtifactVersion(vid, vid, run_id, ArtifactKind.MESSAGE, vid, frozenset(), integrity)


def test_ledger_is_append_only_and_snapshot_changes_on_state_transition():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    source = ledger.append_artifact(_artifact("r1", "v1", "low"))
    child = ledger.append_artifact(_artifact("r1", "v2", "high"))
    ledger.append_derivation(Derivation("d1", "r1", child.version_id, (source.version_id,), "a1"))
    before = ledger.snapshot("r1")
    ledger.transition_state(StateTransition("s1", "r1", "v1", ArtifactState.ACTIVE, ArtifactState.QUARANTINED, 0, "test"))
    after = ledger.snapshot("r1")
    assert before.snapshot_hash != after.snapshot_hash
    assert ledger.current_state("v1") is ArtifactState.QUARANTINED
    assert ledger.get_artifact("v1").integrity == "low"
    assert ledger._conn.execute("SELECT COUNT(*) FROM state_transitions").fetchone()[0] == 3


def test_dual_graphs_keep_tight_edges_and_conservative_visible_inputs():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    low = ledger.append_artifact(_artifact("r1", "low", "low"))
    clean = ledger.append_artifact(_artifact("r1", "clean", "high"))
    out = ledger.append_artifact(_artifact("r1", "out", "high"))
    ledger.append_derivation(Derivation("d1", "r1", "out", ("clean",), "a1", "derived_from"))
    conservative = build_conservative(ledger, "r1", visible_inputs={"out": ("low",)})
    tight = build_tight(ledger, "r1")
    assert conservative.parents("out") == {"clean", "low"}
    assert tight.parents("out") == {"clean"}


def test_verified_support_is_conservative_and_only_p0_support_is_tight():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    ledger.append_artifact(_artifact("r1", "member", "high"))
    ledger.append_artifact(_artifact("r1", "goal", "high"))
    ledger.append_support_group(SupportGroup(
        "s1", "r1", "goal", ("member",), "verifier", True,
        ProvenanceLevel.P1,
    ))
    assert build_conservative(ledger, "r1").parents("goal") == {"member"}
    assert build_tight(ledger, "r1").parents("goal") == set()


@pytest.mark.asyncio
async def test_gateway_dry_run_cannot_execute_external_effect():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    gateway = ActionGateway(ledger, effect_mode="dry_run", policy=DeterministicPolicy(capabilities={"a": {"send"}}))
    called = False

    async def handler(_request):
        nonlocal called
        called = True
        return "sent"

    gateway.register("mail", "send", handler)
    result = await gateway.submit(ActionRequest("x", "r1", "a", "mail", "send", capability_requested=frozenset({"send"}), effect_class=EffectClass.E3, reversible=False))
    assert result.decision is SecurityDecision.DENY
    assert result.reason_code == "dry_run_external_effect"
    assert called is False


@pytest.mark.asyncio
async def test_gateway_denies_active_artifact_with_low_integrity_ancestor():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    source = ledger.append_artifact(_artifact("r1", "source", "low"))
    child = ledger.append_artifact(_artifact("r1", "child", "high"))
    ledger.append_derivation(Derivation("d1", "r1", child.version_id, (source.version_id,), "activity"))
    gateway = ActionGateway(ledger, policy=DeterministicPolicy(capabilities={"a": {"write"}}))
    called = False

    async def handler(_request):
        nonlocal called
        called = True

    gateway.register("memory", "write", handler)
    result = await gateway.submit(ActionRequest("a1", "r1", "a", "memory", "write", (ActionArgument("x", artifact_refs=("child",), integrity="high"),), frozenset({"write"}), effect_class=EffectClass.E1))
    assert result.decision is SecurityDecision.DENY
    assert result.reason_code == "contaminated_provenance"
    assert called is False


def test_checker_certificate_requires_clean_residual_and_snapshot():
    ledger = ProvenanceLedger()
    engine = RunEngine(ledger)
    context = engine.create_run(RunManifest("r1"))
    source = context.append_artifact(artifact_id="src", kind=ArtifactKind.MESSAGE, value="bad", integrity="low")
    sink = context.append_artifact(artifact_id="arg", kind=ArtifactKind.ARGUMENT, value="x", integrity="high")
    context.derive(sink, [source], activity_id="tool")
    graph, _tight = context_run_graphs(context)
    checker = ResidualChecker()
    assert checker.check(graph, sink_versions={sink.version_id}).status == "UNSAFE"
    certificates = CertificateChecker(ledger)
    cert = certificates.issue(graph, run_id="r1", sink_versions={sink.version_id}, blocked_versions={source.version_id})
    assert cert.valid
    assert certificates.verify(cert, graph)
    context.transition(source, ArtifactState.QUARANTINED, "block")
    assert certificates.verify(cert, graph) is False


def test_state_controller_retains_tight_proposal_only_when_conservative_checker_passes():
    ledger = ProvenanceLedger()
    engine = RunEngine(ledger)
    context = engine.create_run(RunManifest("r1"))
    low = context.append_artifact(artifact_id="low", kind=ArtifactKind.MESSAGE, value="bad", integrity="low")
    side = context.append_artifact(artifact_id="side", kind=ArtifactKind.SUMMARY, value="derived", integrity="high")
    clean = context.append_artifact(artifact_id="clean", kind=ArtifactKind.MESSAGE, value="ok", integrity="high")
    sink = context.append_artifact(artifact_id="sink", kind=ArtifactKind.ARGUMENT, value="send", integrity="high")
    context.derive(side, [low], activity_id="side")
    context.derive(sink, [clean], activity_id="sink")
    from app.state import StateController
    controller = StateController(ledger, "r1")
    result = controller.certify_and_retain(sink_versions={sink.version_id}, blocked_versions=set(), candidate_versions={side.version_id})
    assert result.certificate.valid
    assert result.retained == {side.version_id}
    assert ledger.current_state(side.version_id) is ArtifactState.RETAINED


def context_run_graphs(context):
    return build_conservative(context.ledger, context.manifest.run_id), build_tight(context.ledger, context.manifest.run_id)


def test_runtime_checker_distinguishes_uncoverable_from_budget_unknown():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    sink = ledger.append_artifact(_artifact("r1", "sink", "low"))
    graph = build_conservative(ledger, "r1")
    checker = RuntimeWitnessChecker(max_versions=10)
    impossible = checker.check(
        graph,
        sink_versions={sink.version_id},
        break_sets={sink.version_id: frozenset()},
    )
    assert impossible.status is RuntimeCheckStatus.UNSATISFIABLE
    assert impossible.completeness_evidence == "UNCOVERABLE_BREAK_SET"
    budget = RuntimeWitnessChecker(max_versions=0).check(
        graph, sink_versions={sink.version_id}
    )
    assert budget.status is RuntimeCheckStatus.UNKNOWN


def test_state_machine_does_not_reactivate_invalidated_version():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    version = ledger.append_artifact(_artifact("r1", "v1", "high"))
    from app.state import StateController
    controller = StateController(ledger, "r1")
    controller.apply_state(version.version_id, ArtifactState.INVALIDATED, "test")
    with pytest.raises(ValueError, match="illegal state transition"):
        controller.apply_state(version.version_id, ArtifactState.ACTIVE, "forbidden")


def test_release_reissue_is_narrow_and_bounded():
    ledger = ProvenanceLedger()
    ledger.ensure_run("r1")
    version = ledger.append_artifact(_artifact("r1", "v1", "high"))
    graph = build_conservative(ledger, "r1")
    checker = CertificateChecker(ledger)
    cert = checker.issue_release(
        graph,
        run_id="r1",
        release_versions={version.version_id},
        blocked_versions=set(),
        reissue_policy=ReissuePolicy(ttl_seconds=60, max_reissues=1),
    )
    assert checker.verify(cert, graph)
    assert checker.reissue(cert, graph).reissue_count == 1
    with pytest.raises(ValueError, match="limit exhausted"):
        checker.reissue(checker.reissue(cert, graph), graph)


def test_human_approval_gate_estimate_is_conservative():
    estimate = estimate_human_approval_cost(
        expected_e3_actions=10,
        max_reissues=1,
        cost_per_review=2,
        projected_objective_cost=20,
        max_ratio=0.25,
    )
    assert estimate.estimated_reviews == 5
    assert estimate.admitted is False
