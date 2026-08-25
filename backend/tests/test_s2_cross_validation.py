"""S2 acceptance: the online mechanism must agree with the offline prototype.

The point of S2 is that the solvers, the cheap sufficient conditions and the cost
model move from ``research/scale`` into ``state/`` and ``verification/`` *without
semantic drift*. Agreement is therefore the acceptance criterion, and it is
checked on the same instance rather than on two independently generated ones.

Only tests may import both worlds. The runtime may not, which
``test_research_isolation.py`` enforces separately.
"""

from __future__ import annotations

import random

import pytest

from app.provenance.models import ArtifactKind, ArtifactVersion, Derivation, SupportGroup
from app.provenance.projection import ProvenanceGraph
from app.research.scale import analysis as off_analysis
from app.research.scale import graph as off_graph
from app.research.scale import solvers as off_solvers
from app.state import costs as on_costs
from app.state import witness as on_witness
from app.state.greedy_solver import greedy_cover
from app.state.exact_solver import exact_cover
from app.verification.completeness import cheap_completeness
from app.verification.residual_checker import ResidualChecker

KIND_MAP = {
    off_graph.VersionKind.RAG_CHUNK: ArtifactKind.RAG_CHUNK,
    off_graph.VersionKind.MESSAGE: ArtifactKind.MESSAGE,
    off_graph.VersionKind.MEMORY: ArtifactKind.MEMORY,
    off_graph.VersionKind.SUMMARY: ArtifactKind.SUMMARY,
    off_graph.VersionKind.PLAN: ArtifactKind.PLAN,
    off_graph.VersionKind.TOOL_RESULT: ArtifactKind.TOOL_RESULT,
    off_graph.VersionKind.ARGUMENT: ArtifactKind.ARGUMENT,
}


def to_projection(g: off_graph.Hypergraph, run_id: str = "xval") -> ProvenanceGraph:
    """Bridge an offline hypergraph into the online typed projection.

    Structure is preserved exactly: version ids, hyperedge parent tuples and
    derivation ids all carry over unchanged, so a witness found on one side is
    comparable element-by-element with a witness found on the other.
    """
    versions: dict[str, ArtifactVersion] = {}
    for v in g.versions.values():
        versions[v.vid] = ArtifactVersion(
            version_id=v.vid,
            artifact_id=v.vid,
            run_id=run_id,
            kind=KIND_MAP[v.kind],
            value_hash=v.vid,
            integrity=str(v.integrity),
            origin_principals=frozenset({v.agent}) if v.agent else frozenset(),
            derivation_ids=tuple(d.did for d in g.incoming(v.vid)),
            metadata={"topo_index": v.topo_index},
        )
    derivations = {
        d.did: Derivation(
            relation_id=d.did,
            run_id=run_id,
            child_version_id=d.child,
            parent_version_ids=tuple(d.parents),
            activity_id=d.activity,
        )
        for d in g.derivations.values()
    }
    return ProvenanceGraph(versions=versions, derivations=derivations, conservative=True)


def support_groups(g: off_graph.Hypergraph, run_id: str = "xval") -> list[SupportGroup]:
    return [
        SupportGroup(
            support_id=s.sid,
            run_id=run_id,
            goal_id=s.goal,
            member_version_ids=tuple(s.members),
            verifier_id="xval",
            verified=s.verified,
        )
        for s in g.support.values()
    ]


def sink_versions(g: off_graph.Hypergraph) -> set[str]:
    return {s.version_id for s in g.sinks}


def _spec(seed: int, **kw) -> off_graph.GenSpec:
    """Modest default instance: small enough to enumerate exhaustively."""
    params = dict(context_size=3, hops=3, n_sinks=2, seed=seed)
    params.update(kw)
    return off_graph.GenSpec(**params)


def _small(seed: int) -> off_graph.GenSpec:
    """Small enough for exact branch-and-bound to prove optimality."""
    return _spec(seed, context_size=2, hops=2, n_sinks=1, n_goals=2, n_agents=2)


def _instances(count: int, *, conservative: bool = False):
    for seed in range(count):
        g = off_graph.generate(_spec(seed), conservative=conservative)
        g.index()
        yield seed, g


# ---------------------------------------------------------------------------
# 1. Witness enumeration parity
# ---------------------------------------------------------------------------


def _offline_witness_keys(g: off_graph.Hypergraph) -> set[tuple]:
    """Normalise offline witnesses onto (root version, versions, derivations).

    The offline root is a sink *id*; the online root is the sink's *version*.
    Comparing on the version makes the two sides commensurable without weakening
    the check: the version/derivation sets are still compared exactly.
    """
    by_qid = {s.qid: s.version_id for s in g.sinks}
    result = off_analysis.enumerate_witnesses(g, cap=5_000)
    return {
        (by_qid[w.root_qid], w.versions, w.derivations) for w in result.witnesses
    }


