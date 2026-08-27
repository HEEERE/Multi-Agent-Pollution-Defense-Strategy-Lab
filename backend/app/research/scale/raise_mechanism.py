"""RAISE asymmetric mechanism (v4 plan §3.7, §4.1, §5.2–5.3, §6.6).

Formalises the propose/veto relationship between tight graph (P0) and
conservative graph (P1):

  - Tight graph (P0):   proposes retention candidates only.
  - Conservative graph (P1): vetoes — has sole authority to certify.

An independent checker (checker.py, no solvers.py import) runs on the
conservative graph and must return COVERED before a RetentionCertificate
is issued.  Post-state re-verification re-runs witness enumeration after
applying the intervention set; any residual triggers rollback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.research.scale.analysis import (
    Witness,
    classify,
    clean_e,
    enumerate_witnesses,
    removed_versions,
    sink_reachable,
)
from app.research.scale.baselines import Outcome, RepairPolicy, score
from app.research.scale.checker import IndependentChecker
from app.research.scale.graph import Hypergraph, InterventionKind, VersionKind
from app.research.scale.solvers import greedy_cover


class SolveStatus(StrEnum):
    COVERED = "COVERED"
    """Checker returned exhaustive + zero residual witnesses."""
    UNSAFE = "UNSAFE"
    """Checker found at least one residual witness."""
    UNKNOWN = "UNKNOWN"
    """Enumeration hit the budget; safety conclusion is unavailable."""
    ROLLBACK = "ROLLBACK"
    """Post-state re-verification found witnesses; retention was rolled back."""


@dataclass(frozen=True)
class RetentionCandidate:
    """A version proposed for retention by the tight graph (P0)."""

    vid: str
    """Version identifier."""
    reason: str = "contaminated_unreachable_in_tight"


@dataclass
class RetentionCertificate:
    """Issued when post-state re-verification on the conservative graph passes.

    A certificate binds the exact intervention set and the set of retained
    versions it covers.  It is valid only when ``status == COVERED`` and
    ``post_state_exhaustive`` is True.
    """

    status: SolveStatus
    intervention_set: frozenset[str]
    retained_versions: frozenset[str]
    post_state_witnesses: int
    post_state_exhaustive: bool
    proposed_count: int
    """How many candidates P0 put forward."""
    vetoed_count: int
    """How many P0 candidates were removed by the P1 veto step."""

    @property
    def valid(self) -> bool:
        """True iff the certificate actually permits retention."""
        return (
            self.status is SolveStatus.COVERED
            and self.post_state_exhaustive
            and self.post_state_witnesses == 0
        )


@dataclass
class RAISEResult:
    """Full output of one raise_solve() call."""

    outcome: Outcome
    certificate: RetentionCertificate
    candidates_proposed: list[RetentionCandidate] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tight-graph proposal  (P0 role: propose only)
# ---------------------------------------------------------------------------


def _propose_retention(
    tight_g: Hypergraph,
    conservative_g: Hypergraph,
    selected: set[str],
) -> list[RetentionCandidate]:
    """Enumerate contaminated-unreachable versions from the tight graph.

    P0 proposes; P1 vetoes.  This function only reads *tight_g* and must
    never be the final authority on what is retained — the conservative
    graph and independent checker own that decision.
    """
    # Intervention ids are catalogue-local. P1 normally has more derivations
    # than P0 and therefore a different opaque iid sequence. Retention proposal
    # needs only the versions removed by revoke/quarantine, so translate those
    # two kinds by semantic (kind, target); edge/deny ids stay P1-local.
    revoked: set[str] = set()
    for iid in selected:
        intervention = conservative_g.interventions[iid]
        if intervention.kind is InterventionKind.REVOKE_VERSION:
            if intervention.target in tight_g.versions:
                revoked.add(intervention.target)
        elif intervention.kind is InterventionKind.QUARANTINE_AGENT:
            revoked.update(
                version.vid
                for version in tight_g.versions.values()
                if version.agent == intervention.target
                and version.kind is not VersionKind.ARGUMENT
            )
    ce = clean_e(tight_g, revoked)
    reach = sink_reachable(tight_g, removed_versions=revoked)
    non_arg = {
        v.vid
        for v in tight_g.versions.values()
        if v.kind is not VersionKind.ARGUMENT
    }
    candidates = []
    for vid in non_arg:
        if vid in revoked:
            continue
        if ce.get(vid, False):
            continue  # already clean — not a retention candidate
        if vid not in reach:
            candidates.append(RetentionCandidate(vid=vid))
    return candidates


# ---------------------------------------------------------------------------
# Conservative-graph veto  (P1 role: veto authority)
# ---------------------------------------------------------------------------


def _veto(
    conservative_g: Hypergraph,
    candidates: list[RetentionCandidate],
    selected: set[str],
) -> frozenset[str]:
    """Keep only candidates that are also sink-unreachable in the *conservative* graph.

    P1 is the veto authority (v4 plan §4.1): a version retained by P0 must
    *also* be unreachable in P1 before it survives.
    """
    revoked = removed_versions(conservative_g, selected)
    reach_p1 = sink_reachable(conservative_g, removed_versions=revoked)
    return frozenset(
        c.vid for c in candidates if c.vid not in reach_p1 and c.vid not in revoked
    )


# ---------------------------------------------------------------------------
# Post-state re-verification
# ---------------------------------------------------------------------------


def post_state_verify(
    conservative_g: Hypergraph,
    selected: set[str],
    checker: IndependentChecker,
) -> tuple[SolveStatus, int, bool]:
    """Re-run witness enumeration after applying *selected*.

    Returns (status, residual_count, exhaustive).

    The conservative graph is the only input to this check — it is the veto
    authority and must also be the source of truth for post-state safety.
    """
    result = checker.check(conservative_g, selected)
    if not result.exhaustive:
        return SolveStatus.UNKNOWN, len(result.residual_witnesses), False
    if result.residual_witnesses:
        return SolveStatus.UNSAFE, len(result.residual_witnesses), True
    return SolveStatus.COVERED, 0, True


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def raise_solve(
    tight_g: Hypergraph,
    conservative_g: Hypergraph,
    *,
    checker: IndependentChecker | None = None,
    witness_cap: int = 200_000,
) -> RAISEResult:
    """Run the full RAISE asymmetric mechanism.

    Steps
    -----
    1. Enumerate witnesses on *conservative_g* (the safety-authoritative graph).
    2. Solve for an intervention set using a greedy cover on *conservative_g*.
    3. Propose retention candidates from *tight_g* (P0 propose-only).
    4. Veto candidates that are reachable in *conservative_g* (P1 veto).
    5. Post-state re-verify on *conservative_g* via *checker* (independent path).
    6. If COVERED: issue RetentionCertificate and return final Outcome.
       If UNSAFE/UNKNOWN: roll back retention, return conservative-only Outcome.
    """
    if checker is None:
        checker = IndependentChecker(cap=witness_cap)

    # Step 1 — witnesses on conservative graph
    enum = enumerate_witnesses(conservative_g, cap=witness_cap)
    witnesses: list[Witness] = enum.witnesses

    # Step 2 — greedy cover on conservative graph
    solve_result = greedy_cover(conservative_g, witnesses)
    selected = set(solve_result.selected)

    # Step 3 — P0 proposes retention candidates
    candidates = _propose_retention(tight_g, conservative_g, selected)

    # Step 4 — P1 vetoes
    certified_retained = _veto(conservative_g, candidates, selected)
    vetoed_count = len(candidates) - len(certified_retained)

    # Step 5 — independent post-state re-verification on conservative graph
    status, residual_count, exhaustive = post_state_verify(
        conservative_g, selected, checker
    )

    # Step 6 — issue certificate or roll back
    if status is SolveStatus.COVERED:
        # Retention stands: use ASYMMETRIC repair policy so score() computes
        # retained versions correctly via apply_repair.
        outcome = score(
            conservative_g,
            witnesses,
            "RAISE-asymmetric",
            selected,
            RepairPolicy.ASYMMETRIC,
            solver_status=solve_result.status,
            exhaustive=enum.exhaustive,
        )
        cert_status = SolveStatus.COVERED
    else:
        # Roll back: fall through to support-preserving (conservative-only).
        outcome = score(
            conservative_g,
            witnesses,
            "RAISE-conservative",
            selected,
            RepairPolicy.SUPPORT_PRESERVING,
            solver_status=solve_result.status,
            exhaustive=enum.exhaustive,
        )
        certified_retained = frozenset()
        cert_status = SolveStatus.ROLLBACK if status is SolveStatus.UNSAFE else SolveStatus.UNKNOWN

    cert = RetentionCertificate(
        status=cert_status,
        intervention_set=frozenset(selected),
        retained_versions=certified_retained,
        post_state_witnesses=residual_count,
        post_state_exhaustive=exhaustive,
        proposed_count=len(candidates),
        vetoed_count=vetoed_count,
    )

    return RAISEResult(
        outcome=outcome,
        certificate=cert,
        candidates_proposed=candidates,
    )
