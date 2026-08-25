"""Intervention catalogue, intervention semantics and the real J(X) (v4 §5).

Three things live here because they are the shared ground truth that both the
optimiser and the independent checker must agree on:

* the candidate intervention set Γ and its unit costs;
* what an intervention *does* to the graph (``apply_interventions``);
* the real objective ``J(X) = C_op + λ·L_task + μ·C_replay + ν·C_human`` and the
  additive surrogate the greedy optimiser actually minimises.

Sharing intervention *semantics* between solver and checker is deliberate: if
they disagreed on what "revoke v" means they would be answering different
questions. What must not be shared is the *cover decision* — that is why
``verification/`` may import this module but never a solver (v4 §11.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.provenance.models import ArtifactKind
from app.provenance.projection import ProvenanceGraph

# Unit costs. Frozen before results are seen (v4 §5.1) and identical to the
# offline scale study so online and offline J(X) are directly comparable.
COST_REVOKE_SOURCE = 1.0
COST_REVOKE_DERIVED = 2.0
COST_DISABLE_EDGE = 1.5
COST_DENY_ACTION = 8.0
COST_QUARANTINE_AGENT = 3.0

# J(X) weights, also frozen before results are seen.
LAMBDA_TASK = 2.0
MU_REPLAY = 1.0
NU_HUMAN = 1.0

SOURCE_KINDS = frozenset({ArtifactKind.RAG_CHUNK, ArtifactKind.MESSAGE})


class InterventionKind(StrEnum):
    REVOKE_VERSION = "revoke_version"
    DISABLE_EDGE = "disable_edge"
    DENY_ACTION = "deny_action"
    QUARANTINE_AGENT = "quarantine_agent"


@dataclass(frozen=True)
class Intervention:
    iid: str
    kind: InterventionKind
    target: str
    cost: float


@dataclass(frozen=True)
class AppliedInterventions:
    """The residual-graph effect of an intervention set."""

    removed_versions: frozenset[str]
    removed_relations: frozenset[str]
    denied_sinks: frozenset[str]

    def versions_only(self) -> "AppliedInterventions":
        """Drop edge and sink effects, keeping only removed versions.

        Used by the retention decision. Crediting a disabled edge there would let
        a version be called sink-unreachable because one path was cut, which
        under-approximates reachability on the graph whose entire purpose is to
        over-approximate it (v4 axiom A). A denied action likewise does not make
        stored state unreachable — the argument is refused, the dependency stands.
        Safety checks, by contrast, *must* credit both.
        """
        return AppliedInterventions(self.removed_versions, frozenset(), frozenset())


def is_argument(graph: ProvenanceGraph, version_id: str) -> bool:
    artifact = graph.versions.get(version_id)
    return artifact is not None and artifact.kind is ArtifactKind.ARGUMENT


def principals(graph: ProvenanceGraph, version_id: str) -> frozenset[str]:
    artifact = graph.versions.get(version_id)
    return artifact.origin_principals if artifact else frozenset()


def candidate_interventions(
    graph: ProvenanceGraph, sink_versions: set[str]
) -> dict[str, Intervention]:
    """Build Γ for one snapshot.

    Argument versions get no ``revoke_version`` candidate: the sink argument is
    the thing being protected, so revoking it is modelled as ``deny_action``
    instead. Intervention ids are derived from the target rather than counted, so
    the same snapshot always yields the same catalogue and replays are stable.
    """
    out: dict[str, Intervention] = {}

    def add(kind: InterventionKind, target: str, cost: float) -> None:
        iid = f"{kind.value}:{target}"
        out[iid] = Intervention(iid=iid, kind=kind, target=target, cost=cost)

    for version_id, artifact in graph.versions.items():
        if artifact.kind is ArtifactKind.ARGUMENT:
            continue
        source = artifact.kind in SOURCE_KINDS
        add(
            InterventionKind.REVOKE_VERSION,
            version_id,
            COST_REVOKE_SOURCE if source else COST_REVOKE_DERIVED,
        )
    for relation_id in graph.derivations:
        add(InterventionKind.DISABLE_EDGE, relation_id, COST_DISABLE_EDGE)
    for sink in sorted(sink_versions):
        add(InterventionKind.DENY_ACTION, sink, COST_DENY_ACTION)
    agents: set[str] = set()
    for version_id, artifact in graph.versions.items():
        if artifact.kind is ArtifactKind.ARGUMENT:
            continue
        agents |= set(artifact.origin_principals)
    for agent in sorted(agents):
        add(InterventionKind.QUARANTINE_AGENT, agent, COST_QUARANTINE_AGENT)
    return out


def apply_interventions(
    graph: ProvenanceGraph,
    catalogue: dict[str, Intervention],
    selected: set[str],
) -> AppliedInterventions:
    """Expand an intervention set into its residual-graph effect.

    Quarantining an agent removes every non-argument version that agent owns, so
    it expands into the removed-version set rather than staying a separate case
    for every downstream consumer to re-handle.
    """
    removed: set[str] = set()
    relations: set[str] = set()
    denied: set[str] = set()
    for iid in selected:
        intervention = catalogue.get(iid)
        if intervention is None:
            continue
        if intervention.kind is InterventionKind.REVOKE_VERSION:
            removed.add(intervention.target)
        elif intervention.kind is InterventionKind.DISABLE_EDGE:
            relations.add(intervention.target)
        elif intervention.kind is InterventionKind.DENY_ACTION:
            denied.add(intervention.target)
        elif intervention.kind is InterventionKind.QUARANTINE_AGENT:
            removed |= {
                version_id
                for version_id, artifact in graph.versions.items()
                if intervention.target in artifact.origin_principals
                and artifact.kind is not ArtifactKind.ARGUMENT
            }
    return AppliedInterventions(frozenset(removed), frozenset(relations), frozenset(denied))


def surrogate_cost(catalogue: dict[str, Intervention], selected: set[str]) -> float:
    """The additive surrogate Ĉ(X) = Σ cost, which the greedy actually minimises.

    Additive by construction, so the weighted set-cover guarantee applies. It is
    an upper bound proxy for the real J(X) below, not a substitute: task loss and
    replay cost are not additive over interventions.
    """
    return sum(catalogue[iid].cost for iid in selected if iid in catalogue)


def human_cost(catalogue: dict[str, Intervention], selected: set[str]) -> float:
    """Interventions that need human sign-off.

    Agent quarantine and action denial are outward-facing and reversible only by
    a person; version revocation is internal. This is what makes blunt
    strategies expensive in a term that is not operational cost.
    """
    return sum(
        1.0
        for iid in selected
        if iid in catalogue
        and catalogue[iid].kind
        in (InterventionKind.QUARANTINE_AGENT, InterventionKind.DENY_ACTION)
    )


@dataclass
class CostBreakdown:
    """The four components of the real J(X), kept separate for reporting."""

    op_cost: float = 0.0
    task_loss: float = 0.0
    replay_cost: float = 0.0
    human_cost: float = 0.0

    goals_total: int = 0
    goals_supported: int = 0
    versions_total: int = 0
    versions_active: int = 0
    versions_retained: int = 0
    benign_invalidated: int = 0
    """Versions that passed Clean_E before any intervention and are now gone."""

    extra: dict[str, float] = field(default_factory=dict)

    def j(
        self,
        *,
        lam: float = LAMBDA_TASK,
        mu: float = MU_REPLAY,
        nu: float = NU_HUMAN,
    ) -> float:
        return self.op_cost + lam * self.task_loss + mu * self.replay_cost + nu * self.human_cost

    @property
    def task_utility(self) -> float:
        return self.goals_supported / self.goals_total if self.goals_total else 1.0

    @property
    def benign_preservation(self) -> float:
        total = self.versions_total
        return (total - self.benign_invalidated) / total if total else 1.0