def _online_witness_keys(graph: ProvenanceGraph, sinks: set[str]) -> set[tuple]:
    result = on_witness.enumerate_witnesses(graph, sinks, cap=5_000)
    return {
        (w.root_version_id, frozenset(w.versions), frozenset(w.relations))
        for w in result.witnesses
    }


@pytest.mark.parametrize("seed", range(12))
def test_witness_enumeration_matches_offline(seed: int) -> None:
    g = off_graph.generate(_spec(seed), conservative=False)
    g.index()
    graph = to_projection(g)

    offline = _offline_witness_keys(g)
    online = _online_witness_keys(graph, sink_versions(g))

    assert online == offline, (
        f"seed={seed}: online-only={len(online - offline)} "
        f"offline-only={len(offline - online)}"
    )


def test_witness_enumeration_is_non_trivial() -> None:
    """Guard against the parity test passing because both sides find nothing."""
    total = 0
    for _, g in _instances(6):
        graph = to_projection(g)
        total += len(on_witness.enumerate_witnesses(graph, sink_versions(g), cap=5_000).witnesses)
    assert total > 0


def test_low_integrity_deviation_is_deliberate() -> None:
    """Online counts any low version; offline counts low *source* leaves.

    On generated graphs the two coincide, which is what makes the parity test
    above meaningful. This test pins the deviation itself so it stays a choice
    rather than an accident: a low-integrity version with high-integrity parents
    is a contamination origin online.
    """
    graph = ProvenanceGraph(
        versions={
            "hi": ArtifactVersion("hi", "hi", "r", ArtifactKind.MESSAGE, "h", integrity="high"),
            "mid": ArtifactVersion("mid", "mid", "r", ArtifactKind.TOOL_RESULT, "h", integrity="low"),
            "sink": ArtifactVersion("sink", "sink", "r", ArtifactKind.ARGUMENT, "h", integrity="high"),
        },
        derivations={
            "d1": Derivation("d1", "r", "mid", ("hi",), "a1"),
            "d2": Derivation("d2", "r", "sink", ("mid",), "a2"),
        },
    )
    assert on_witness.low_integrity_versions(graph) == {"mid"}
    result = on_witness.enumerate_witnesses(graph, {"sink"}, cap=10)
    assert result.witnesses, "a low tool result with a high parent must still be a witness"


# ---------------------------------------------------------------------------
# 2. Cost-model / solver parity on J(X)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(12))
def test_greedy_cost_matches_offline(seed: int) -> None:
    g = off_graph.generate(_spec(seed), conservative=False)
    g.index()
    graph = to_projection(g)
    sinks = sink_versions(g)

    offline_ws = off_analysis.enumerate_witnesses(g, cap=5_000).witnesses
    off_result = off_solvers.greedy_cover(g, offline_ws)

    online_ws = on_witness.enumerate_witnesses(graph, sinks, cap=5_000).witnesses
    catalogue = on_costs.candidate_interventions(graph, sinks)
    on_result = greedy_cover(graph, catalogue, online_ws)

    assert on_result.status == off_result.status
    assert on_result.cost == pytest.approx(off_result.cost), (
        f"seed={seed}: online={on_result.cost} offline={off_result.cost}"
    )


def _offline_catalogue(g: off_graph.Hypergraph) -> dict[tuple[str, str], float]:
    """Offline catalogue keyed semantically.

    Offline iids are opaque counters (``i0``, ``i1``, ...); online they are
    ``{kind}:{target}`` so a replay of the same snapshot yields the same
    catalogue. That difference is deliberate, so parity is checked on
    ``(kind, target)`` instead. ``deny_action`` targets a sink id offline and the
    sink's version online; the mapping is one-to-one, so it is normalised here.
    """
    by_qid = {s.qid: s.version_id for s in g.sinks}
    out: dict[tuple[str, str], float] = {}
    for i in g.interventions.values():
        target = by_qid[i.target] if i.kind is off_graph.InterventionKind.DENY_ACTION else i.target
        out[(str(i.kind), target)] = i.cost
    return out


@pytest.mark.parametrize("seed", range(8))
def test_intervention_catalogue_matches_offline(seed: int) -> None:
    """Same universe, same unit costs. Without this, cost parity is meaningless."""
    g = off_graph.generate(_spec(seed), conservative=False)
    g.index()
    graph = to_projection(g)

    catalogue = on_costs.candidate_interventions(graph, sink_versions(g))
    online = {(str(iv.kind), iv.target): iv.cost for iv in catalogue.values()}
    offline = _offline_catalogue(g)

    assert set(online) == set(offline), (
        f"seed={seed}: online-only={sorted(set(online) - set(offline))[:5]} "
        f"offline-only={sorted(set(offline) - set(online))[:5]}"
    )
    for key, cost in offline.items():
        assert online[key] == pytest.approx(cost), key


