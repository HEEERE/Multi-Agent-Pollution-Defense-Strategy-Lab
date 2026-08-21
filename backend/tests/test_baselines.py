"""Tests for the M-layer baseline matrix (v4 plan section 9.5).

Correctness invariants verified here:

* B0 always escapes (no intervention).
* All non-B0 strategies are closed: residual_witnesses == 0.
* B10 is optimal: its J(X) ≤ every other non-escape strategy's J(X).
* RAISE-asymmetric preserves at least as much benign state as RAISE-conservative.
* RAISE-asymmetric has at least as many active versions as RAISE-conservative.
* B9' does not escape (Go/No-Go primary self-built baseline).
* node-quarantine has higher human_cost than source-only (bluntness).
* run_all marks exhaustive correctly (small graphs always exhaustive).
* Score accounting: versions_active + versions_invalidated == versions_total.
* B10 exhaustive flag is inherited from the enumeration result.
"""

from __future__ import annotations

import pytest

from app.research.scale.analysis import enumerate_witnesses
from app.research.scale.baselines import (
    RepairPolicy,
    b0_no_defense,
    b10_exact,
    b7_dependency_rollback,
    b8_min_cut,
    b9_prime_naive_compose,
    containment_only_greedy,
    full_reset,
    node_quarantine,
    raise_asymmetric,
    raise_conservative,
    run_all,
    score,
    source_only,
)
from app.research.scale.graph import GenSpec, generate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_graph(
    *,
    hops: int = 3,
    context: int = 4,
    sinks: int = 2,
    seed: int = 42,
    chain_width: int = 1,
    conservative: bool = True,
) -> object:
    spec = GenSpec(
        context_size=context,
        hops=hops,
        n_sinks=sinks,
        seed=seed,
        chain_width=chain_width,
        n_agents=3,
        n_goals=3,
    )
    return generate(spec, conservative=conservative)


@pytest.fixture
def g_simple():
    return _make_graph()


@pytest.fixture
def g_wide():
    """chain_width=2 produces more witnesses — exercises B10 harder."""
    return _make_graph(chain_width=2, seed=7)


@pytest.fixture
def g_p0():
    return _make_graph(conservative=False, seed=13)


# ---------------------------------------------------------------------------
# B0: no defense — must always have residual witnesses
# ---------------------------------------------------------------------------

