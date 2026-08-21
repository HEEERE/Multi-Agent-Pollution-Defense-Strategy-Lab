"""Correctness tests for the Phase 0.5 machinery.

The scale study produces the Phase 4 admission numbers, so the machinery that
produces them needs to be checked against hand-computed cases and against
brute force. Untested research code yielding a gate decision is worthless.
"""

from __future__ import annotations

import pytest

from app.research.scale.analysis import (
    Witness,
    break_set,
    classify,
    clean_e,
    completeness,
    enumerate_witnesses,
    sc1_layer_cut,
    sc2_sink_domination,
    sink_reachable,
)
from app.research.scale.graph import (
    Derivation,
    GenSpec,
    Hypergraph,
    Integrity,
    Intervention,
    InterventionKind,
    Sink,
    Version,
    VersionKind,
    generate,
)
from app.research.scale.solvers import (
    brute_force_cover,
    greedy_cover,
    verify_cover,
)


def _manual_chain() -> Hypergraph:
    """A hand-built three-hop chain with one low-integrity source.

        v0(rag, LOW) -> v1(memory) -> v2(argument, sink q0)
        v3(rag, HIGH) -> v4(summary)          [no path to sink]

    Expected: exactly one witness {v0, v1, v2}; v4 is clean; nothing is
    contaminated-unreachable because v4's only parent is high integrity.
    """
    g = Hypergraph()
    g.versions["v0"] = Version("v0", VersionKind.RAG_CHUNK, Integrity.LOW, 0)
    g.versions["v3"] = Version("v3", VersionKind.RAG_CHUNK, Integrity.HIGH, 1)
    g.versions["v1"] = Version("v1", VersionKind.MEMORY, Integrity.HIGH, 2)
    g.versions["v4"] = Version("v4", VersionKind.SUMMARY, Integrity.HIGH, 3)
    g.versions["v2"] = Version("v2", VersionKind.ARGUMENT, Integrity.HIGH, 4)
    g.derivations["d0"] = Derivation("d0", ("v0",), "v1", "a0")
    g.derivations["d1"] = Derivation("d1", ("v3",), "v4", "a1")
    g.derivations["d2"] = Derivation("d2", ("v1",), "v2", "a2")
    g.sinks.append(Sink("q0", "v2", "E3"))
    for vid in ("v0", "v1", "v3", "v4"):
        g.interventions[f"rv_{vid}"] = Intervention(
            f"rv_{vid}", InterventionKind.REVOKE_VERSION, vid, 1.0
        )
    for did in ("d0", "d1", "d2"):
        g.interventions[f"de_{did}"] = Intervention(
            f"de_{did}", InterventionKind.DISABLE_EDGE, did, 1.5
        )
    g.interventions["da_q0"] = Intervention(
        "da_q0", InterventionKind.DENY_ACTION, "q0", 8.0
    )
    g.index()
    return g


