"""Independent residual checker (v4 plan §4.2 / §8.1 COVERED state).

Structural isolation: this module imports nothing from solvers.py.
Break sets are re-derived here via analysis.break_set so a bug in the
optimiser cannot self-verify — the checker and the solver share no code
path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.research.scale.analysis import Witness, break_set, enumerate_witnesses
from app.research.scale.graph import Hypergraph


@dataclass
class CheckResult:
    """Output of one IndependentChecker.check() call."""

    residual_witnesses: list[Witness]
    exhaustive: bool
    """True when the full witness universe was enumerated (cap not hit)."""
    total_enumerated: int = 0
    """Total witnesses found by the checker's own enumeration pass."""

    @property
    def passed(self) -> bool:
        """True iff exhaustive=True and no residual witnesses.

        Maps to the COVERED state in v4 plan §8.1.  A non-exhaustive
        enumeration is UNKNOWN, never COVERED — it cannot gate a
        RetentionCertificate.
        """
        return self.exhaustive and not self.residual_witnesses


class IndependentChecker:
    """Check whether intervention set X covers all witnesses.

    No import of solvers.py.  Break sets are re-derived via
    analysis.break_set, giving an independent implementation path that
    cannot share a defect with the optimiser.
    """

    def __init__(self, cap: int = 200_000) -> None:
        self._cap = cap

    def check(self, g: Hypergraph, x: set[str]) -> CheckResult:
        """Enumerate witnesses independently and return any not broken by X.

        A witness is broken by X when at least one element of X appears
        in its break set.  The break-set derivation here is independent
        of the derivation inside the solver.
        """
        enum = enumerate_witnesses(g, cap=self._cap)
        residual = [w for w in enum.witnesses if not (x & break_set(g, w))]
        return CheckResult(
            residual_witnesses=residual,
            exhaustive=enum.exhaustive,
            total_enumerated=len(enum.witnesses),
        )

    def has_residual(self, g: Hypergraph, x: set[str]) -> bool | None:
        """Quick membership check for pipeline use.

        Returns
        -------
        True
            A residual witness was found — X does not cover.
        False
            No residual found and enumeration was exhaustive — COVERED.
        None
            Enumeration hit the budget (BUDGET_EXHAUSTED) — cannot conclude.
        """
        r = self.check(g, x)
        if r.residual_witnesses:
            return True
        return False if r.exhaustive else None
