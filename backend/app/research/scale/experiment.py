"""Phase 0.5 grid driver.

Run with::

    python -m app.research.scale.experiment --out tmp/phase05.json

Produces, for every point of the (context_size, hops, n_sinks) grid and for both
provenance modes:

* witness count and whether enumeration was exhaustive
* exact solver status, cost and wall time  -> tractability limit
* greedy cost and the real gap to exact    -> proposition 3 in practice
* Clean_E survival rate                    -> the L1 metric
* retention rate (contaminated_unreachable) -> the H5 headroom
* SC1/SC2 hit rate                          -> section 4.2 viability
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from app.research.scale.analysis import (
    classify,
    completeness,
    enumerate_witnesses,
)
from app.research.scale.graph import GenSpec, generate
from app.research.scale.solvers import (
    brute_force_cover,
    greedy_cover,
    mincut_cover,
    verify_cover,
)


@dataclass
class Point:
    mode: str
    context_size: int
    hops: int
    n_sinks: int
    chain_width: int
    seed: int

    versions: int
    derivations: int
    witnesses: int
    enumeration_exhaustive: bool
    enumeration_ms: float

    exact_status: str
    exact_cost: float
    exact_ms: float
    exact_subsets: int

    greedy_cost: float
    greedy_ms: float
    greedy_verified: bool
    greedy_gap_ratio: float | None

    mincut_status: str
    mincut_cost: float
    mincut_verified: bool

    clean_survival_rate: float
    retention_rate: float
    asymmetric_available_rate: float

    sc_condition: str


def run_point(
    *, context_size: int, hops: int, n_sinks: int, seed: int, conservative: bool,
    witness_cap: int, exact_budget: int, chain_width: int = 1,
) -> Point:
    from time import perf_counter

    spec = GenSpec(
        context_size=context_size,
        hops=hops,
        n_sinks=n_sinks,
        chain_width=chain_width,
        seed=seed,
    )
    g = generate(spec, conservative=conservative)

    t0 = perf_counter()
    enum = enumerate_witnesses(g, cap=witness_cap)
    enum_ms = (perf_counter() - t0) * 1000

    exact = brute_force_cover(g, enum.witnesses, max_subsets=exact_budget)
    greedy = greedy_cover(g, enum.witnesses)
    mincut = mincut_cover(g, enum.witnesses)

    # A solver cannot prove optimality over a universe that was never fully
    # enumerated. Downgrading the status here is what keeps a truncated run from
    # being read as a proven-safe run (v4 plan section 4.2: BUDGET_EXHAUSTED is
    # never a safety result).
    exact_status = exact.status
    if not enum.exhaustive and exact_status == "optimal":
        exact_status = "budget_exhausted_universe"

    gap = None
    if (
        exact.proven_optimal
        and enum.exhaustive
        and exact.cost > 0
        and greedy.cost != float("inf")
    ):
        gap = greedy.cost / exact.cost

    taint = classify(g)
    sc = completeness(g, greedy.selected)

    return Point(
        mode="P1_conservative" if conservative else "P0_tight",
        context_size=context_size,
        hops=hops,
        n_sinks=n_sinks,
        chain_width=chain_width,
        seed=seed,
        versions=len(g.versions),
        derivations=len(g.derivations),
        witnesses=enum.count,
        enumeration_exhaustive=enum.exhaustive,
        enumeration_ms=round(enum_ms, 3),
        exact_status=exact_status,
        exact_cost=exact.cost if exact.cost != float("inf") else -1.0,
        exact_ms=round(exact.elapsed_ms, 3),
        exact_subsets=exact.subsets_examined,
        greedy_cost=greedy.cost if greedy.cost != float("inf") else -1.0,
        greedy_ms=round(greedy.elapsed_ms, 3),
        greedy_verified=verify_cover(g, enum.witnesses, greedy.selected),
        greedy_gap_ratio=round(gap, 4) if gap is not None else None,
        mincut_status=mincut.status,
        mincut_cost=mincut.cost if mincut.cost != float("inf") else -1.0,
        mincut_verified=verify_cover(g, enum.witnesses, mincut.selected),
        clean_survival_rate=round(taint.clean_survival_rate, 4),
        retention_rate=round(taint.retention_rate, 4),
        asymmetric_available_rate=round(taint.asymmetric_available_rate, 4),
        sc_condition=sc,
    )


DEFAULT_CONTEXT = (2, 4, 8, 16)
DEFAULT_HOPS = (1, 2, 3, 4, 5)
DEFAULT_SINKS = (1, 2)
DEFAULT_WIDTHS = (1, 2, 3)
DEFAULT_SEEDS = (0, 1, 2)


def run_grid(
    *,
    contexts=DEFAULT_CONTEXT,
    hops_list=DEFAULT_HOPS,
    sinks_list=DEFAULT_SINKS,
    widths=DEFAULT_WIDTHS,
    seeds=DEFAULT_SEEDS,
    witness_cap: int = 20_000,
    exact_budget: int = 200_000,
) -> list[Point]:
    points: list[Point] = []
    for conservative in (False, True):
        for ctx in contexts:
            for hops in hops_list:
                for ns in sinks_list:
                    for width in widths:
                        for seed in seeds:
                            points.append(
                                run_point(
                                    context_size=ctx,
                                    hops=hops,
                                    n_sinks=ns,
                                    chain_width=width,
                                    seed=seed,
                                    conservative=conservative,
                                    witness_cap=witness_cap,
                                    exact_budget=exact_budget,
                                )
                            )
    return points


def summarise(points: list[Point]) -> dict:
    def sub(mode: str) -> list[Point]:
        return [p for p in points if p.mode == mode]

    out: dict = {"modes": {}}
    for mode in ("P0_tight", "P1_conservative"):
        ps = sub(mode)
        if not ps:
            continue
        exhaustive = [p for p in ps if p.enumeration_exhaustive]
        gaps = [p.greedy_gap_ratio for p in ps if p.greedy_gap_ratio is not None]
        out["modes"][mode] = {
            "points": len(ps),
            "witness_count": {
                "min": min(p.witnesses for p in ps),
                "median": statistics.median(p.witnesses for p in ps),
                "max": max(p.witnesses for p in ps),
            },
            "enumeration_exhaustive_rate": round(len(exhaustive) / len(ps), 4),
            "exact_proven_optimal_rate": round(
                sum(1 for p in ps if p.exact_status == "optimal") / len(ps), 4
            ),
            "greedy_all_verified": all(p.greedy_verified for p in ps),
            "greedy_gap_ratio": {
                "median": round(statistics.median(gaps), 4) if gaps else None,
                "max": round(max(gaps), 4) if gaps else None,
            },
            "clean_survival_rate": {
                "min": round(min(p.clean_survival_rate for p in ps), 4),
                "median": round(
                    statistics.median(p.clean_survival_rate for p in ps), 4
                ),
                "max": round(max(p.clean_survival_rate for p in ps), 4),
            },
            "retention_rate": {
                "min": round(min(p.retention_rate for p in ps), 4),
                "median": round(statistics.median(p.retention_rate for p in ps), 4),
                "max": round(max(p.retention_rate for p in ps), 4),
            },
            "asymmetric_available_rate": {
                "median": round(
                    statistics.median(p.asymmetric_available_rate for p in ps), 4
                ),
            },
            "sc_hit_rate": round(
                sum(1 for p in ps if p.sc_condition != "none") / len(ps), 4
            ),
            "mincut_unsatisfiable_rate": round(
                sum(1 for p in ps if p.mincut_status == "unsatisfiable") / len(ps), 4
            ),
            # Soundness invariants. Both must hold on every reported run; a
            # violation means the numbers above cannot be trusted.
            "no_optimality_claimed_on_truncated_universe": all(
                p.enumeration_exhaustive or p.exact_status != "optimal" for p in ps
            ),
            "retention_never_reduces_availability": all(
                p.asymmetric_available_rate >= p.clean_survival_rate - 1e-9
                for p in ps
            ),
        }

    # Tractability frontier: largest (context, hops) still proven optimal.
    frontier: dict[str, list[list[int]]] = {}
    for mode in ("P0_tight", "P1_conservative"):
        ok = [
            [p.context_size, p.hops, p.n_sinks]
            for p in sub(mode)
            if p.exact_status == "optimal" and p.enumeration_exhaustive
        ]
        frontier[mode] = sorted(ok)[-5:] if ok else []
    out["exact_tractable_frontier_last5"] = frontier
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 0.5 scale pre-experiment")
    ap.add_argument("--out", default="tmp/phase05_scale.json")
    ap.add_argument("--witness-cap", type=int, default=20_000)
    ap.add_argument("--exact-budget", type=int, default=200_000)
    ap.add_argument("--quick", action="store_true", help="small grid smoke run")
    args = ap.parse_args()

    if args.quick:
        points = run_grid(
            contexts=(2, 4),
            hops_list=(1, 2),
            sinks_list=(1,),
            widths=(1, 2),
            seeds=(0,),
            witness_cap=args.witness_cap,
            exact_budget=args.exact_budget,
        )
    else:
        points = run_grid(
            witness_cap=args.witness_cap, exact_budget=args.exact_budget
        )

    payload = {
        "points": [asdict(p) for p in points],
        "summary": summarise(points),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    s = payload["summary"]
    print(f"points: {len(points)}  ->  {out}")
    for mode, m in s["modes"].items():
        print(f"\n[{mode}]")
        print(f"  witnesses      min/med/max : {m['witness_count']}")
        print(f"  enum exhaustive rate       : {m['enumeration_exhaustive_rate']}")
        print(f"  exact proven optimal rate  : {m['exact_proven_optimal_rate']}")
        print(f"  greedy all verified        : {m['greedy_all_verified']}")
        print(f"  greedy gap (med/max)       : {m['greedy_gap_ratio']}")
        print(f"  Clean_E survival min/med/max: {m['clean_survival_rate']}")
        print(f"  retention rate  min/med/max: {m['retention_rate']}")
        print(f"  asym available (median)    : {m['asymmetric_available_rate']}")
        print(f"  SC1/SC2 hit rate           : {m['sc_hit_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
