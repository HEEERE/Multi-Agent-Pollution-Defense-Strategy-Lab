"""Tests for the M-layer baseline grid runner (§9.5 deliverable).

Verifies:
* Grid runner returns correct number of points for a known parameter set.
* Every strategy appears in every point's outcomes.
* B0 escape_rate == 1.0 in the summary.
* No non-B0 strategy has escape_rate > 0 on small exhaustive graphs.
* RAISE-asymmetric benign_preservation >= RAISE-conservative in both modes.
* Summary by_mode exhaustive_rate == 1.0 on small graphs.
* J(X) >= 0 for every point / every strategy.
"""

from __future__ import annotations

import pytest

from app.research.scale.baselines import STRATEGIES
from app.research.scale.grid_runner import run_grid, summarise


@pytest.fixture(scope="module")
def small_grid():
    """A 2×2×1×1×1 grid: fast enough to run in CI, large enough to matter."""
    return run_grid(
        contexts=(2, 4),
        hops_list=(1, 2),
        sinks_list=(1,),
        widths=(1,),
        seeds=(0,),
        witness_cap=5_000,
    )


@pytest.fixture(scope="module")
def small_summary(small_grid):
    return summarise(small_grid)


class TestGridShape:
    def test_point_count(self, small_grid):
        # 2 modes × 2 contexts × 2 hops × 1 sink × 1 width × 1 seed = 8
        assert len(small_grid) == 8

    def test_all_strategies_present(self, small_grid):
        for pt in small_grid:
            for strat in STRATEGIES:
                assert strat in pt.outcomes, (
                    f"Strategy {strat!r} missing in point {pt}"
                )

    def test_modes_present(self, small_grid):
        modes = {pt.mode for pt in small_grid}
        assert "P0_tight" in modes
        assert "P1_conservative" in modes


class TestOutcomeInvariants:
    def test_j_nonnegative(self, small_grid):
        for pt in small_grid:
            for strat, row in pt.outcomes.items():
                assert row["j"] >= 0.0, f"Negative J for {strat} at {pt}"

    def test_task_utility_in_unit_interval(self, small_grid):
        for pt in small_grid:
            for strat, row in pt.outcomes.items():
                assert 0.0 <= row["task_utility"] <= 1.0, (
                    f"task_utility out of range for {strat}"
                )

    def test_benign_preservation_in_unit_interval(self, small_grid):
        for pt in small_grid:
            for strat, row in pt.outcomes.items():
                assert 0.0 <= row["benign_preservation"] <= 1.0, (
                    f"benign_preservation out of range for {strat}"
                )

    def test_b0_always_escapes(self, small_grid):
        for pt in small_grid:
            assert pt.outcomes["B0-no-defense"]["escaped"] is True

    def test_non_b0_never_escapes(self, small_grid):
        for pt in small_grid:
            for strat, row in pt.outcomes.items():
                if strat == "B0-no-defense":
                    continue
                assert not row["escaped"], (
                    f"{strat} escaped on point {pt.mode} ctx={pt.context_size} "
                    f"hops={pt.hops}"
                )


class TestSummaryInvariants:
    def test_b0_escape_rate_one(self, small_summary):
        for mode in ("P0_tight", "P1_conservative"):
            rate = small_summary["by_strategy"]["B0-no-defense"][mode]["escape_rate"]
            assert rate == 1.0, f"B0 escape_rate should be 1.0 in {mode}"

    def test_non_b0_escape_rate_zero(self, small_summary):
        for strat in STRATEGIES:
            if strat == "B0-no-defense":
                continue
            for mode in ("P0_tight", "P1_conservative"):
                rate = small_summary["by_strategy"][strat][mode]["escape_rate"]
                assert rate == 0.0, (
                    f"{strat}/{mode} escape_rate={rate}, expected 0.0"
                )

    def test_exhaustive_rate_one(self, small_summary):
        for mode in ("P0_tight", "P1_conservative"):
            er = small_summary["by_mode"][mode]["exhaustive_rate"]
            assert er == 1.0, f"exhaustive_rate should be 1.0 for {mode}"

    def test_raise_asymmetric_bp_ge_conservative(self, small_summary):
        for mode in ("P0_tight", "P1_conservative"):
            asym = small_summary["by_strategy"]["RAISE-asymmetric"][mode]
            cons = small_summary["by_strategy"]["RAISE-conservative"][mode]
            assert asym["benign_preservation"]["median"] >= cons["benign_preservation"]["median"] - 1e-9, (
                f"RAISE-asymmetric bp should be >= conservative in {mode}"
            )

    def test_summary_contains_all_strategies(self, small_summary):
        for strat in STRATEGIES:
            assert strat in small_summary["by_strategy"]
