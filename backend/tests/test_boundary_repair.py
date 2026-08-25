from __future__ import annotations

import pytest

from app.actions import ActionArgument, ActionRequest, DeterministicPolicy, EffectClass, SecurityDecision
from app.provenance import ProvenanceLedger
from app.provenance.models import ArtifactKind, ArtifactState, ArtifactVersion, Derivation
from app.runtime import RunEngine, RunManifest
from app.state.boundary_repair import BoundaryRepair


def _artifact(run_id: str, vid: str, integrity: str) -> ArtifactVersion:
    return ArtifactVersion(vid, vid, run_id, ArtifactKind.MESSAGE, vid, frozenset(), integrity)


def _contaminated_run(engine: RunEngine, run_id: str):
    """low -> child (reaches the sink) and low -> side (does not).

    ``side`` is the ``contaminated_unreachable`` version: the tight graph may
    propose it for retention because no path carries the contamination to the
    action's sink.
    """
    ledger = engine.ledger
    ledger.append_artifact(_artifact(run_id, "low", "low"))
    ledger.append_artifact(_artifact(run_id, "child", "high"))
    ledger.append_artifact(_artifact(run_id, "side", "high"))
    ledger.append_derivation(Derivation("d1", run_id, "child", ("low",), "a1"))
    ledger.append_derivation(Derivation("d2", run_id, "side", ("low",), "a2"))
    return ledger


def _request(run_id: str, action_id: str = "act1") -> ActionRequest:
    return ActionRequest(
        action_id, run_id, "agent", "memory", "write",
        (ActionArgument("x", artifact_refs=("child",), integrity="high"),),
        frozenset({"write"}), effect_class=EffectClass.E1,
    )


@pytest.mark.asyncio
async def test_contamination_denial_invokes_repair_and_issues_retention_certificate():
    engine = RunEngine()
    ledger = _contaminated_run(engine, "r1")
    context = engine.create_run(RunManifest("r1"), policy=DeterministicPolicy(capabilities={"agent": {"write"}}))
    context.gateway.register("memory", "write", lambda _r: None)

    result = await context.gateway.submit(_request("r1"))

    assert result.decision is SecurityDecision.DENY
    assert result.reason_code == "contaminated_provenance"
    # S4: the repair mechanism actually ran at the boundary.
    assert ledger.metrics("r1").get("boundary_repairs") == 1
    # The cover cuts at the sink, which is cheaper than revoking the root.
    assert ledger.current_state("child") is ArtifactState.INVALIDATED
    assert ledger.current_state("side") is ArtifactState.RETAINED
    assert ledger.has_label_enforcement("side")


@pytest.mark.asyncio
async def test_non_contamination_denial_does_not_repair():
    engine = RunEngine()
    ledger = _contaminated_run(engine, "r2")
    context = engine.create_run(RunManifest("r2"), policy=DeterministicPolicy(capabilities={"agent": set()}))
    context.gateway.register("memory", "write", lambda _r: None)

    result = await context.gateway.submit(_request("r2"))

    assert result.reason_code == "capability_out_of_scope"
    assert "boundary_repairs" not in ledger.metrics("r2")
    assert ledger.current_state("side") is ArtifactState.ACTIVE


@pytest.mark.asyncio
async def test_open_horizon_refuses_to_retain(monkeypatch):
    """v4 §5.3: 定理 5 only holds for a frozen Q_sigma."""
    engine = RunEngine()
    ledger = _contaminated_run(engine, "r3")
    context = engine.create_run(RunManifest("r3", horizon_closure="open"),
                                policy=DeterministicPolicy(capabilities={"agent": {"write"}}))
    context.gateway.register("memory", "write", lambda _r: None)

    await context.gateway.submit(_request("r3"))

    assert ledger.metrics("r3").get("boundary_repairs") == 1
    assert ledger.current_state("child") is ArtifactState.INVALIDATED
    assert ledger.current_state("side") is not ArtifactState.RETAINED
    assert not ledger.has_label_enforcement("side")


@pytest.mark.asyncio
async def test_repair_requeues_the_affected_scope():
    """v4 §8.4 rule 5: pending actions lose the pre-intervention verdict."""
    engine = RunEngine()
    _contaminated_run(engine, "r4")
    context = engine.create_run(RunManifest("r4"), policy=DeterministicPolicy(capabilities={"agent": {"write"}}))
    context.gateway.register("memory", "write", lambda _r: None)
    before = context.boundary_queue._generation

    await context.gateway.submit(_request("r4"))

    assert context.boundary_queue._generation > before


@pytest.mark.asyncio
async def test_retained_version_is_readjudicated_when_it_becomes_reachable():
    """The second boundary must not reuse the first boundary's retention."""
    engine = RunEngine()
    ledger = _contaminated_run(engine, "r5")
    context = engine.create_run(RunManifest("r5"), policy=DeterministicPolicy(capabilities={"agent": {"write"}}))
    context.gateway.register("memory", "write", lambda _r: None)
    await context.gateway.submit(_request("r5"))
    assert ledger.current_state("side") is ArtifactState.RETAINED

    # New activity builds a path from the retained version to the next sink.
    ledger.append_artifact(_artifact("r5", "next", "high"))
    ledger.append_derivation(Derivation("d3", "r5", "next", ("side",), "a3"))
    request = ActionRequest(
        "act2", "r5", "agent", "memory", "write",
        (ActionArgument("x", artifact_refs=("next",), integrity="high"),),
        frozenset({"write"}), effect_class=EffectClass.E1,
    )
    await context.gateway.submit(request)

    assert ledger.current_state("side") is ArtifactState.INVALIDATED


@pytest.mark.asyncio
async def test_repair_is_skipped_without_artifact_refs():
    repair = BoundaryRepair(ProvenanceLedger())
    request = ActionRequest("a", "r6", "agent", "memory", "write", (ActionArgument("x"),),
                            frozenset({"write"}), effect_class=EffectClass.E1)
    assert await repair.at_boundary(request, "contaminated_provenance") is None
    assert await repair.at_boundary(_request("r6"), "artifact_unavailable") is None
