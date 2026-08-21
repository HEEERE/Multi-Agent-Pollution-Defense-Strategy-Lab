"""Label enforcement for retained contaminated versions (v4 plan §3.7, §6.6, §9.3 X-A4).

Theorem 5 (retention safety) holds only when every `retained` version cannot
reach a protected sink.  But that reachability guarantee applies to the graph
*at the moment of certification*.  Label enforcement provides a second, static
guard: it checks that retained versions have not appeared as ancestors of any
E2/E3 action argument, and that no such version could have reached a sink by
the time a check is requested.

The invariant that must always hold:
    label_enforcement_violations == 0

A violation means a `retained` version appeared in the origin closure of an E2
or E3 argument — an event that invalidates the retention certificate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.research.scale.analysis import sink_reachable
from app.research.scale.graph import Hypergraph, InterventionKind, VersionKind


# ---------------------------------------------------------------------------
# Effect-level classification (mirrors §6.4 / §8.3 semantics)
# ---------------------------------------------------------------------------

class EffectLevel:
    """Symbolic effect levels for enforcement decisions."""
    E0 = 0   # pure/read
    E1 = 1   # internal write
    E2 = 2   # external reversible
    E3 = 3   # external irreversible


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class LabelEnforcementResult:
    """Result of one label-enforcement check.

    label_enforcement_violations must remain 0 for the retention certificate
    to stay valid.  Any non-zero count must immediately trigger invalidation
    of the corresponding retained versions (state transition: retained →
    invalidated).
    """

    label_enforcement_violations: int
    """Count of retained versions found in any E2/E3 argument's origin closure."""

    violating_retained_versions: frozenset[str]
    """Specific retained version IDs whose paths were found in restricted sinks."""

    reachability_violations: frozenset[str]
    """Retained versions that have become sink-reachable since certification.

    These must be invalidated at the next action boundary per §6.6 state
    machine: ``retained`` → ``invalidated`` when reachability changes.
    """

    @property
    def passed(self) -> bool:
        """True only when zero enforcement violations and zero reachability violations."""
        return (
            self.label_enforcement_violations == 0
            and not self.reachability_violations
        )


# ---------------------------------------------------------------------------
# Enforcement checker
# ---------------------------------------------------------------------------


def check_label_enforcement(
    g: Hypergraph,
    retained_versions: frozenset[str],
    selected_interventions: set[str],
) -> LabelEnforcementResult:
    """Check that no retained version violates label enforcement rules.

    Two checks are performed:

    1. **Sink reachability** — any retained version that is now reachable from
       a protected sink in the post-intervention graph must be flagged for
       immediate invalidation.  This implements the action-boundary recheck
       required by §6.6 and theorem 5.

    2. **E2/E3 argument ancestry** — retained versions must not appear in the
       backward closure of any sink argument.  In the model, sinks represent
       E2/E3 action arguments, so any retained version in a sink's ancestor
       set constitutes a label enforcement violation.

    Parameters
    ----------
    g:
        The conservative graph (P1).  This is the only graph authorised to
        determine reachability for enforcement purposes.
    retained_versions:
        The frozenset from the current RetentionCertificate.
    selected_interventions:
        The intervention set X that was applied.  Provided to compute
        the post-state residual graph for reachability checks.
    """
    if not retained_versions:
        return LabelEnforcementResult(
            label_enforcement_violations=0,
            violating_retained_versions=frozenset(),
            reachability_violations=frozenset(),
        )

    # Derive the set of versions removed by the intervention set.
    removed: set[str] = set()
    removed_edges: set[str] = set()
    for iid in selected_interventions:
        if iid not in g.interventions:
            continue
        i = g.interventions[iid]
        if i.kind is InterventionKind.REVOKE_VERSION:
            removed.add(i.target)
        elif i.kind is InterventionKind.DISABLE_EDGE:
            removed_edges.add(i.target)
        elif i.kind is InterventionKind.QUARANTINE_AGENT:
            removed |= {
                v.vid
                for v in g.versions.values()
                if v.agent == i.target and v.kind is not VersionKind.ARGUMENT
            }

    # Check 1: sink reachability in the post-intervention graph.
    # Retained versions must be sink-unreachable after X is applied.
    # This is guaranteed at certification time by the veto step, but label
    # enforcement re-checks it because new activities may have been added at
    # an action boundary since the certificate was issued (attack family 15).
    post_reach = sink_reachable(
        g,
        removed_versions=removed,
        removed_edges=removed_edges,
    )
    reachability_violations = retained_versions & post_reach

    # Check 2: E2/E3 argument ancestry in the post-intervention graph.
    # A retained version must not appear in the backward closure of any
    # protected sink *after* the interventions are applied.  In the model,
    # sinks represent E2/E3 action arguments.  We intentionally use the
    # post-intervention graph here — retained versions are, by construction,
    # ancestors of sinks in the original graph (they are contaminated); the
    # enforcement guarantee is only that they cannot reach sinks *after X*.
    e2e3_violations = reachability_violations  # same predicate, separate semantic name

    # Both checks reduce to the same reachability test in this model.
    # We keep them distinct for diagnostic clarity and future extension.
    violation_count = len(reachability_violations)

    return LabelEnforcementResult(
        label_enforcement_violations=violation_count,
        violating_retained_versions=e2e3_violations,
        reachability_violations=reachability_violations,
    )
