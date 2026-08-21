"""M-layer baseline grid runner — §9.5 deliverable.

Sweeps all 11 strategies across a parameter grid of synthetic graphs and
produces the comparative J(X) / task_utility / benign-preservation tables
for the Phase 2 report.

Run with::

    python -m app.research.scale.grid_runner --out tmp/phase2_baseline_grid.json
    python -m app.research.scale.grid_runner --quick

Columns produced per strategy in the summary table:
    escape_rate      fraction of grid points where residual witnesses > 0
    J mean/med/max   real J(X) = op_cost + 2*task_loss + replay + human
    task_utility     goals_supported / goals_total
    benign_pres      1 - benign_invalidated / versions_total
    op_cost          raw intervention cost
    human_cost       quarantine/deny-action interventions needing sign-off
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from app.research.scale.baselines import STRATEGIES, Outcome, run_all
from app.research.scale.graph import GenSpec, generate


# ---------------------------------------------------------------------------
# per-point data
# ---------------------------------------------------------------------------


@dataclass
class GridPoint:
    mode: str
    context_size: int
    hops: int
    n_sinks: int
    chain_width: int
    seed: int
    enumeration_exhaustive: bool
    elapsed_ms: float
    outcomes: dict[str, dict]  # strategy_name -> serialised Outcome


def _outcome_row(o: Outcome) -> dict:
    return {
        "escaped": o.escaped,
        "j": round(o.j(), 4),
        "task_utility": round(o.task_utility, 4),
        "benign_preservation": round(o.benign_preservation, 4),
        "op_cost": round(o.op_cost, 4),
        "human_cost": round(o.human_cost, 4),
    }


def run_grid_point(
    *,
    context_size: int,
    hops: int,
    n_sinks: int,
    chain_width: int,
    seed: int,
    conservative: bool,
    witness_cap: int,
) -> GridPoint:
    t0 = perf_counter()
    spec = GenSpec(
        context_size=context_size,
        hops=hops,
        n_sinks=n_sinks,
        chain_width=chain_width,
        seed=seed,
    )
    g = generate(spec, conservative=conservative)
    outcomes, exhaustive = run_all(g, witness_cap=witness_cap)
    elapsed = (perf_counter() - t0) * 1000
    return GridPoint(
        mode="P1_conservative" if conservative else "P0_tight",
        context_size=context_size,
        hops=hops,
        n_sinks=n_sinks,
        chain_width=chain_width,
        seed=seed,
        enumeration_exhaustive=exhaustive,
        elapsed_ms=round(elapsed, 2),
        outcomes={name: _outcome_row(o) for name, o in outcomes.items()},
    )


# ---------------------------------------------------------------------------
# grid definition
# ---------------------------------------------------------------------------

DEFAULT_CONTEXTS = (2, 4, 8)
DEFAULT_HOPS = (1, 2, 3, 4)
DEFAULT_SINKS = (1, 2)
DEFAULT_WIDTHS = (1, 2)
DEFAULT_SEEDS = (0, 1, 2)


def run_grid(
    *,
    contexts=DEFAULT_CONTEXTS,
    hops_list=DEFAULT_HOPS,
    sinks_list=DEFAULT_SINKS,
    widths=DEFAULT_WIDTHS,
    seeds=DEFAULT_SEEDS,
    witness_cap: int = 20_000,
) -> list[GridPoint]:
    points: list[GridPoint] = []
    for conservative in (False, True):
        for ctx in contexts:
            for hops in hops_list:
                for ns in sinks_list:
                    for width in widths:
                        for seed in seeds:
                            points.append(
                                run_grid_point(
                                    context_size=ctx,
                                    hops=hops,
                                    n_sinks=ns,
                                    chain_width=width,
                                    seed=seed,
                                    conservative=conservative,
                                    witness_cap=witness_cap,
                                )
                            )
    return points


# ---------------------------------------------------------------------------
# summary table
# ---------------------------------------------------------------------------


def _strategy_stats(points: list[GridPoint], strategy: str) -> dict:
    rows = [p.outcomes[strategy] for p in points if strategy in p.outcomes]
    if not rows:
        return {}
    js = [r["j"] for r in rows]
    utils = [r["task_utility"] for r in rows]
    bps = [r["benign_preservation"] for r in rows]
    ops = [r["op_cost"] for r in rows]
    hcs = [r["human_cost"] for r in rows]
    escapes = [r["escaped"] for r in rows]
    return {
        "escape_rate": round(sum(escapes) / len(escapes), 4),
        "J": {
            "mean": round(statistics.mean(js), 4),
            "median": round(statistics.median(js), 4),
            "max": round(max(js), 4),
        },
        "task_utility": {
            "mean": round(statistics.mean(utils), 4),
            "median": round(statistics.median(utils), 4),
        },
        "benign_preservation": {
            "mean": round(statistics.mean(bps), 4),
            "median": round(statistics.median(bps), 4),
        },
        "op_cost": {
            "mean": round(statistics.mean(ops), 4),
        },
        "human_cost": {
            "mean": round(statistics.mean(hcs), 4),
        },
    }


def summarise(points: list[GridPoint]) -> dict:
    out: dict = {"by_mode": {}, "by_strategy": {}}

    for mode in ("P0_tight", "P1_conservative"):
        ps = [p for p in points if p.mode == mode]
        if not ps:
            continue
        exhaustive_count = sum(1 for p in ps if p.enumeration_exhaustive)
        out["by_mode"][mode] = {
            "points": len(ps),
            "exhaustive_rate": round(exhaustive_count / len(ps), 4),
        }

    for strategy in STRATEGIES:
        out["by_strategy"][strategy] = {}
        for mode in ("P0_tight", "P1_conservative"):
            ps = [p for p in points if p.mode == mode]
            out["by_strategy"][strategy][mode] = _strategy_stats(ps, strategy)

    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="M-layer baseline grid runner (§9.5)")
    ap.add_argument("--out", default="tmp/phase2_baseline_grid.json")
    ap.add_argument("--witness-cap", type=int, default=20_000)
    ap.add_argument("--quick", action="store_true", help="small 2×2 smoke run")
    args = ap.parse_args()

    if args.quick:
        points = run_grid(
            contexts=(2, 4),
            hops_list=(1, 2),
            sinks_list=(1,),
            widths=(1,),
            seeds=(0,),
            witness_cap=args.witness_cap,
        )
    else:
        points = run_grid(witness_cap=args.witness_cap)

    summary = summarise(points)
    payload = {
        "points": [
            {
                "mode": p.mode,
                "context_size": p.context_size,
                "hops": p.hops,
                "n_sinks": p.n_sinks,
                "chain_width": p.chain_width,
                "seed": p.seed,
                "enumeration_exhaustive": p.enumeration_exhaustive,
                "elapsed_ms": p.elapsed_ms,
                "outcomes": p.outcomes,
            }
            for p in points
        ],
        "summary": summary,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"points written: {len(points)}  ->  {out}")
    print(f"\n{'Strategy':<30}  {'mode':<20}  {'escape%':>8}  {'J_med':>8}  "
          f"{'util_med':>9}  {'bp_med':>8}  {'hcost':>7}")
    print("-" * 100)
    for strat in STRATEGIES:
        for mode in ("P0_tight", "P1_conservative"):
            s = summary["by_strategy"].get(strat, {}).get(mode, {})
            if not s:
                continue
            print(
                f"{strat:<30}  {mode:<20}  "
                f"{s['escape_rate']:>8.4f}  "
                f"{s['J']['median']:>8.4f}  "
                f"{s['task_utility']['median']:>9.4f}  "
                f"{s['benign_preservation']['median']:>8.4f}  "
                f"{s['human_cost']['mean']:>7.4f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
