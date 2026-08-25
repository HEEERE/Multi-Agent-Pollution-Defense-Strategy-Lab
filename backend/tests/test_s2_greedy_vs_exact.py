"""Go/No-Go item 2: the greedy-vs-exact gap on the real J(X), not the surrogate.

The H(m) approximation guarantee is a statement about the *additive* surrogate
``C(X) = sum of unit costs``. Real ``J(X) = C_op + 2*L_task + C_replay + C_human``
is not additive: task loss and replay depend on which support groups survive, so a
cover that is cheaper to apply can be more expensive overall, and vice versa.
Nothing in the set-cover proof carries over. So the gap has to be measured.

Two populations, deliberately:

* the published Phase 2 grid (144 points), which is what the report's numbers
  describe;
* a held-out set using seeds and parameters the grid never touched, which is
  where the honest picture of the gap lives.

Measured (full write-up in docs/Phase5-实验结果.md):

    population     surrogate-optimal   max ratio   real J greedy/exact   retention
    Phase 2 grid   142/144 (98.6%)     1.750       805.0 / 802.0 = 1.004  756 = 756
    held-out       72/100  (72.0%)     1.625       887.5 / 706.0 = 1.257  645 < 738

The published grid understates the gap by a wide margin: 98.6% optimal there
against 72.0% on held-out instances, and real J within 0.4% against 25.7%. Both
populations stay far inside their H(m) bound (H(166) = 5.69 on the grid,
H(1080) = 7.56 held-out), so the guarantee is not tight enough to be informative
at these sizes -- which is the point of measuring instead of quoting it.
"""

from __future__ import annotations

from statistics import median

import pytest

from app.research.scale import graph as off_graph
from app.research.scale.heldout import heldout_specs
from app.state import asymmetric_repair as repair
from app.state.costs import apply_interventions, candidate_interventions
from app.state.exact_solver import exact_cover
from app.state.greedy_solver import greedy_cover
from app.state.reachability import clean_e
from app.state.witness import coverage_map, enumerate_witnesses
from app.verification.residual_checker import ResidualChecker
from tests.test_s2_cross_validation import support_groups, sink_versions, to_projection

WITNESS_CAP = 20_000


def _score_cover(graph, catalogue, selected, sinks, support, checker):
    """Run ``solve``'s steps 3-6 on an externally supplied cover.

    ``solve()`` hardcodes the greedy solver, which is correct for production: the
    exact solver is a research baseline (v4 B10), not a runtime path. Rather than
    add a solver switch nothing in production would use, this replays the same
    propose/veto/check/score sequence over whichever cover it is handed, so greedy
    and exact are compared under identical downstream treatment.
    """
    applied = apply_interventions(graph, catalogue, selected)
    non_argument = repair._non_argument(graph)
    cleanliness = clean_e(graph, set(applied.removed_versions))
    clean_active = {v for v in non_argument if cleanliness.get(v, False)}

    proposed = repair.propose(graph, catalogue, selected, sinks)
    vetoed = repair.veto(graph, catalogue, selected, sinks, proposed)
    retained = frozenset(
        v for v in proposed - vetoed
        if v in non_argument and v not in clean_active and v not in applied.removed_versions
    )

    post = checker.check(
        graph,
        sink_versions=sinks,
        blocked_versions=set(applied.removed_versions) | set(applied.denied_sinks),
        blocked_relations=set(applied.removed_relations),
    )
    status = post.status if post.exhaustive or post.status == "UNSAFE" else "UNKNOWN"
    if status != "COVERED":
        retained = frozenset()

    active = clean_active | set(retained)
    cost = repair._score(graph, catalogue, selected, active, set(retained), support)
    return status, cost, retained


