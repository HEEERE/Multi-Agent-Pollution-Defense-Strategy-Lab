"""Synthetic versioned execution hypergraph for the Phase 0.5 scale study.

Mirrors the v4 plan's definition 1 (section 3.1) with the minimum structure the
scale questions need:

* immutable entity versions with an integrity label
* causal influence records (``Derivation``) carrying one or more parents
* protected sinks (``Q``)
* candidate interventions (``Gamma``)

A generated graph is a DAG by construction: parents always have a strictly
smaller topological index than their child, which satisfies assumption A5.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import StrEnum


class Integrity(StrEnum):
    LOW = "low"
    HIGH = "high"


class VersionKind(StrEnum):
    RAG_CHUNK = "rag_chunk"
    MESSAGE = "message"
    MEMORY = "memory"
    SUMMARY = "summary"
    PLAN = "plan"
    TOOL_RESULT = "tool_result"
    ARGUMENT = "argument"


@dataclass(frozen=True)
class Version:
    """One immutable entity version."""

    vid: str
    kind: VersionKind
    integrity: Integrity
    topo_index: int
    agent: str = ""
    """Owning agent. Needed by node-quarantine baselines, which act on agents
    rather than on individual versions."""

    @property
    def is_source(self) -> bool:
        return self.kind in (VersionKind.RAG_CHUNK, VersionKind.MESSAGE)


@dataclass(frozen=True)
class SupportGroup:
    """One AND group of evidence supporting a task goal (an element of Δ_S).

    Several groups for the same goal are OR alternatives. Without this layer the
    task-loss term of J(X) cannot be computed at all, and a containment-only
    strategy would score identically to a recovery-aware one -- which is exactly
    the comparison H2 rests on.
    """

    sid: str
    goal: str
    members: tuple[str, ...]
    verified: bool = True
    """Only deterministic/verified groups may establish support. A P2-inferred
    group must not keep a goal alive on its own."""


@dataclass(frozen=True)
class Goal:
    """A canonical task goal the run is supposed to achieve."""

    gid: str
    required: bool = True
    value: float = 1.0


@dataclass(frozen=True)
class Derivation:
    """One causal influence record: ``parents`` jointly influenced ``child``.

    ``parents`` with more than one element is an AND hyperedge (P0 structured
    evidence). P1 conservative mode emits one single-parent record per visible
    input instead, so a child then owns many single-parent records.
    """

    did: str
    parents: tuple[str, ...]
    child: str
    activity: str

    @property
    def is_and_edge(self) -> bool:
        return len(self.parents) > 1


@dataclass(frozen=True)
class Sink:
    """A protected action argument (an element of ``Q``)."""

    qid: str
    version_id: str
    effect_class: str


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


@dataclass
class Hypergraph:
    versions: dict[str, Version] = field(default_factory=dict)
    derivations: dict[str, Derivation] = field(default_factory=dict)
    sinks: list[Sink] = field(default_factory=list)
    interventions: dict[str, Intervention] = field(default_factory=dict)
    goals: dict[str, Goal] = field(default_factory=dict)
    support: dict[str, SupportGroup] = field(default_factory=dict)

    # ---- topology helpers -------------------------------------------------
    _by_child: dict[str, list[str]] | None = field(default=None, repr=False)
    _by_parent: dict[str, list[str]] | None = field(default=None, repr=False)

    def index(self) -> None:
        by_child: dict[str, list[str]] = {}
        by_parent: dict[str, list[str]] = {}
        for d in self.derivations.values():
            by_child.setdefault(d.child, []).append(d.did)
            for p in d.parents:
                by_parent.setdefault(p, []).append(d.did)
        self._by_child = by_child
        self._by_parent = by_parent

    def incoming(self, vid: str) -> list[Derivation]:
        if self._by_child is None:
            self.index()
        assert self._by_child is not None
        return [self.derivations[d] for d in self._by_child.get(vid, ())]

    def outgoing(self, vid: str) -> list[Derivation]:
        if self._by_parent is None:
            self.index()
        assert self._by_parent is not None
        return [self.derivations[d] for d in self._by_parent.get(vid, ())]

    @property
    def low_integrity_sources(self) -> set[str]:
        return {
            v.vid
            for v in self.versions.values()
            if v.is_source and v.integrity is Integrity.LOW
        }

    @property
    def agents(self) -> set[str]:
        return {v.agent for v in self.versions.values() if v.agent}

    def versions_of(self, agent: str) -> set[str]:
        return {v.vid for v in self.versions.values() if v.agent == agent}

    def support_for(self, goal: str) -> list[SupportGroup]:
        return [s for s in self.support.values() if s.goal == goal]

    @property
    def required_goals(self) -> list[str]:
        return sorted(g.gid for g in self.goals.values() if g.required)

    def activities(self) -> set[str]:
        return {d.activity for d in self.derivations.values()}

    def activity_of(self, vid: str) -> str:
        inc = self.incoming(vid)
        return inc[0].activity if inc else ""

    def stats(self) -> dict[str, int]:
        return {
            "versions": len(self.versions),
            "derivations": len(self.derivations),
            "and_edges": sum(1 for d in self.derivations.values() if d.is_and_edge),
            "sinks": len(self.sinks),
            "interventions": len(self.interventions),
        }


@dataclass(frozen=True)
class GenSpec:
    """Generation parameters for one synthetic run."""

    context_size: int
    """Visible inputs per LLM activity. Drives P1 fan-in."""

    hops: int
    """Length of the agent/memory chain from source to sink."""

    n_sinks: int
    """Number of protected sinks (|Q_sigma|)."""

    seed: int = 0

    low_integrity_ratio: float = 0.34
    """Fraction of source versions that carry integrity=low."""

    side_branch_per_hop: int = 2
    """Versions produced per hop that do NOT lead to any sink.

    These are the candidates for ``contaminated_unreachable`` retention, i.e.
    the population the asymmetric mechanism is designed to rescue.
    """

    chain_width: int = 1
    """Sink-feeding versions produced per hop.

    With width 1 the sink-bound chain is a single line, so a P1 proof tree
    degenerates to a path and the witness count grows linearly. Real deployments
    produce several artifacts per hop that all remain visible downstream; each
    then contributes its own conservative influence edge, and the number of
    minimal proof trees grows like ``chain_width ** hops``. This is the axis that
    actually drives the enumeration frontier.
    """

    and_edge_prob: float = 0.25
    """Probability that a structured (P0) step is a multi-parent AND edge."""

    n_goals: int = 3
    """Task goals. Each gets one support group drawn from the contaminated chain
    and, for some goals, a second independent group drawn from clean side state.
    A strategy that wipes all descendants loses the first kind; one that keeps
    verified alternative support does not."""

    independent_support_ratio: float = 0.5
    """Fraction of goals that also have a clean, independent support group. This
    is the population that separates support-preserving repair from descendant
    wipe."""

    n_agents: int = 3
    """Agents owning the versions. Node-quarantine baselines act at this
    granularity, so a coarse agent partition is what makes them blunt."""


def generate(spec: GenSpec, *, conservative: bool) -> Hypergraph:
    """Build one synthetic graph.

    ``conservative=True`` emits the P1 graph: every visible input of an LLM
    activity becomes its own single-parent influence record, so a child version
    has ``context_size`` incoming records. ``conservative=False`` emits the tight
    P0 graph: only the structurally bound parents are recorded.
    """

    rng = random.Random(spec.seed)
    g = Hypergraph()
    topo = 0

    def add_version(
        kind: VersionKind, integrity: Integrity, agent: str = ""
    ) -> Version:
        nonlocal topo
        v = Version(
            vid=f"v{topo}",
            kind=kind,
            integrity=integrity,
            topo_index=topo,
            agent=agent or f"agent_{topo % max(1, spec.n_agents)}",
        )
        g.versions[v.vid] = v
        topo += 1
        return v

    # --- layer 0: the visible-input pool (RAG chunks and inbound messages) ---
    # sources[0] is always low integrity: it is the injected attack entry point.
    # Without it a generated graph can contain no witness at all, which would
    # make the scale numbers meaningless.
    sources: list[Version] = []
    for i in range(spec.context_size):
        low = True if i == 0 else rng.random() < spec.low_integrity_ratio
        kind = VersionKind.RAG_CHUNK if i % 2 == 0 else VersionKind.MESSAGE
        sources.append(add_version(kind, Integrity.LOW if low else Integrity.HIGH))

    # --- the main chain that terminates in the protected sinks ---------------
    chain_kinds = [
        VersionKind.MEMORY,
        VersionKind.SUMMARY,
        VersionKind.PLAN,
        VersionKind.TOOL_RESULT,
    ]
    frontier: list[Version] = sources
    chain_tail: Version = sources[0]
    unreachable_pool: list[Version] = []
    did = 0

    def add_derivation(parents: tuple[str, ...], child: str, activity: str) -> None:
        nonlocal did
        d = Derivation(did=f"d{did}", parents=parents, child=child, activity=activity)
        g.derivations[d.did] = d
        did += 1

    # A high-integrity source used as the structured parent of side branches.
    # In P0 the binding is exact, so side branches stay clean; in P1 the same
    # activity is charged with every visible input and therefore inherits the
    # injected contamination. That difference is the L1 effect being measured.
    clean_source = next(
        (v for v in sources if v.integrity is Integrity.HIGH), sources[-1]
    )

    chain_layer: list[Version] = []
    for hop in range(spec.hops):
        kind = chain_kinds[hop % len(chain_kinds)]
        activity = f"act_{hop}"
        layer: list[Version] = []

        for w in range(max(1, spec.chain_width)):
            produced = add_version(kind, Integrity.HIGH)
            layer.append(produced)
            step_activity = activity if w == 0 else f"{activity}_w{w}"

            if conservative:
                # P1: one single-parent conservative edge per visible input.
                for p in frontier:
                    add_derivation((p.vid,), produced.vid, step_activity)
            else:
                # P0: structured binding only. Either a single bound parent or a
                # verified multi-parent AND group. The chain deliberately carries
                # the injected source so a witness always exists in both modes.
                if rng.random() < spec.and_edge_prob and len(frontier) >= 2:
                    picks = tuple(v.vid for v in rng.sample(frontier, 2))
                    if chain_tail.vid not in picks:
                        picks = (chain_tail.vid, *picks[:1])
                    add_derivation(picks, produced.vid, step_activity)
                else:
                    add_derivation((chain_tail.vid,), produced.vid, step_activity)

        chain_layer = layer
        produced = layer[0]

        # Side branches: derived from the same context but never feeding a sink.
        for b in range(spec.side_branch_per_hop):
            side = add_version(VersionKind.SUMMARY, Integrity.HIGH)
            side_activity = f"act_{hop}_side{b}"
            if conservative:
                for p in frontier:
                    add_derivation((p.vid,), side.vid, side_activity)
            else:
                add_derivation((clean_source.vid,), side.vid, side_activity)
            unreachable_pool.append(side)

        chain_tail = produced
        # The next activity sees the whole freshly produced layer plus the
        # original context pool; this is what makes P1 fan-in persist across hops
        # and what turns proof trees from paths into branching trees.
        frontier = [*layer, *sources]

    # --- protected sinks: arguments derived from the last chain layer ---------
    final_layer = chain_layer or [chain_tail]
    for s in range(spec.n_sinks):
        arg = add_version(VersionKind.ARGUMENT, Integrity.HIGH)
        if conservative:
            for p in final_layer:
                add_derivation((p.vid,), arg.vid, f"sink_act_{s}")
        else:
            add_derivation((chain_tail.vid,), arg.vid, f"sink_act_{s}")
        g.sinks.append(
            Sink(qid=f"q{s}", version_id=arg.vid, effect_class="E3" if s == 0 else "E2")
        )

    # --- candidate interventions -------------------------------------------
    iid = 0

    def add_intervention(kind: InterventionKind, target: str, cost: float) -> None:
        nonlocal iid
        g.interventions[f"i{iid}"] = Intervention(
            iid=f"i{iid}", kind=kind, target=target, cost=cost
        )
        iid += 1

    # revoke_version on every non-argument version
    for v in g.versions.values():
        if v.kind is VersionKind.ARGUMENT:
            continue
        cost = 1.0 if v.is_source else 2.0
        add_intervention(InterventionKind.REVOKE_VERSION, v.vid, cost)

    # disable_edge on every derivation
    for d in g.derivations.values():
        add_intervention(InterventionKind.DISABLE_EDGE, d.did, 1.5)

    # deny_action per sink: expensive but always available
    for s in g.sinks:
        add_intervention(InterventionKind.DENY_ACTION, s.qid, 8.0)

    # quarantine_agent: coarse but cheap per unit of coverage. This is what a
    # node-level topology defense has available, and its bluntness is the point.
    for agent in sorted({v.agent for v in g.versions.values() if v.agent}):
        add_intervention(InterventionKind.QUARANTINE_AGENT, agent, 3.0)

    g.index()

    # --- task goals and their support groups ---------------------------------
    # Each goal gets one group drawn from the sink-bound (hence contaminated)
    # chain. Some goals additionally get a clean, independent group drawn from
    # side state. A descendant-wipe strategy loses the first kind outright; a
    # support-preserving one keeps any goal that still has a verified clean group.
    reachable = _backward_closure(g)
    chain_pool = [
        v.vid
        for v in g.versions.values()
        if v.vid in reachable and v.kind is not VersionKind.ARGUMENT
    ]
    clean_pool = [v.vid for v in unreachable_pool]

    sid = 0
    for gi in range(spec.n_goals):
        gid = f"g{gi}"
        g.goals[gid] = Goal(gid=gid, required=True, value=1.0)

        if chain_pool:
            picks = tuple(
                rng.sample(chain_pool, min(2, len(chain_pool)))
            )
            g.support[f"s{sid}"] = SupportGroup(
                sid=f"s{sid}", goal=gid, members=picks, verified=True
            )
            sid += 1

        if clean_pool and rng.random() < spec.independent_support_ratio:
            picks = tuple(rng.sample(clean_pool, min(2, len(clean_pool))))
            g.support[f"s{sid}"] = SupportGroup(
                sid=f"s{sid}", goal=gid, members=picks, verified=True
            )
            sid += 1

    return g


def _backward_closure(g: Hypergraph) -> set[str]:
    """Versions that can influence at least one sink."""
    seen: set[str] = set()
    stack = [s.version_id for s in g.sinks]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for d in g.incoming(cur):
            for p in d.parents:
                if p not in seen:
                    stack.append(p)
    return seen