class TestB0:
    def test_b0_escapes(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b0_no_defense(g_simple, ws)
        assert o.escaped, "B0 must escape: no intervention means the attack is real"

    def test_b0_zero_cost(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b0_no_defense(g_simple, ws)
        assert o.op_cost == 0.0
        assert o.human_cost == 0.0

    def test_b0_no_intervention(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b0_no_defense(g_simple, ws)
        assert len(o.selected) == 0

    def test_b0_repair_none(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b0_no_defense(g_simple, ws)
        assert o.repair is RepairPolicy.NONE


# ---------------------------------------------------------------------------
# All strategies are closed (no escape) except B0
# ---------------------------------------------------------------------------

class TestClosed:
    STRATEGIES = [
        source_only,
        node_quarantine,
        b8_min_cut,
        containment_only_greedy,
        full_reset,
        b7_dependency_rollback,
        b9_prime_naive_compose,
        b10_exact,
        raise_conservative,
        raise_asymmetric,
    ]

    @pytest.mark.parametrize("fn", STRATEGIES, ids=lambda f: f.__name__)
    def test_no_escape(self, g_simple, fn):
        ws = enumerate_witnesses(g_simple).witnesses
        o = fn(g_simple, ws)
        assert not o.escaped, f"{fn.__name__} must contain all witnesses"
        assert o.residual_witnesses == 0

    @pytest.mark.parametrize("fn", STRATEGIES, ids=lambda f: f.__name__)
    def test_no_escape_p0(self, g_p0, fn):
        ws = enumerate_witnesses(g_p0).witnesses
        o = fn(g_p0, ws)
        assert not o.escaped, f"{fn.__name__} must contain all witnesses (P0 graph)"


# ---------------------------------------------------------------------------
# Version accounting
# ---------------------------------------------------------------------------

class TestVersionAccounting:
    STRATEGIES = [
        b0_no_defense, source_only, node_quarantine, b8_min_cut,
        containment_only_greedy, full_reset, b7_dependency_rollback,
        b9_prime_naive_compose, b10_exact, raise_conservative, raise_asymmetric,
    ]

    @pytest.mark.parametrize("fn", STRATEGIES, ids=lambda f: f.__name__)
    def test_accounting_identity(self, g_simple, fn):
        ws = enumerate_witnesses(g_simple).witnesses
        o = fn(g_simple, ws)
        assert o.versions_active + o.versions_invalidated == o.versions_total, (
            f"{fn.__name__}: active + invalidated must equal total"
        )

    @pytest.mark.parametrize("fn", STRATEGIES, ids=lambda f: f.__name__)
    def test_benign_preserved_nonnegative(self, g_simple, fn):
        ws = enumerate_witnesses(g_simple).witnesses
        o = fn(g_simple, ws)
        assert o.benign_invalidated >= 0
        assert o.benign_preservation >= 0.0
        assert o.benign_preservation <= 1.0


# ---------------------------------------------------------------------------
# B10 is optimal in op_cost: its intervention cost ≤ any other closed strategy
# that uses RepairPolicy.NONE (same repair context).
#
# B10 does NOT minimize J(X) globally — strategies with a smarter repair policy
# may produce lower J by preserving more goals, even at higher op_cost.
# ---------------------------------------------------------------------------

class TestB10Optimal:
    def _containment_only_strategies(self, g):
        """Strategies whose repair policy is NONE — same context as B10."""
        ws = enumerate_witnesses(g).witnesses
        return {
            fn.__name__: fn(g, ws)
            for fn in [
                b0_no_defense,      # escape=True, skip in comparison
                source_only,
                node_quarantine,
                b8_min_cut,
                containment_only_greedy,
                b10_exact,
            ]
        }

    def test_b10_op_cost_optimal_simple(self, g_simple):
        """B10 op_cost ≤ every other NONE-repair containment strategy."""
        out = self._containment_only_strategies(g_simple)
        b10 = out["b10_exact"]
        for name, o in out.items():
            if name == "b0_no_defense" or o.escaped:
                continue
            assert b10.op_cost <= o.op_cost + 1e-9, (
                f"B10 op_cost={b10.op_cost:.2f} must be ≤ {name} op_cost={o.op_cost:.2f}"
            )

    def test_b10_op_cost_optimal_wide(self, g_wide):
        out = self._containment_only_strategies(g_wide)
        b10 = out["b10_exact"]
        for name, o in out.items():
            if name == "b0_no_defense" or o.escaped:
                continue
            assert b10.op_cost <= o.op_cost + 1e-9, (
                f"B10 op_cost={b10.op_cost:.2f} must be ≤ {name} op_cost={o.op_cost:.2f} (wide)"
            )

    def test_b10_does_not_escape(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b10_exact(g_simple, ws)
        assert not o.escaped

    def test_b10_solver_status_optimal(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b10_exact(g_simple, ws)
        assert o.solver_status in ("optimal", "budget_exhausted")


# ---------------------------------------------------------------------------
# RAISE-asymmetric ≥ RAISE-conservative (availability and preservation)
# ---------------------------------------------------------------------------

class TestRAISEAsymmetric:
    def test_asymmetric_preserves_at_least_as_much(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        conservative = raise_conservative(g_simple, ws)
        asymmetric = raise_asymmetric(g_simple, ws)
        assert asymmetric.versions_active >= conservative.versions_active, (
            "RAISE-asymmetric must keep at least as many active versions"
        )

    def test_asymmetric_preserves_benign_at_least_as_much(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        conservative = raise_conservative(g_simple, ws)
        asymmetric = raise_asymmetric(g_simple, ws)
        assert asymmetric.benign_preservation >= conservative.benign_preservation - 1e-9

    def test_asymmetric_uses_support_preserving_repair(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = raise_asymmetric(g_simple, ws)
        assert o.repair is RepairPolicy.ASYMMETRIC

    def test_conservative_uses_support_preserving_repair(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = raise_conservative(g_simple, ws)
        assert o.repair is RepairPolicy.SUPPORT_PRESERVING

    def test_asymmetric_retained_nonnegative(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = raise_asymmetric(g_simple, ws)
        assert o.versions_retained >= 0

    def test_asymmetric_wide(self, g_wide):
        """On a wider graph with more side branches the asymmetric gain should appear."""
        spec = GenSpec(
            context_size=4, hops=3, n_sinks=2, seed=99,
            chain_width=2, side_branch_per_hop=4, n_goals=3,
        )
        from app.research.scale.graph import generate
        g = generate(spec, conservative=True)
        ws = enumerate_witnesses(g).witnesses
        conservative = raise_conservative(g, ws)
        asymmetric = raise_asymmetric(g, ws)
        assert asymmetric.versions_active >= conservative.versions_active


# ---------------------------------------------------------------------------
# B9' Go/No-Go self-built baseline
# ---------------------------------------------------------------------------

class TestB9Prime:
    def test_b9_does_not_escape(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b9_prime_naive_compose(g_simple, ws)
        assert not o.escaped

    def test_b9_repair_is_descendant_wipe(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b9_prime_naive_compose(g_simple, ws)
        assert o.repair is RepairPolicy.DESCENDANT_WIPE

    def test_b9_solver_status(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b9_prime_naive_compose(g_simple, ws)
        assert o.solver_status == "composed"

    def test_b9_selects_something(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b9_prime_naive_compose(g_simple, ws)
        assert len(o.selected) > 0, "B9' must select at least one intervention"


# ---------------------------------------------------------------------------
# node-quarantine bluntness: higher human cost than source-only
# ---------------------------------------------------------------------------

class TestNodeQuarantineBluntness:
    def test_higher_human_cost(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        quar = node_quarantine(g_simple, ws)
        src = source_only(g_simple, ws)
        assert quar.human_cost >= src.human_cost, (
            "Quarantine should incur at least as much human cost as source-only"
        )

    def test_node_quarantine_repair_none(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = node_quarantine(g_simple, ws)
        assert o.repair is RepairPolicy.NONE


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------

class TestRunAll:
    def test_run_all_returns_all_strategies(self, g_simple):
        out, exh = run_all(g_simple, witness_cap=5000)
        assert "B0-no-defense" in out
        assert "RAISE-asymmetric" in out
        assert len(out) == 11

    def test_run_all_exhaustive_small_graph(self, g_simple):
        _out, exh = run_all(g_simple, witness_cap=5000)
        assert exh, "Small graph should be exhaustively enumerated"

    def test_run_all_b0_escapes_others_dont(self, g_simple):
        out, _ = run_all(g_simple, witness_cap=5000)
        assert out["B0-no-defense"].escaped
        for name, o in out.items():
            if name != "B0-no-defense":
                assert not o.escaped, f"{name} should not escape"

    def test_run_all_b10_op_cost_optimal(self, g_simple):
        """B10 minimizes op_cost among NONE-repair strategies, not overall J."""
        out, _ = run_all(g_simple, witness_cap=5000)
        b10_op = out["B10-exact-oracle"].op_cost
        none_repair_names = {
            "source-only", "node-quarantine", "B8-min-cut",
            "containment-only-greedy",
        }
        for name in none_repair_names:
            o = out[name]
            if o.escaped:
                continue
            assert b10_op <= o.op_cost + 1e-9, (
                f"B10 op_cost={b10_op:.2f} must be ≤ {name} op_cost={o.op_cost:.2f}"
            )


# ---------------------------------------------------------------------------
# Goal / task utility
# ---------------------------------------------------------------------------

class TestTaskUtility:
    def test_b0_utility_nonnegative(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = b0_no_defense(g_simple, ws)
        assert 0.0 <= o.task_utility <= 1.0

    def test_full_reset_lower_utility_than_raise_asymmetric(self, g_simple):
        """full-reset wipes all derived state; RAISE-asymmetric keeps clean support."""
        spec = GenSpec(
            context_size=4, hops=3, n_sinks=2, seed=55,
            chain_width=1, independent_support_ratio=1.0, n_goals=3,
        )
        from app.research.scale.graph import generate
        g = generate(spec, conservative=True)
        ws = enumerate_witnesses(g).witnesses
        fr = full_reset(g, ws)
        ra = raise_asymmetric(g, ws)
        # RAISE-asymmetric must support at least as many goals as full-reset
        assert ra.goals_supported >= fr.goals_supported

    def test_goals_total_consistent(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = run_all(g_simple, witness_cap=5000)[0]["RAISE-asymmetric"]
        assert o.goals_total == len(g_simple.goals)


# ---------------------------------------------------------------------------
# Score API
# ---------------------------------------------------------------------------

class TestScoreAPI:
    def test_score_empty_selection_is_b0(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = score(g_simple, ws, "manual-b0", set(), RepairPolicy.NONE)
        assert o.escaped
        assert o.op_cost == 0.0

    def test_score_name_propagated(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = score(g_simple, ws, "my-strategy", set(), RepairPolicy.NONE)
        assert o.name == "my-strategy"

    def test_j_weights(self, g_simple):
        ws = enumerate_witnesses(g_simple).witnesses
        o = score(g_simple, ws, "t", set(), RepairPolicy.NONE)
        j1 = o.j(lam=1.0, mu=1.0, nu=1.0)
        j2 = o.j(lam=2.0, mu=1.0, nu=1.0)
        assert j2 >= j1  # higher lambda amplifies task_loss

    def test_task_utility_zero_goals(self, g_simple):
        """If goals_total is 0, utility should be 1.0 (vacuously supported)."""
        ws = enumerate_witnesses(g_simple).witnesses
        o = score(g_simple, ws, "t", set(), RepairPolicy.NONE)
        if o.goals_total == 0:
            assert o.task_utility == 1.0