class TestWitnessEnumeration:
    def test_manual_chain_has_exactly_one_witness(self):
        g = _manual_chain()
        res = enumerate_witnesses(g)
        assert res.exhaustive is True
        assert res.count == 1
        w = res.witnesses[0]
        assert w.root_qid == "q0"
        assert w.versions == frozenset({"v0", "v1", "v2"})
        assert w.derivations == frozenset({"d0", "d2"})

    def test_high_integrity_only_graph_has_no_witness(self):
        """A graph with no low-integrity source is fully authorised."""
        g = _manual_chain()
        g.versions["v0"] = Version("v0", VersionKind.RAG_CHUNK, Integrity.HIGH, 0)
        res = enumerate_witnesses(g)
        assert res.count == 0
        assert res.exhaustive is True

    def test_break_set_covers_versions_edges_and_deny(self):
        g = _manual_chain()
        w = enumerate_witnesses(g).witnesses[0]
        bs = break_set(g, w)
        # v2 is the sink argument itself, so revoke_version(v2) is not offered.
        assert "rv_v0" in bs and "rv_v1" in bs
        assert "rv_v2" not in bs
        assert "de_d0" in bs and "de_d2" in bs
        assert "de_d1" not in bs  # not part of this witness
        assert "da_q0" in bs

    def test_cap_marks_enumeration_non_exhaustive(self):
        """Hitting the cap must report a bounded universe, never a complete one."""
        g = generate(
            GenSpec(context_size=4, hops=4, n_sinks=2, chain_width=3, seed=0),
            conservative=True,
        )
        full = enumerate_witnesses(g, cap=10_000_000)
        assert full.exhaustive is True
        capped = enumerate_witnesses(g, cap=2)
        assert capped.exhaustive is False
        assert capped.count <= full.count

    def test_and_edge_requires_all_parents(self):
        """An AND record's proof must contain every parent (fragment fusion)."""
        g = Hypergraph()
        g.versions["a"] = Version("a", VersionKind.RAG_CHUNK, Integrity.LOW, 0)
        g.versions["b"] = Version("b", VersionKind.RAG_CHUNK, Integrity.HIGH, 1)
        g.versions["c"] = Version("c", VersionKind.ARGUMENT, Integrity.HIGH, 2)
        g.derivations["d"] = Derivation("d", ("a", "b"), "c", "fuse")
        g.sinks.append(Sink("q0", "c", "E3"))
        g.index()
        res = enumerate_witnesses(g)
        assert res.count == 1
        assert res.witnesses[0].versions == frozenset({"a", "b", "c"})


class TestCleanE:
    def test_low_integrity_source_is_not_clean(self):
        g = _manual_chain()
        ce = clean_e(g, set())
        assert ce["v0"] is False
        assert ce["v1"] is False  # inherits from v0
        assert ce["v3"] is True
        assert ce["v4"] is True

    def test_revocation_propagates(self):
        g = _manual_chain()
        ce = clean_e(g, {"v3"})
        assert ce["v3"] is False
        assert ce["v4"] is False

    def test_conservative_mode_collapses_more_than_tight(self):
        """The L1 effect: P1 fan-in drags side state into contamination."""
        spec = GenSpec(context_size=8, hops=3, n_sinks=1, seed=0)
        tight = classify(generate(spec, conservative=False))
        cons = classify(generate(spec, conservative=True))
        assert cons.clean_survival_rate < tight.clean_survival_rate


class TestReachabilityAndClassification:
    def test_sink_reachable_excludes_side_branch(self):
        g = _manual_chain()
        reach = sink_reachable(g)
        assert {"v0", "v1", "v2"} <= reach
        assert "v4" not in reach
        assert "v3" not in reach

    def test_classification_partitions_all_non_argument_versions(self):
        g = generate(
            GenSpec(context_size=6, hops=3, n_sinks=1, seed=1), conservative=True
        )
        t = classify(g)
        non_arg = sum(
            1 for v in g.versions.values() if v.kind is not VersionKind.ARGUMENT
        )
        assert t.total == non_arg
        assert (
            t.clean + t.contaminated_reachable + t.contaminated_unreachable == non_arg
        )

    def test_retained_versions_never_reach_a_sink(self):
        """Theorem 5's precondition, checked directly on generated graphs."""
        for seed in range(4):
            g = generate(
                GenSpec(context_size=8, hops=4, n_sinks=2, seed=seed),
                conservative=True,
            )
            t = classify(g)
            reach = sink_reachable(g)
            for vid in t.members["contaminated_unreachable"]:
                assert vid not in reach, (
                    f"{vid} was classified retainable but can reach a sink"
                )

    def test_asymmetric_availability_is_never_below_clean_rate(self):
        """Retention can only add availability, never remove it."""
        for seed in range(4):
            g = generate(
                GenSpec(context_size=8, hops=3, n_sinks=1, seed=seed),
                conservative=True,
            )
            t = classify(g)
            assert t.asymmetric_available_rate >= t.clean_survival_rate


