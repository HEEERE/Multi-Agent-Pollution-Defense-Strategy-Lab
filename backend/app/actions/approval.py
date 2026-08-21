from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class HumanApprovalEstimate:
    expected_e3_actions: int
    estimated_reviews: int
    review_cost: float
    objective_cost: float
    ratio: float
    max_ratio: float

    @property
    def admitted(self) -> bool:
        return self.ratio <= self.max_ratio


def estimate_human_approval_cost(
    *,
    expected_e3_actions: int,
    max_reissues: int,
    cost_per_review: float,
    projected_objective_cost: float,
    max_ratio: float = 0.25,
) -> HumanApprovalEstimate:
    """Phase 3 admission estimate for human review cost.

    One review can cover the initial action and at most ``max_reissues``
    identical-scope reissues. The estimate is deliberately conservative and
    does not assume cross-scope certificate reuse.
    """
    if expected_e3_actions < 0 or max_reissues < 0:
        raise ValueError("action and reissue counts must be non-negative")
    if cost_per_review < 0 or projected_objective_cost <= 0:
        raise ValueError("costs must be non-negative and objective cost positive")
    if not 0 <= max_ratio <= 1:
        raise ValueError("max_ratio must be between 0 and 1")
    reviews = math.ceil(expected_e3_actions / (max_reissues + 1))
    review_cost = reviews * cost_per_review
    ratio = review_cost / projected_objective_cost
    return HumanApprovalEstimate(
        expected_e3_actions,
        reviews,
        review_cost,
        projected_objective_cost,
        ratio,
        max_ratio,
    )
