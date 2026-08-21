"""Three-state completeness judgment for the independent checker (v4 plan §4.2).

Formalises the checker_result enum from §4.2:

  EXHAUSTIVE_NO_WITNESS  — enumeration completed, zero residual witnesses;
                           the only state that supports signing a certificate.
  WITNESS_FOUND          — at least one residual witness survived X.
  BUDGET_EXHAUSTED       — cap hit before exhaustion; safety claim unavailable.

Only EXHAUSTIVE_NO_WITNESS supports §5.3 scoped authority safety (theorem 1′).
BUDGET_EXHAUSTED maps to SolveStatus.UNKNOWN and may only produce a diagnostic
certificate — it must never gate a retention or action_safety certificate.
"""
from __future__ import annotations

from enum import StrEnum


class CheckerCompleteness(StrEnum):
    EXHAUSTIVE_NO_WITNESS = "EXHAUSTIVE_NO_WITNESS"
    """All witnesses enumerated; none survived the intervention set X.
    Gate condition for RetentionCertificate.valid and action_safety certificates."""

    WITNESS_FOUND = "WITNESS_FOUND"
    """At least one residual witness exists; X does not cover the graph."""

    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    """Enumeration hit the cap; universe is only partially explored.
    Mapped to SolveStatus.UNKNOWN — E2/E3 fail closed (§8.2)."""


def completeness_from_check(exhaustive: bool, has_residual: bool) -> CheckerCompleteness:
    """Derive the three-state judgment from raw CheckResult fields.

    WITNESS_FOUND takes precedence over the exhaustive flag: a partial
    enumeration that already found a residual witness is conclusive regardless
    of what the unseen remainder contains.
    """
    if has_residual:
        return CheckerCompleteness.WITNESS_FOUND
    if exhaustive:
        return CheckerCompleteness.EXHAUSTIVE_NO_WITNESS
    return CheckerCompleteness.BUDGET_EXHAUSTED
