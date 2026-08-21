"""Locate the enumeration / exact-solver tractability frontier.

The Phase 0.5 grid in ``experiment.py`` answers the *shape* questions but stays
inside the tractable region, so it never finds the limit. This driver walks a
single axis at a time until enumeration stops being exhaustive or the exact
solver stops proving optimality, and reports the last tractable point.

That frontier is what section 10.1 of the v4 plan requires as the Phase 4 gate:
without it there is no defensible E-layer scale cap.

Run with::

    python -m app.research.scale.frontier --out tmp/phase05_frontier.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.research.scale.experiment import Point, run_point


@dataclass
class AxisWalk:
    axis: str
    mode: str
    fixed: dict[str, int]
    points: list[Point]
    last_exhaustive: int | None
    first_non_exhaustive: int | None
    last_proven_optimal: int | None
    first_unproven: int | None
    stop_reason: str


def walk_axis(
    *,
    axis: str,
    values: list[int],
    conservative: bool,
    context_size: int,
    hops: int,
    n_sinks: int,
    seed: int,
    witness_cap: int,
    exact_budget: int,
    time_budget_ms: float,
    chain_width: int = 1,
) -> AxisWalk:
    points: list[Point] = []
    last_exhaustive: int | None = None
    first_non_exhaustive: int | None = None
    last_proven: int | None = None
    first_unproven: int | None = None
    stop_reason = "axis exhausted"

    for v in values:
        kwargs = {
            "context_size": context_size,
            "hops": hops,
            "n_sinks": n_sinks,
            "chain_width": chain_width,
            "seed": seed,
        }
        kwargs[axis] = v
        p = run_point(
            conservative=conservative,
            witness_cap=witness_cap,
            exact_budget=exact_budget,
            **kwargs,
        )
        points.append(p)

        if p.enumeration_exhaustive:
            last_exhaustive = v
        elif first_non_exhaustive is None:
            first_non_exhaustive = v

        if p.exact_status == "optimal":
            last_proven = v
        elif first_unproven is None:
            first_unproven = v

        # Stop as soon as both limits are known, or wall time blows up.
        if first_non_exhaustive is not None and first_unproven is not None:
            stop_reason = "both limits found"
            break
        if p.enumeration_ms + p.exact_ms > time_budget_ms:
            stop_reason = (
                f"time budget exceeded at {axis}={v} "
                f"({p.enumeration_ms + p.exact_ms:.0f} ms)"
            )
            break

    return AxisWalk(
        axis=axis,
        mode="P1_conservative" if conservative else "P0_tight",
        fixed={
            k: v
            for k, v in (
                ("context_size", context_size),
                ("hops", hops),
                ("n_sinks", n_sinks),
                ("chain_width", chain_width),
            )
            if k != axis
        },
        points=points,
        last_exhaustive=last_exhaustive,
        first_non_exhaustive=first_non_exhaustive,
        last_proven_optimal=last_proven,
        first_unproven=first_unproven,
        stop_reason=stop_reason,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 0.5 tractability frontier")
    ap.add_argument("--out", default="tmp/phase05_frontier.json")
    ap.add_argument("--witness-cap", type=int, default=50_000)
    ap.add_argument("--exact-budget", type=int, default=400_000)
    ap.add_argument("--time-budget-ms", type=float, default=20_000)
    ap.add_argument("--max-hops", type=int, default=16)
    ap.add_argument("--max-context", type=int, default=48)
    ap.add_argument("--max-sinks", type=int, default=12)
    ap.add_argument("--max-width", type=int, default=8)
    args = ap.parse_args()

    walks: list[AxisWalk] = []

    for conservative in (True, False):
        # hops axis: the dominant driver of proof-tree count
        walks.append(
            walk_axis(
                axis="hops",
                values=list(range(1, args.max_hops + 1)),
                conservative=conservative,
                context_size=8,
                hops=1,
                n_sinks=1,
                seed=0,
                witness_cap=args.witness_cap,
                exact_budget=args.exact_budget,
                time_budget_ms=args.time_budget_ms,
            )
        )
        # context axis: P1 fan-in
        walks.append(
            walk_axis(
                axis="context_size",
                values=[2, 4, 8, 12, 16, 24, 32, 48][
                    : len([c for c in [2, 4, 8, 12, 16, 24, 32, 48]
                           if c <= args.max_context])
                ],
                conservative=conservative,
                context_size=2,
                hops=4,
                n_sinks=1,
                seed=0,
                witness_cap=args.witness_cap,
                exact_budget=args.exact_budget,
                time_budget_ms=args.time_budget_ms,
            )
        )
        # sinks axis: |Q_sigma|
        walks.append(
            walk_axis(
                axis="n_sinks",
                values=list(range(1, args.max_sinks + 1)),
                conservative=conservative,
                context_size=8,
                hops=4,
                n_sinks=1,
                seed=0,
                witness_cap=args.witness_cap,
                exact_budget=args.exact_budget,
                time_budget_ms=args.time_budget_ms,
            )
        )
        # width axis at fixed depth: branching proof trees
        walks.append(
            walk_axis(
                axis="chain_width",
                values=list(range(1, args.max_width + 1)),
                conservative=conservative,
                context_size=4,
                hops=4,
                n_sinks=1,
                seed=0,
                witness_cap=args.witness_cap,
                exact_budget=args.exact_budget,
                time_budget_ms=args.time_budget_ms,
            )
        )
        # depth axis at fixed width 3: the combined blowup
        walks.append(
            walk_axis(
                axis="hops",
                values=list(range(1, args.max_hops + 1)),
                conservative=conservative,
                context_size=4,
                hops=1,
                n_sinks=1,
                chain_width=3,
                seed=0,
                witness_cap=args.witness_cap,
                exact_budget=args.exact_budget,
                time_budget_ms=args.time_budget_ms,
            )
        )

    payload = {
        "walks": [
            {
                "axis": w.axis,
                "mode": w.mode,
                "fixed": w.fixed,
                "last_exhaustive": w.last_exhaustive,
                "first_non_exhaustive": w.first_non_exhaustive,
                "last_proven_optimal": w.last_proven_optimal,
                "first_unproven": w.first_unproven,
                "stop_reason": w.stop_reason,
                "points": [asdict(p) for p in w.points],
            }
            for w in walks
        ]
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"walks: {len(walks)}  ->  {out}\n")
    for w in walks:
        tail = w.points[-1]
        print(
            f"[{w.mode}] axis={w.axis:<13} fixed={w.fixed}\n"
            f"   witnesses at {w.axis}={getattr(tail, w.axis)}: {tail.witnesses}"
            f"  (enum {tail.enumeration_ms:.0f} ms, exact {tail.exact_ms:.0f} ms)\n"
            f"   last exhaustive={w.last_exhaustive}  first non-exhaustive="
            f"{w.first_non_exhaustive}\n"
            f"   last proven optimal={w.last_proven_optimal}  first unproven="
            f"{w.first_unproven}\n"
            f"   stop: {w.stop_reason}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