class TestSufficientConditions:
    def test_sc1_holds_when_low_source_is_revoked(self):
        g = _manual_chain()
        assert sc1_layer_cut(g, {"rv_v0"}) is True

    def test_sc1_fails_when_path_survives(self):
        g = _manual_chain()
        assert sc1_layer_cut(g, set()) is False
        assert sc1_layer_cut(g, {"rv_v3"}) is False  # irrelevant intervention

    def test_sc2_holds_when_every_sink_is_denied(self):
        g = _manual_chain()
        assert sc2_sink_domination(g, {"da_q0"}) is True
        assert sc2_sink_domination(g, set()) is False

    def test_sc1_is_sound_against_enumeration(self):
        """If SC1 claims exhaustive-no-witness, enumeration must agree.

        This is the property that lets a cheap linear check stand in for
        exponential enumeration. A counterexample would invalidate every
        EXHAUSTIVE certificate issued via SC1.
        """
        for seed in range(6):
            g = generate(
                GenSpec(context_size=5, hops=3, n_sinks=1, seed=seed),
                conservative=True,
            )
            witnesses = enumerate_witnesses(g).witnesses
            candidates = sorted(g.interventions)[:14]
            for iid in candidates:
                x = {iid}
                if sc1_layer_cut(g, x):
                    assert verify_cover(g, witnesses, x), (
                        f"SC1 claimed no residual witness for {x} but a witness "
                        f"survives (seed={seed})"
                    )

    def test_completeness_reports_which_condition_fired(self):
        g = _manual_chain()
        assert completeness(g, {"rv_v0"}) == "SC1"
        assert completeness(g, set()) == "none"


class TestSolvers:
    def test_exact_matches_hand_computed_optimum(self):
        g = _manual_chain()
        witnesses = enumerate_witnesses(g).witnesses
        res = brute_force_cover(g, witnesses)
        assert res.proven_optimal
        # Cheapest single cover is a revoke_version at cost 1.0.
        assert res.cost == pytest.approx(1.0)
        assert verify_cover(g, witnesses, res.selected)

    def test_greedy_covers_everything_and_is_never_cheaper_than_exact(self):
        for seed in range(6):
            g = generate(
                GenSpec(context_size=6, hops=3, n_sinks=2, seed=seed),
                conservative=True,
            )
            witnesses = enumerate_witnesses(g).witnesses
            exact = brute_force_cover(g, witnesses)
            greedy = greedy_cover(g, witnesses)
            assert verify_cover(g, witnesses, greedy.selected), (
                f"greedy left a witness uncovered (seed={seed})"
            )
            if exact.proven_optimal:
                assert greedy.cost >= exact.cost - 1e-9, (
                    "greedy beat a proven optimum, so the exact solver is wrong"
                )

    def test_empty_universe_is_trivially_optimal(self):
        g = _manual_chain()
        res = brute_force_cover(g, [])
        assert res.proven_optimal
        assert res.cost == 0.0
        assert res.selected == set()

    def test_uncoverable_witness_is_unsatisfiable_not_optimal(self):
        """Break(W) = empty set must surface as UNSATISFIABLE.

        The v4 plan requires this to be distinct from a timeout: it is a real
        capability boundary, not a budget problem.
        """
        g = _manual_chain()
        g.interventions.clear()  # nothing can break anything
        witnesses = [
            Witness(
                root_qid="q0",
                versions=frozenset({"v0", "v1", "v2"}),
                derivations=frozenset({"d0", "d2"}),
            )
        ]
        assert brute_force_cover(g, witnesses).status == "unsatisfiable"
        assert greedy_cover(g, witnesses).status == "unsatisfiable"

    def test_verify_cover_rejects_an_incomplete_solution(self):
        g = _manual_chain()
        witnesses = enumerate_witnesses(g).witnesses
        assert verify_cover(g, witnesses, set()) is False
        assert verify_cover(g, witnesses, {"rv_v3"}) is False


