"""S2 Go/No-Go: the online mechanism must reproduce the offline Phase 2 result.

The other S2 tests check component parity. This one checks the *claim*: that the
asymmetric mechanism now running inside ``state/`` produces the same J(X) and task
utility as the offline prototype the Phase 2 report was written from.

Reference row, Phase 2 report section 二, P1 (conservative) mode, median over the
144-point grid:

    RAISE-asymmetric     J_med = 5.00   util_med = 0.67
    RAISE-conservative   J_med = 13.00  util_med = 0.00
    B9'-naive-compose    J_med = 26.00  util_med = 0.00

If these drift, the migration changed the mechanism rather than relocating it,
and the published numbers no longer describe the code that runs.
"""

from __future__ import annotations

from statistics import median

import pytest

from app.research.scale import baselines as off_baselines
from app.research.scale import analysis as off_analysis
from app.research.scale import graph as off_graph
from app.state import asymmetric_repair
from tests.test_s2_cross_validation import support_groups, sink_versions, to_projection

# Phase 2 grid (grid_runner defaults), conservative half only.
CONTEXTS = (2, 4, 8)
HOPS = (1, 2, 3, 4)
SINKS = (1, 2)
WIDTHS = (1, 2)
SEEDS = (0, 1, 2)

PHASE2_P1 = {
    "RAISE-asymmetric": {"j": 5.00, "util": 0.67},
    "RAISE-conservative": {"j": 13.00, "util": 0.00},
}


def _grid_specs() -> list[off_graph.GenSpec]:
    return [
        off_graph.GenSpec(
            context_size=ctx, hops=hops, n_sinks=ns, chain_width=width, seed=seed
        )
        for ctx in CONTEXTS
        for hops in HOPS
        for ns in SINKS
        for width in WIDTHS
        for seed in SEEDS
    ]


def _online_point(spec: off_graph.GenSpec):
    """Run the online mechanism on one conservative-mode grid point.

    Both graph arguments are the P1 projection. That is the honest online
    reading of the P1 row: the runtime holds one ledger, and P1 mode means the
    conservative builder is what the ledger yields. The tight graph is not a
    different instance, so passing the same projection is what the offline P1
    baseline does too.
    """
    g = off_graph.generate(spec, conservative=True)
    g.index()
    graph = to_projection(g)
    return (
        asymmetric_repair.solve(
            graph,
            graph,
            sink_versions=sink_versions(g),
            support_groups=support_groups(g),
            witness_cap=20_000,
        ),
        g,
    )


@pytest.fixture(scope="module")
def grid():
    """The 144-point P1 grid, run once through the online mechanism."""
    out = []
    for spec in _grid_specs():
        plan, g = _online_point(spec)
        witnesses = off_analysis.enumerate_witnesses(g, cap=20_000).witnesses
        out.append(
            {
                "spec": spec,
                "plan": plan,
                "offline_asym": off_baselines.raise_asymmetric(g, witnesses),
                "offline_cons": off_baselines.raise_conservative(g, witnesses),
            }
        )
    return out


def test_grid_has_the_expected_shape(grid) -> None:
    assert len(grid) == 144


def test_asymmetric_j_median_matches_phase2(grid) -> None:
    j = median(row["plan"].cost.j() for row in grid)
    assert j == pytest.approx(PHASE2_P1["RAISE-asymmetric"]["j"], abs=0.01), (
        f"online J_med={j}, Phase 2 reported {PHASE2_P1['RAISE-asymmetric']['j']}"
    )


def test_asymmetric_utility_median_matches_phase2(grid) -> None:
    util = median(row["plan"].cost.task_utility for row in grid)
    assert util == pytest.approx(PHASE2_P1["RAISE-asymmetric"]["util"], abs=0.01), (
        f"online util_med={util}, Phase 2 reported {PHASE2_P1['RAISE-asymmetric']['util']}"
    )