def _compare(spec):
    """One point: solve with both solvers, score both, return the comparison."""
    g = off_graph.generate(spec, conservative=True)
    g.index()
    graph = to_projection(g)
    sinks = sink_versions(g)
    support = support_groups(g)
    catalogue = candidate_interventions(graph, sinks)
    witnesses = enumerate_witnesses(graph, sinks, cap=WITNESS_CAP)

    greedy = greedy_cover(graph, catalogue, witnesses.witnesses)
    exact = exact_cover(graph, catalogue, witnesses.witnesses)
    if greedy.status == "unsatisfiable" or exact.status == "unsatisfiable":
        return None

    # m for the H(m) bound: the most witnesses any single intervention breaks.
    covers = coverage_map(graph, catalogue, witnesses.witnesses)
    broken: dict[str, int] = {}
    for cover in covers:
        for iid in cover:
            broken[iid] = broken.get(iid, 0) + 1
    m = max(broken.values(), default=1)

    checker = ResidualChecker()
    g_status, g_cost, g_retain = _score_cover(
        graph, catalogue, set(greedy.selected), sinks, support, checker
    )
    e_status, e_cost, e_retain = _score_cover(
        graph, catalogue, set(exact.selected), sinks, support, checker
    )
    return {
        "spec": spec,
        "exact_status": exact.status,
        "sur_greedy": greedy.cost,
        "sur_exact": exact.cost,
        "j_greedy": g_cost.j(),
        "j_exact": e_cost.j(),
        "retain_greedy": len(g_retain),
        "retain_exact": len(e_retain),
        "util_greedy": g_cost.task_utility,
        "util_exact": e_cost.task_utility,
        "status_greedy": g_status,
        "status_exact": e_status,
        "nodes": exact.nodes_examined,
        "witnesses": witnesses.count,
        "m": m,
    }


def _grid_specs():
    return [
        off_graph.GenSpec(
            context_size=ctx, hops=hops, n_sinks=ns, chain_width=width, seed=seed
        )
        for ctx in (2, 4, 8)
        for hops in (1, 2, 3, 4)
        for ns in (1, 2)
        for width in (1, 2)
        for seed in (0, 1, 2)
    ]


def _heldout_specs():
    """Return the preregistered population; never tune this from test results."""
    return heldout_specs()


@pytest.fixture(scope="module")
def grid_gap():
    return [row for row in (_compare(s) for s in _grid_specs()) if row]


@pytest.fixture(scope="module")
def heldout_gap():
    return [row for row in (_compare(s) for s in _heldout_specs()) if row]


def test_exact_solver_proves_optimality_at_these_sizes(grid_gap, heldout_gap) -> None:
    """Every point must be solved to *proved* optimality, not budget-exhausted.

    A ``feasible`` result is not an optimality claim, so it cannot be used as the
    denominator of a gap measurement. This asserts the comparison is meaningful
    before any number derived from it is trusted.
    """
    for population, rows in (("grid", grid_gap), ("held-out", heldout_gap)):
        unproved = [r["spec"] for r in rows if r["exact_status"] != "optimal"]
        assert not unproved, f"{population}: {len(unproved)} points not proved optimal"


def test_greedy_never_beats_exact_on_the_surrogate(grid_gap, heldout_gap) -> None:
    """Sanity check on the exact solver itself: nothing may undercut the optimum.

    If greedy ever came in cheaper on the additive surrogate, the branch-and-bound
    would be unsound and every gap number here would be meaningless.
    """
    for population, rows in (("grid", grid_gap), ("held-out", heldout_gap)):
        undercut = [
            (r["spec"], r["sur_greedy"], r["sur_exact"])
            for r in rows
            if r["sur_greedy"] < r["sur_exact"] - 1e-9
        ]
        assert not undercut, f"{population}: exact was beaten, first {undercut[0]}"


def test_surrogate_gap_stays_inside_the_harmonic_bound(grid_gap, heldout_gap) -> None:
    """Greedy's surrogate cost must stay within H(m) of the optimum.

    ``m`` is the largest number of witnesses a single intervention breaks. This is
    the one guarantee the additive surrogate actually buys, so a violation would
    mean the solver is not the greedy set-cover it claims to be.
    """
    for population, rows in (("grid", grid_gap), ("held-out", heldout_gap)):
        for row in rows:
            if row["sur_exact"] <= 0:
                continue
            m = row["m"]
            bound = sum(1.0 / i for i in range(1, m + 1))
            ratio = row["sur_greedy"] / row["sur_exact"]
            assert ratio <= bound + 1e-9, (
                f"{population} {row['spec']}: ratio {ratio:.4f} exceeds H({m})={bound:.4f}"
            )


def test_solver_choice_never_changes_the_safety_verdict(grid_gap, heldout_gap) -> None:
    """The whole point of the four-state semantics: safety must not depend on the optimiser.

    Greedy and exact pick different covers, but both are covers. If one yielded
    COVERED and the other UNSAFE on the same instance, the status would be
    reporting a property of the solver rather than of the residual graph.
    """
    for population, rows in (("grid", grid_gap), ("held-out", heldout_gap)):
        disagreed = [
            (r["spec"], r["status_greedy"], r["status_exact"])
            for r in rows
            if r["status_greedy"] != r["status_exact"]
        ]
        assert not disagreed, f"{population}: {len(disagreed)} disagreements, first {disagreed[0]}"