@pytest.mark.parametrize("seed", range(6))
def test_exact_solver_is_never_worse_than_greedy(seed: int) -> None:
    g = off_graph.generate(_small(seed), conservative=False)
    g.index()
    graph = to_projection(g)
    sinks = sink_versions(g)

    ws = on_witness.enumerate_witnesses(graph, sinks, cap=2_000).witnesses
    catalogue = on_costs.candidate_interventions(graph, sinks)
    greedy = greedy_cover(graph, catalogue, ws)
    exact = exact_cover(graph, catalogue, ws)

    if not exact.proven_optimal:
        pytest.skip("branch-and-bound hit its node cap")
    assert exact.cost <= greedy.cost + 1e-9
    if ws:
        assert on_witness.verify_cover(graph, catalogue, ws, exact.selected)


# ---------------------------------------------------------------------------
# 3. SC1/SC2 soundness against full enumeration
# ---------------------------------------------------------------------------


def _random_intervention_set(rng: random.Random, catalogue: dict) -> set[str]:
    iids = sorted(catalogue)
    if not iids:
        return set()
    k = rng.randint(0, min(4, len(iids)))
    return set(rng.sample(iids, k))


def _to_offline_iids(g: off_graph.Hypergraph, catalogue: dict, x: set[str]) -> set[str]:
    """Translate an online intervention set into the offline iid namespace."""
    by_qid = {s.qid: s.version_id for s in g.sinks}
    lookup: dict[tuple[str, str], str] = {}
    for i in g.interventions.values():
        target = by_qid[i.target] if i.kind is off_graph.InterventionKind.DENY_ACTION else i.target
        lookup[(str(i.kind), target)] = i.iid
    return {lookup[(str(catalogue[iid].kind), catalogue[iid].target)] for iid in x}


def test_cheap_conditions_are_sound_over_random_cases() -> None:
    """SC1/SC2 may miss, but must never claim absence while a witness remains.

    200 random (instance, intervention set) pairs. Each cheap "no witness"
    verdict is checked against full enumeration on the residual graph.
    """
    rng = random.Random(20260821)
    checked = 0
    proved = 0
    for seed in range(40):
        g = off_graph.generate(_small(seed), conservative=False)
        g.index()
        graph = to_projection(g)
        sinks = sink_versions(g)
        catalogue = on_costs.candidate_interventions(graph, sinks)

        for _ in range(5):
            x = _random_intervention_set(rng, catalogue)
            applied = on_costs.apply_interventions(graph, catalogue, x)
            evidence = cheap_completeness(
                graph,
                sinks,
                removed_versions=set(applied.removed_versions),
                removed_relations=set(applied.removed_relations),
                denied_sinks=set(applied.denied_sinks),
            )
            residual = on_witness.enumerate_witnesses(
                graph,
                sinks - set(applied.denied_sinks),
                cap=5_000,
                blocked_versions=set(applied.removed_versions),
                blocked_relations=set(applied.removed_relations),
            )
            checked += 1
            if evidence.proves_absence:
                proved += 1
                assert not residual.witnesses, (
                    f"seed={seed} X={sorted(x)}: {evidence.condition} claimed absence "
                    f"but {len(residual.witnesses)} witnesses remain"
                )
    assert checked >= 200
    assert proved > 0, "no cheap condition ever fired; the soundness check is vacuous"


def test_sc1_agrees_with_offline_completeness() -> None:
    rng = random.Random(7)
    agreed = 0
    for seed in range(20):
        g = off_graph.generate(_small(seed), conservative=False)
        g.index()
        graph = to_projection(g)
        sinks = sink_versions(g)
        catalogue = on_costs.candidate_interventions(graph, sinks)
        for _ in range(3):
            x = _random_intervention_set(rng, catalogue)
            off_sc1 = off_analysis.sc1_layer_cut(g, _to_offline_iids(g, catalogue, x))
            applied = on_costs.apply_interventions(graph, catalogue, x)
            on_sc1 = cheap_completeness(
                graph,
                sinks,
                removed_versions=set(applied.removed_versions),
                removed_relations=set(applied.removed_relations),
                denied_sinks=set(applied.denied_sinks),
            ).condition == "SC1"
            assert on_sc1 == off_sc1, f"seed={seed} X={sorted(x)}"
            agreed += 1
    assert agreed >= 60


# ---------------------------------------------------------------------------
# 4. The checker still refuses to depend on a solver
# ---------------------------------------------------------------------------


def test_checker_reaches_a_verdict_without_any_solver() -> None:
    g = off_graph.generate(_spec(3), conservative=False)
    g.index()
    graph = to_projection(g)
    sinks = sink_versions(g)
    result = ResidualChecker().check(graph, sink_versions=sinks)
    assert result.status in {"COVERED", "UNSAFE", "UNKNOWN"}
