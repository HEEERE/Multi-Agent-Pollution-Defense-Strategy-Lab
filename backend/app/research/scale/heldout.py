"""Frozen Phase 6 held-out mechanism graph population.

This module is data, not a tuning surface.  Any change to a template, seed
range, ordering, or canonicalisation changes ``DATASET_SHA256`` and therefore
requires a new preregistration version before results are inspected.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

from app.research.scale.graph import GenSpec


DATASET_ID = "majd-mechanism-heldout-graphs-v1"
SEEDS = tuple(range(10, 30))


def heldout_specs() -> tuple[GenSpec, ...]:
    specs: list[GenSpec] = []
    for seed in SEEDS:
        specs.extend((
            GenSpec(
                context_size=4, hops=3, n_sinks=2,
                chain_width=2, seed=seed,
            ),
            GenSpec(
                context_size=8, hops=4, n_sinks=2,
                chain_width=3, seed=seed,
            ),
            GenSpec(
                context_size=6, hops=3, n_sinks=3,
                chain_width=2, and_edge_prob=0.5, seed=seed,
            ),
            GenSpec(
                context_size=4, hops=4, n_sinks=1,
                chain_width=2, side_branch_per_hop=2,
                n_goals=4, seed=seed,
            ),
            GenSpec(
                context_size=8, hops=2, n_sinks=2,
                chain_width=2, low_integrity_ratio=0.6,
                n_goals=5, seed=seed,
            ),
        ))
    return tuple(specs)


CANONICAL_JSON = json.dumps(
    [asdict(spec) for spec in heldout_specs()],
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
DATASET_SHA256 = hashlib.sha256(CANONICAL_JSON).hexdigest()


assert len(heldout_specs()) == 100