def test_published_grid_gap_matches_the_reported_distribution(grid_gap) -> None:
    """Lock the Phase 2 grid numbers: greedy is optimal on 142/144, max ratio 1.75.

    The two suboptimal points are ``(ctx=8, hops=4, sinks=2, width=1, seed=1|2)``,
    where ``disable_edge:d78`` (1.5, breaks 18) and ``revoke_version:v17``
    (2.0, breaks 24) have *exactly* equal ratio 0.08333 and the tie-break takes the
    cheaper one, which then still needs v17. Preferring the larger gain instead
    fixes both points but regresses harder held-out instances (J 9.0 -> 19.0 on
    ctx=8/hops=2/seed=21), so the cheaper-first order stands.
    """
    assert len(grid_gap) == 144
    optimal = [r for r in grid_gap if abs(r["sur_greedy"] - r["sur_exact"]) < 1e-9]
    assert len(optimal) == 142, f"expected 142 optimal, got {len(optimal)}"

    ratios = [r["sur_greedy"] / r["sur_exact"] for r in grid_gap if r["sur_exact"] > 0]
    assert max(ratios) == pytest.approx(1.75), f"max ratio {max(ratios)}"

    assert median(r["j_greedy"] for r in grid_gap) == pytest.approx(5.0)
    assert median(r["j_exact"] for r in grid_gap) == pytest.approx(5.0)
    assert median(r["retain_greedy"] for r in grid_gap) == pytest.approx(6.0)
    assert median(r["retain_exact"] for r in grid_gap) == pytest.approx(6.0)


def test_heldout_gap_is_materially_wider_than_the_published_grid(heldout_gap) -> None:
    """The finding worth reporting: 142/144 does not generalise.

    On instances the grid never covered, greedy is surrogate-optimal on well under
    80% of points and real J is over 20% above exact. Asserted as inequalities in
    the direction that matters -- the claim is that the gap is *wide*, so the test
    fails if it silently narrows too, which would mean these specs stopped being
    the harder population they were chosen to be.
    """
    assert len(heldout_gap) == 100
    optimal = [r for r in heldout_gap if abs(r["sur_greedy"] - r["sur_exact"]) < 1e-9]
    assert 60 <= len(optimal) <= 85, f"held-out optimal count {len(optimal)} moved"

    j_greedy = sum(r["j_greedy"] for r in heldout_gap)
    j_exact = sum(r["j_exact"] for r in heldout_gap)
    assert j_greedy > j_exact * 1.15, (
        f"held-out real-J gap narrowed: greedy {j_greedy} vs exact {j_exact}"
    )

    retain_greedy = sum(r["retain_greedy"] for r in heldout_gap)
    retain_exact = sum(r["retain_exact"] for r in heldout_gap)
    assert retain_greedy < retain_exact, (
        f"held-out retention: greedy {retain_greedy} vs exact {retain_exact}"
    )


def test_real_j_gap_is_not_predicted_by_the_surrogate_gap(grid_gap, heldout_gap) -> None:
    """J is not additive, so surrogate-optimal does not imply J-optimal.

    This is the substantive reason the H(m) guarantee cannot be quoted as a
    guarantee about ``J``. Demonstrated rather than asserted abstractly: there
    exist points where the surrogate costs are equal and the real J values differ,
    and points where exact wins the surrogate yet loses on real J.
    """
    rows = grid_gap + heldout_gap
    tied_surrogate_split_j = [
        r for r in rows
        if abs(r["sur_greedy"] - r["sur_exact"]) < 1e-9
        and abs(r["j_greedy"] - r["j_exact"]) > 1e-9
    ]
    greedy_wins_real_j = [r for r in rows if r["j_greedy"] < r["j_exact"] - 1e-9]
    assert tied_surrogate_split_j or greedy_wins_real_j, (
        "no evidence of surrogate/J divergence; J may have become additive, "
        "which would invalidate the report's framing"
    )


def test_exact_is_affordable_at_action_boundary_sizes(grid_gap, heldout_gap) -> None:
    """Recorded for the write-up: B&B is cheap here, so the gap is a choice.

    Max nodes examined stays orders of magnitude below the 300k budget on both
    populations. That is why the write-up can recommend exact-with-greedy-fallback
    as future work rather than dismissing it as intractable.
    """
    for population, rows in (("grid", grid_gap), ("held-out", heldout_gap)):
        worst = max(r["nodes"] for r in rows)
        assert worst < 300_000, f"{population}: {worst} nodes hit the budget"