def test_online_agrees_with_offline_pointwise(grid) -> None:
    """Identical J(X) on all 144 points, not merely an identical median.

    A median can match while individual points disagree in cancelling directions,
    which would still mean the mechanism drifted.

    Exact equality is only assertable because both solvers now break ratio ties
    on ``(ratio, cost, -gain, iid)``. The offline greedy used to leave ties to
    whatever order its ``set[str]`` break sets iterated in, so the same instance
    produced different covers under different ``PYTHONHASHSEED`` values — three
    distinct covers and a grid J_med of 5.00 or 5.25 across seeds 0/1/2/7/42/1234.
    Both sides are now bit-identical across those seeds (grid sum 805.0000).
    """
    mismatches = [
        (row["spec"], row["plan"].cost.j(), row["offline_asym"].j())
        for row in grid
        if abs(row["plan"].cost.j() - row["offline_asym"].j()) > 1e-9
    ]
    assert not mismatches, (
        f"{len(mismatches)}/144 points disagree; first: {mismatches[0]}"
    )

    disagreed = [
        row["spec"]
        for row in grid
        if row["offline_asym"].escaped != (row["plan"].status == "UNSAFE")
    ]
    assert not disagreed, f"{len(disagreed)}/144 safety disagreements"


def test_offline_solver_tie_break_is_fully_ordered(grid) -> None:
    """Guard the fix: the offline cover must not depend on dict iteration order.

    Re-solving with the candidate index built in reverse insertion order must give
    the same cover. Before the tie-break was fully ordered this changed the answer,
    which is exactly how hash-order dependence leaked into the published numbers.
    """
    from app.research.scale.solvers import greedy_cover as off_greedy

    for row in grid[:24]:
        g = off_graph.generate(row["spec"], conservative=True)
        g.index()
        witnesses = off_analysis.enumerate_witnesses(g, cap=20_000).witnesses
        forward = off_greedy(g, witnesses)
        g.interventions = dict(reversed(list(g.interventions.items())))
        reverse = off_greedy(g, witnesses)
        assert forward.selected == reverse.selected, row["spec"]
        assert forward.cost == pytest.approx(reverse.cost), row["spec"]


def test_online_solver_is_deterministic(grid) -> None:
    """Re-solving the same instance must yield the identical plan.

    This is the property the offline prototype lacks, and it is not optional
    online: an append-only ledger with replayable certificates needs the same
    snapshot to produce the same intervention set every time.
    """
    for row in grid[:24]:
        g = off_graph.generate(row["spec"], conservative=True)
        g.index()
        graph = to_projection(g)
        again = asymmetric_repair.solve(
            graph,
            graph,
            sink_versions=sink_versions(g),
            support_groups=support_groups(g),
            witness_cap=20_000,
        )
        assert again.selected == row["plan"].selected, row["spec"]
        assert again.retain == row["plan"].retain, row["spec"]
        assert again.cost.j() == pytest.approx(row["plan"].cost.j()), row["spec"]


def test_online_retention_matches_offline_pointwise(grid) -> None:
    """Retention must match offline on every point, not just in aggregate.

    Retention is the entire claim of the asymmetric mechanism, so a count that
    matches overall while individual points differ would hide the failure that
    matters. Now that both solvers pick the same cover, the same versions survive.
    """
    mismatches = [
        (row["spec"], len(row["plan"].retain), row["offline_asym"].versions_retained)
        for row in grid
        if len(row["plan"].retain) != row["offline_asym"].versions_retained
    ]
    assert not mismatches, (
        f"{len(mismatches)}/144 retention mismatches; first: {mismatches[0]}"
    )


def test_asymmetry_beats_conservative_online(grid) -> None:
    """The H2/§3.7 claim, re-derived online rather than quoted from the report."""
    asym_j = median(row["plan"].cost.j() for row in grid)
    cons_j = median(row["offline_cons"].j() for row in grid)
    assert asym_j < cons_j
    assert cons_j == pytest.approx(PHASE2_P1["RAISE-conservative"]["j"], abs=0.01)


def test_no_grid_point_escapes(grid) -> None:
    """Safety first: retention must never leave a residual witness behind."""
    escaped = [row["spec"] for row in grid if row["plan"].status == "UNSAFE"]
    assert not escaped, f"{len(escaped)}/144 points left a residual witness"


def test_benign_preservation_never_regresses(grid) -> None:
    """Soundness invariant of v4 §3.7: bp_asym >= bp_cons at every point."""
    regressions = [
        row["spec"]
        for row in grid
        if row["plan"].cost.benign_preservation < row["offline_cons"].benign_preservation - 1e-9
    ]
    assert not regressions, f"{len(regressions)}/144 benign-preservation regressions"
