"""Witness enumeration, Clean_E, reachability and taint classification.

Implements the computational core of v4 plan sections 3.3, 3.5, 3.7 and 4.2 at
the fidelity the scale study needs. Deliberately simple and independent of the
online runtime so it can be brute-force checked.

Authorisation model used here: a sink argument is unauthorised iff its origin
closure contains at least one low-integrity source version. A *witness* is then
a minimal derivation proof (one incoming record chosen per derived node, all
parents of a chosen AND record included) whose leaf set contains a low-integrity
source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.research.scale.graph import (
    Hypergraph,
    Intervention,
    InterventionKind,
    VersionKind,
)

WITNESS_CAP_DEFAULT = 200_000


@dataclass(frozen=True)
class Witness:
    """A minimal unauthorised authority derivation proof rooted at one sink."""

    root_qid: str
    versions: frozenset[str]
    derivations: frozenset[str]

    def key(self) -> tuple:
        return (self.root_qid, self.versions, self.derivations)


@dataclass
class EnumerationResult:
    witnesses: list[Witness]
    exhaustive: bool
    """False when the cap was hit, i.e. the universe is only partially known."""

    visited_nodes: int = 0

    @property
    def count(self) -> int:
        return len(self.witnesses)


def iter_witnesses(g: Hypergraph):
    """Yield minimal unauthorised derivation proofs one at a time.

    Lazy on purpose. A caller with a budget can stop early and still keep every
    witness produced so far, which is how a separation oracle actually behaves:
    it looks for one residual witness, not the whole universe. Building the full
    list first would mean a budget stop loses everything it had found.
    """
    low_sources = g.low_integrity_sources
    seen: set[tuple] = set()

    def proofs(vid: str):
        """Yield (versions, derivations, touches_low_source) for ``vid``."""
        incoming = g.incoming(vid)
        if not incoming:
            yield frozenset({vid}), frozenset(), vid in low_sources
            return
        for d in incoming:
            # AND semantics: every parent of the chosen record must be proved.
            combos = [(frozenset({vid}), frozenset({d.did}), False)]
            for p in d.parents:
                merged = []
                for cv, cd, clow in combos:
                    for sv, sd, slow in proofs(p):
                        merged.append((cv | sv, cd | sd, clow or slow))
                combos = merged
                if not combos:
                    break
            yield from combos

    for sink in g.sinks:
        for vs, ds, low in proofs(sink.version_id):
            if not low:
                continue  # authorised: no low-integrity origin
            w = Witness(root_qid=sink.qid, versions=vs, derivations=ds)
            k = w.key()
            if k in seen:
                continue
            seen.add(k)
            yield w


def enumerate_witnesses(
    g: Hypergraph, *, cap: int = WITNESS_CAP_DEFAULT
) -> EnumerationResult:
    """Collect up to ``cap`` witnesses.

    ``exhaustive=False`` means the universe is bounded, not that nothing was
    found; ``witnesses`` is then a strict subset and ``count`` is a lower bound.
    Callers must not read a truncated result as a safety result (v4 plan section
    4.2 ``BUDGET_EXHAUSTED``).
    """
    out: list[Witness] = []
    truncated = False
    for w in iter_witnesses(g):
        if len(out) >= cap:
            truncated = True
            break
        out.append(w)
    return EnumerationResult(
        witnesses=out, exhaustive=not truncated, visited_nodes=len(out)
    )


def _enumerate_witnesses_eager(
    g: Hypergraph, *, cap: int = WITNESS_CAP_DEFAULT
) -> EnumerationResult:
    """Retained memoised implementation, used only to cross-check the generator.

    The lazy path above cannot memoise (a generator is consumed once), so it
    re-walks shared subtrees. This eager version memoises and must agree with it
    on any graph small enough to enumerate fully; ``test_scale_analysis`` asserts
    that agreement.
    """

    low_sources = g.low_integrity_sources
    visited = 0
    out: list[Witness] = []
    seen: set[tuple] = set()
    truncated = False

    def proofs(vid: str) -> list[tuple[frozenset[str], frozenset[str], bool]]:
        """All minimal proof trees rooted at ``vid``.

        Each entry is (versions, derivations, touches_low_integrity_source).
        On truncation the partial set built so far is returned rather than an
        empty list: dropping it would make a truncated run look like a run that
        found nothing, which is the "timeout disguised as safe" failure mode.
        """
        nonlocal visited, truncated
        if vid in cache:
            return cache[vid]
        visited += 1

        incoming = g.incoming(vid)
        if not incoming:
            # Source entity: the proof is the single version.
            res = [(frozenset({vid}), frozenset(), vid in low_sources)]
            cache[vid] = res
            return res

        results: list[tuple[frozenset[str], frozenset[str], bool]] = []
        for d in incoming:
            if truncated:
                break
            # AND semantics: every parent of the chosen record must be proved.
            combos: list[tuple[frozenset[str], frozenset[str], bool]] = [
                (frozenset({vid}), frozenset({d.did}), False)
            ]
            for p in d.parents:
                sub = proofs(p)
                if not sub:
                    combos = []
                    break
                merged: list[tuple[frozenset[str], frozenset[str], bool]] = []
                for cv, cd, clow in combos:
                    for sv, sd, slow in sub:
                        merged.append((cv | sv, cd | sd, clow or slow))
                        if len(merged) >= cap:
                            truncated = True
                            break
                    if truncated:
                        break
                combos = merged
                if truncated:
                    break
            results.extend(combos)
            if len(results) >= cap:
                truncated = True
                break
        # Only memoise a complete result; a truncated one would poison later
        # lookups with a silently partial answer.
        if not truncated:
            cache[vid] = results
        return results

    cache: dict[str, list[tuple[frozenset[str], frozenset[str], bool]]] = {}

    for sink in g.sinks:
        for vs, ds, low in proofs(sink.version_id):
            if truncated:
                break
            if not low:
                continue  # authorised: no low-integrity origin
            w = Witness(root_qid=sink.qid, versions=vs, derivations=ds)
            k = w.key()
            if k in seen:
                continue
            seen.add(k)
            out.append(w)
            if len(out) >= cap:
                truncated = True
                break
        if truncated:
            break

    return EnumerationResult(
        witnesses=out, exhaustive=not truncated, visited_nodes=visited
    )


def break_set(g: Hypergraph, w: Witness) -> set[str]:
    """Interventions that disable a necessary element of ``w``.

    ``deny_action`` on the witness root counts, matching the v4 plan's
    action-only certificate scope. ``quarantine_agent`` counts when the agent owns
    any non-argument version in the proof: quarantining it removes that version
    from the graph, which breaks the proof.
    """
    out: set[str] = set()
    proof_agents = {
        g.versions[v].agent
        for v in w.versions
        if v in g.versions
        and g.versions[v].agent
        and g.versions[v].kind is not VersionKind.ARGUMENT
    }
    for i in g.interventions.values():
        if i.kind is InterventionKind.REVOKE_VERSION and i.target in w.versions:
            if g.versions[i.target].kind is not VersionKind.ARGUMENT:
                out.add(i.iid)
        elif i.kind is InterventionKind.DISABLE_EDGE and i.target in w.derivations:
            out.add(i.iid)
        elif i.kind is InterventionKind.DENY_ACTION and i.target == w.root_qid:
            out.add(i.iid)
        elif i.kind is InterventionKind.QUARANTINE_AGENT and i.target in proof_agents:
            out.add(i.iid)
    return out


# --------------------------------------------------------------------------
# Clean_E, reachability, taint classification
# --------------------------------------------------------------------------


def clean_e(g: Hypergraph, revoked: set[str]) -> dict[str, bool]:
    """Conservative causal cleanliness (v4 plan section 3.7).

    A version is clean iff it is not revoked, is not a low-integrity source, and
    *every* parent of *every* incoming influence record is clean. Under P1 this
    conjunction ranges over one record per visible input, which is exactly the
    structural collapse this experiment measures.
    """
    low = g.low_integrity_sources
    order = sorted(g.versions.values(), key=lambda v: v.topo_index)
    out: dict[str, bool] = {}
    for v in order:
        if v.vid in revoked:
            out[v.vid] = False
            continue
        incoming = g.incoming(v.vid)
        if not incoming:
            out[v.vid] = v.vid not in low
            continue
        ok = True
        for d in incoming:
            for p in d.parents:
                if not out.get(p, False):
                    ok = False
                    break
            if not ok:
                break
        out[v.vid] = ok
    return out


def sink_reachable(g: Hypergraph, *, removed_versions: set[str] | None = None,
                   removed_edges: set[str] | None = None) -> set[str]:
    """Versions that can influence at least one protected sink.

    Backward closure from the sink versions over derivation records, skipping
    removed versions/edges (the residual graph after applying ``X``).
    """
    rv = removed_versions or set()
    re = removed_edges or set()
    seen: set[str] = set()
    stack = [s.version_id for s in g.sinks if s.version_id not in rv]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for d in g.incoming(cur):
            if d.did in re:
                continue
            for p in d.parents:
                if p in rv or p in seen:
                    continue
                stack.append(p)
    return seen


@dataclass
class TaintCounts:
    clean: int = 0
    contaminated_reachable: int = 0
    contaminated_unreachable: int = 0
    members: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.clean + self.contaminated_reachable + self.contaminated_unreachable

    @property
    def clean_survival_rate(self) -> float:
        """Fraction of versions that pass Clean_E. This is the L1 metric."""
        return self.clean / self.total if self.total else 0.0

    @property
    def retention_rate(self) -> float:
        """Fraction of versions rescued by the asymmetric mechanism.

        These are contaminated (Clean_E = False) but cannot reach any protected
        sink, so retaining them introduces no unauthorised authority flow
        (v4 plan theorem 5).
        """
        return self.contaminated_unreachable / self.total if self.total else 0.0

    @property
    def asymmetric_available_rate(self) -> float:
        """clean + retained: what stays usable under the asymmetric design."""
        return (
            (self.clean + self.contaminated_unreachable) / self.total
            if self.total
            else 0.0
        )


def classify(g: Hypergraph, revoked: set[str] | None = None) -> TaintCounts:
    """Three-way taint classification (v4 plan section 3.7)."""
    rv = revoked or set()
    ce = clean_e(g, rv)
    reach = sink_reachable(g)
    counts = TaintCounts()
    members: dict[str, list[str]] = {
        "clean": [],
        "contaminated_reachable": [],
        "contaminated_unreachable": [],
    }
    for vid, v in g.versions.items():
        if v.kind is VersionKind.ARGUMENT:
            continue  # sink arguments are not retention candidates
        if ce.get(vid, False):
            counts.clean += 1
            members["clean"].append(vid)
        elif vid in reach:
            counts.contaminated_reachable += 1
            members["contaminated_reachable"].append(vid)
        else:
            counts.contaminated_unreachable += 1
            members["contaminated_unreachable"].append(vid)
    counts.members = members
    return counts


# --------------------------------------------------------------------------
# SC1 / SC2 cheap sufficient conditions for EXHAUSTIVE (v4 plan section 4.2)
# --------------------------------------------------------------------------


def _applied(g: Hypergraph, x: set[str]) -> tuple[set[str], set[str], set[str]]:
    """Split an intervention set into removed versions/edges/denied sinks.

    Quarantining an agent removes every version it owns, so it expands into the
    removed-version set rather than being a separate case downstream.
    """
    rv, re, denied = set(), set(), set()
    for iid in x:
        i = g.interventions[iid]
        if i.kind is InterventionKind.REVOKE_VERSION:
            rv.add(i.target)
        elif i.kind is InterventionKind.DISABLE_EDGE:
            re.add(i.target)
        elif i.kind is InterventionKind.DENY_ACTION:
            denied.add(i.target)
        elif i.kind is InterventionKind.QUARANTINE_AGENT:
            rv |= {
                v.vid
                for v in g.versions.values()
                if v.agent == i.target and v.kind is not VersionKind.ARGUMENT
            }
    return rv, re, denied


def removed_versions(g: Hypergraph, x: set[str]) -> set[str]:
    """Versions made unavailable by ``x`` (agent quarantine expanded)."""
    rv, _re, _denied = _applied(g, x)
    return rv


def sc1_layer_cut(g: Hypergraph, x: set[str]) -> bool:
    """SC1: no low-integrity source can still influence any live sink.

    Sound: any witness in the residual graph implies a live low-integrity source
    inside the sink's backward closure, so an empty intersection proves that no
    witness remains. Cost is two linear passes, no enumeration.
    """
    rv, re, denied = _applied(g, x)
    live_sinks = [s for s in g.sinks if s.qid not in denied and s.version_id not in rv]
    if not live_sinks:
        return True
    seen: set[str] = set()
    stack = [s.version_id for s in live_sinks]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for d in g.incoming(cur):
            if d.did in re:
                continue
            for p in d.parents:
                if p in rv or p in seen:
                    continue
                stack.append(p)
    return not (seen & (g.low_integrity_sources - rv))


def sc2_sink_domination(g: Hypergraph, x: set[str]) -> bool:
    """SC2: every sink is dominated by a cut in ``x`` (e.g. deny_action)."""
    rv, re, denied = _applied(g, x)
    for s in g.sinks:
        if s.qid in denied or s.version_id in rv:
            continue
        # Is every incoming record of the sink argument disabled?
        incoming = g.incoming(s.version_id)
        if incoming and all(d.did in re for d in incoming):
            continue
        return False
    return True


def completeness(g: Hypergraph, x: set[str]) -> str:
    """Return which cheap condition proves exhaustiveness, if any."""
    if sc1_layer_cut(g, x):
        return "SC1"
    if sc2_sink_domination(g, x):
        return "SC2"
    return "none"