class TestGenerator:
    def test_graph_is_a_dag_by_topological_index(self):
        g = generate(
            GenSpec(context_size=6, hops=4, n_sinks=2, chain_width=2, seed=3),
            conservative=True,
        )
        for d in g.derivations.values():
            child = g.versions[d.child]
            for p in d.parents:
                assert g.versions[p].topo_index < child.topo_index, (
                    "derivation violates A5 version ordering"
                )

    def test_every_generated_graph_contains_an_attack(self):
        """Without a guaranteed low-integrity entry the numbers are meaningless."""
        for seed in range(5):
            for conservative in (True, False):
                g = generate(
                    GenSpec(context_size=4, hops=2, n_sinks=1, seed=seed),
                    conservative=conservative,
                )
                assert g.low_integrity_sources
                assert enumerate_witnesses(g).count >= 1

    def test_width_increases_witness_count(self):
        """chain_width is the axis that makes proof trees branch."""
        base = GenSpec(context_size=4, hops=4, n_sinks=1, chain_width=1, seed=0)
        wide = GenSpec(context_size=4, hops=4, n_sinks=1, chain_width=3, seed=0)
        n_base = enumerate_witnesses(generate(base, conservative=True)).count
        n_wide = enumerate_witnesses(generate(wide, conservative=True)).count
        assert n_wide > n_base


class TestTruncationIsNeverReportedAsSafe:
    """A bounded universe must never be presentable as a proven result.

    This is the "timeout disguised as safe" failure the v4 plan singles out. It
    occurred for real in the first frontier run: truncated enumeration returned
    an empty witness list, and the exact solver then trivially reported
    ``optimal`` over that empty universe.
    """

    def test_lazy_and_eager_enumerators_agree(self):
        """Two independent implementations must produce the same universe.

        The lazy generator is the one used in anger; the memoised eager version
        exists as a cross-check. Divergence means one of them is wrong, and the
        scale numbers would be untrustworthy either way.
        """
        from app.research.scale.analysis import _enumerate_witnesses_eager

        for seed in range(4):
            for width in (1, 2, 3):
                g = generate(
                    GenSpec(
                        context_size=4,
                        hops=3,
                        n_sinks=2,
                        chain_width=width,
                        seed=seed,
                    ),
                    conservative=True,
                )
                lazy = enumerate_witnesses(g, cap=10_000_000)
                eager = _enumerate_witnesses_eager(g, cap=10_000_000)
                assert lazy.exhaustive and eager.exhaustive
                assert {w.key() for w in lazy.witnesses} == {
                    w.key() for w in eager.witnesses
                }, f"enumerators disagree (seed={seed}, width={width})"

    def test_truncated_enumeration_keeps_partial_witnesses(self):
        g = generate(
            GenSpec(context_size=4, hops=5, n_sinks=1, chain_width=3, seed=0),
            conservative=True,
        )
        full = enumerate_witnesses(g, cap=10_000_000)
        assert full.exhaustive and full.count > 10

        capped = enumerate_witnesses(g, cap=5)
        assert capped.exhaustive is False
        assert capped.count > 0, (
            "truncated enumeration returned an empty universe, which would read "
            "as 'no witnesses found'"
        )

    def test_run_point_downgrades_status_on_truncation(self):
        from app.research.scale.experiment import run_point

        p = run_point(
            context_size=4,
            hops=6,
            n_sinks=1,
            chain_width=3,
            seed=0,
            conservative=True,
            witness_cap=5,
            exact_budget=100_000,
        )
        assert p.enumeration_exhaustive is False
        assert p.exact_status != "optimal", (
            "optimality was claimed over a universe that was never fully "
            "enumerated"
        )
        assert p.greedy_gap_ratio is None, (
            "a gap ratio was reported against an unproven optimum"
        )
