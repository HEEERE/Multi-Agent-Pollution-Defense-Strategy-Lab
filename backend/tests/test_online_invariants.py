"""The v4 §11.2 starred invariants, asserted against the code that actually runs.

``test_raise.py`` already covers these, but every one of its 54 tests imports
``app.research.scale.*`` -- the offline prototype. That leaves the production
modules under ``app/state/`` and ``app/verification/`` with no invariant coverage
at all, which is not a theoretical gap: the propose/veto step was crediting edge
removal to sink reachability, under-approximating on the graph whose entire job is
to over-approximate, and 41 of 144 grid points were wrong. The offline suite could
not have caught it, because the offline code did not have the bug.

So these tests target the online modules directly, and they build state through
``ProvenanceLedger`` rather than a hand-made graph object, so the append-only
guarantee and the projection builders are exercised on the real path.

Invariants covered here, in v4's numbering:

* ★紧图单向性        tight graph proposes only; it can never widen retention
* ★单调否决          adding interventions never resurrects a vetoed version
* ★state 无就地写    artifact rows are immutable; state lives in transitions
* ★保留安全性        retained set is disjoint from conservative sink-reachable
* ★标签强制          every retained version carries an enforcement record
* mutant injection   a broken optimiser cannot self-certify
* retention abuse     a new path to a sink demotes a retained version

The offline versions stay where they are, as cross-validation.
"""

from __future__ import annotations

import pytest

from app.provenance import ProvenanceLedger
from app.provenance.conservative_builder import build_conservative
from app.provenance.models import (
    ActivityRecord,
    ArtifactKind,
    ArtifactState,
    ArtifactVersion,
    Derivation,
    StateTransition,
    SupportGroup,
    TaintClass,
)
from app.provenance.tight_builder import build_tight
from app.state import asymmetric_repair
from app.state.controller import StateController
from app.state.costs import apply_interventions, candidate_interventions
from app.state.greedy_solver import greedy_cover
from app.state.reachability import classify, clean_e, sink_reachable
from app.state.witness import enumerate_witnesses
from app.verification.certificate_checker import CertificateChecker
from app.verification.residual_checker import ResidualChecker

RUN = "r_inv"


def _artifact(vid: str, integrity: str, *, kind: ArtifactKind = ArtifactKind.MESSAGE,
              agent: str = "agent_a") -> ArtifactVersion:
    return ArtifactVersion(
        vid, vid, RUN, kind, f"h_{vid}", frozenset({agent}), integrity
    )


@pytest.fixture
def scenario():
    """A ledger where retention is genuinely available, not vacuous.

    Shape, and why each piece is there:

        poison (low)  --d1-->  reach   --d2-->  sink_arg   [protected sink]
        poison (low)  --d3-->  stash                       [no path to sink]
        clean (high)  --d4-->  useful  --d5-->  goal        [support group]

    ``reach`` is contaminated *and* sink-reachable, so it must be invalidated.
    ``stash`` is contaminated and sink-*un*reachable, so theorem 5 says it is
    retainable -- it is the version the asymmetric mechanism exists to rescue, and
    without it every retention assertion below would pass trivially on an empty
    set. The clean branch keeps task utility non-zero so cost regressions show up.

    ``visible_inputs`` gives the conservative builder one extra edge the tight
    builder does not have: the activity behind ``useful`` saw ``poison`` in its
    context window without declaring a dependency on it. That is the P0/P1
    divergence the two-graph design is about, so the two graphs are structurally
    different here rather than the same object under two names.
    """
    ledger = ProvenanceLedger()
    ledger.ensure_run(RUN)
    for vid, integrity in (
        ("poison", "low"), ("reach", "high"), ("stash", "high"),
        ("clean", "high"), ("useful", "high"),
    ):
        ledger.append_artifact(_artifact(vid, integrity))
    ledger.append_artifact(_artifact("sink_arg", "high", kind=ArtifactKind.ARGUMENT))
    ledger.append_artifact(_artifact("goal", "high"))

    ledger.append_activity(ActivityRecord(
        "act_useful", RUN, "agent_b", "compose", visible_input_ids=("clean", "poison")
    ))
    ledger.append_derivation(Derivation("d1", RUN, "reach", ("poison",), "act_1"))
    ledger.append_derivation(Derivation("d2", RUN, "sink_arg", ("reach",), "act_2"))
    ledger.append_derivation(Derivation("d3", RUN, "stash", ("poison",), "act_3"))
    ledger.append_derivation(Derivation("d4", RUN, "useful", ("clean",), "act_useful"))
    ledger.append_derivation(Derivation("d5", RUN, "goal", ("useful",), "act_5"))
    ledger.append_support_group(SupportGroup(
        "sg1", RUN, "goal", ("useful",), "verifier_1", True
    ))
    return ledger


@pytest.fixture
def graphs(scenario):
    conservative = build_conservative(
        scenario, RUN, visible_inputs={"useful": ("clean", "poison")}
    )
    tight = build_tight(scenario, RUN)
    return conservative, tight


SINKS = {"sink_arg"}

CHOKE_RUN = "r_choke"


@pytest.fixture
def choke_ledger():
    """A shape where the cheapest cover is a *disabled edge*, not a revoked version.

    This fixture exists for one reason: to make the edge-crediting soundness bug
    observable. The main ``scenario`` cannot see it, because there the cheapest
    cover is ``revoke_version:poison`` and version-only reachability coincides with
    the full residual reachability -- so ``propose``/``veto`` give the same answer
    either way and the bug hides.

    Shape: three low-integrity sources, each through its own hop, all funnelled
    into one summary node whose single edge ``d_choke`` carries every path to the
    sink argument.

        p1(low) -> h1 -\\
        p2(low) -> h2 --+-> merge --d_choke--> sink_arg
        p3(low) -> h3 -/        ^
        p1(low) -> stash2 ------/

    The intermediate nodes are ``SUMMARY`` rather than ``MESSAGE`` on purpose:
    ``MESSAGE`` is a source kind and costs 1.0 to revoke, which would beat the
    1.5 edge. At 2.0 the single choke edge is the cheapest cover, so greedy
    selects ``disable_edge:d_choke`` and the divergence between crediting edges
    and not crediting them becomes a set of 8 versions.
    """
    ledger = ProvenanceLedger()
    ledger.ensure_run(CHOKE_RUN)

    def add(vid: str, integrity: str, kind: ArtifactKind) -> None:
        ledger.append_artifact(ArtifactVersion(
            vid, vid, CHOKE_RUN, kind, f"h_{vid}", frozenset({"agent_a"}), integrity
        ))

    for vid in ("p1", "p2", "p3"):
        add(vid, "low", ArtifactKind.MESSAGE)
    for vid in ("h1", "h2", "h3", "merge", "stash2"):
        add(vid, "high", ArtifactKind.SUMMARY)
    add("sink_arg", "high", ArtifactKind.ARGUMENT)

    for i in (1, 2, 3):
        ledger.append_derivation(Derivation(f"e{i}", CHOKE_RUN, f"h{i}", (f"p{i}",), f"a{i}"))
        ledger.append_derivation(Derivation(f"em{i}", CHOKE_RUN, "merge", (f"h{i}",), "am"))
    ledger.append_derivation(Derivation("e_st", CHOKE_RUN, "stash2", ("p1",), "a_st"))
    ledger.append_derivation(Derivation("e_st2", CHOKE_RUN, "merge", ("stash2",), "am"))
    ledger.append_derivation(Derivation("d_choke", CHOKE_RUN, "sink_arg", ("merge",), "a_sink"))
    return ledger


def test_choke_fixture_really_selects_a_disabled_edge(choke_ledger) -> None:
    """Guard the fixture below: if greedy stops picking the edge, it proves nothing.

    Unit costs could be retuned, or the kind classification changed, and this
    fixture would silently revert to being a duplicate of ``scenario``. Asserted
    explicitly so that shows up as a failure here instead of as lost coverage.
    """
    conservative = build_conservative(choke_ledger, CHOKE_RUN)
    catalogue = candidate_interventions(conservative, SINKS)
    witnesses = enumerate_witnesses(conservative, SINKS, cap=20_000)
    solution = greedy_cover(conservative, catalogue, witnesses.witnesses)
    assert solution.selected == {"disable_edge:d_choke"}, sorted(solution.selected)

    applied = apply_interventions(conservative, catalogue, set(solution.selected))
    assert applied.removed_relations == frozenset({"d_choke"})
    assert not applied.removed_versions

    full = sink_reachable(conservative, SINKS, applied=applied)
    versions_only = sink_reachable(conservative, SINKS, applied=applied.versions_only())
    assert len(versions_only - full) == 8, (
        f"bug window is {sorted(versions_only - full)}; expected 8 versions"
    )


def test_disabled_edge_is_not_credited_to_the_retention_decision(choke_ledger) -> None:
    """★保留安全性 against the bug that actually happened.

    An edge disable is a policy control on one influence record. It does not make
    stored state unreachable -- the state is still there and every other path
    stands. Crediting it in ``propose``/``veto`` under-approximates reachability on
    the graph whose entire purpose is to over-approximate it, which is v4 axiom A
    read backwards.

    With the bug present, this fixture retains all 8 contaminated versions,
    including all three low-integrity sources, every one of them still able to
    reach the sink the moment the edge control is bypassed or reverted. Verified
    by reintroducing it: this assertion fails with
    ``retained sink-reachable ['h1','h2','h3','merge','p1','p2','p3','stash2']``.
    """
    conservative = build_conservative(choke_ledger, CHOKE_RUN)
    tight = build_tight(choke_ledger, CHOKE_RUN)
    plan = asymmetric_repair.solve(
        conservative, tight, sink_versions=SINKS, witness_cap=20_000
    )
    assert plan.status == "COVERED"

    catalogue = candidate_interventions(conservative, SINKS)
    applied = apply_interventions(conservative, catalogue, set(plan.selected))
    reachable = sink_reachable(conservative, SINKS, applied=applied.versions_only())
    assert not (plan.retain & reachable), (
        f"retained sink-reachable {sorted(plan.retain & reachable)}"
    )


def test_denied_action_is_not_credited_to_the_retention_decision(choke_ledger) -> None:
    """The same argument for ``deny_action``, which is the other half of the fix.

    Denying an action refuses the *argument* at the boundary; it does not remove
    the stored state feeding it. So a version must not count as unreachable merely
    because the sink that consumes it was denied. Driven directly rather than
    through ``solve``, because ``deny_action`` costs 8.0 and greedy will never
    choose it here.
    """
    conservative = build_conservative(choke_ledger, CHOKE_RUN)
    tight = build_tight(choke_ledger, CHOKE_RUN)
    catalogue = candidate_interventions(conservative, SINKS)
    deny = {"deny_action:sink_arg"}

    proposed = asymmetric_repair.propose(tight, catalogue, deny, SINKS)
    vetoed = asymmetric_repair.veto(conservative, catalogue, deny, SINKS, proposed)
    retained = proposed - vetoed
    reachable = sink_reachable(conservative, SINKS)
    assert not (retained & reachable), (
        f"denying the sink retained still-reachable state: {sorted(retained & reachable)}"
    )


def test_fixture_is_not_vacuous(graphs) -> None:
    """Guard every assertion below: all three taint classes must be populated.

    If the scenario degenerated so that nothing was retainable, the retention
    invariants would pass by vacuous truth and this file would be worthless.
    Asserted first and explicitly rather than trusted.
    """
    conservative, tight = graphs
    report = classify(conservative, SINKS)
    assert report.of(TaintClass.CLEAN), "no clean versions"
    assert report.of(TaintClass.CONTAMINATED_REACHABLE), "nothing reachable"
    assert report.of(TaintClass.CONTAMINATED_UNREACHABLE), "nothing retainable"
    assert "stash" in report.of(TaintClass.CONTAMINATED_UNREACHABLE)
    assert "reach" in report.of(TaintClass.CONTAMINATED_REACHABLE)

    # The two graphs must genuinely differ, or the asymmetry is untested.
    assert conservative.parents("useful") == {"clean", "poison"}
    assert tight.parents("useful") == {"clean"}


# ---------------------------------------------------------------------------
# ★紧图单向性 -- the tight graph proposes and nothing more
# ---------------------------------------------------------------------------


def test_tight_graph_can_never_widen_retention(graphs) -> None:
    """Retention is ``propose_tight AND NOT vetoed_conservative``, one-directional.

    Demonstrated at the mechanism level rather than by reading the source: a tight
    graph that proposes *everything* must still not retain anything the
    conservative graph can route to a sink. If the relationship were symmetric --
    or if the conservative check were skipped when the tight graph was confident --
    an attacker who controls the tight view would control what survives.
    """
    conservative, tight = graphs
    catalogue = candidate_interventions(conservative, SINKS)
    witnesses = enumerate_witnesses(conservative, SINKS, cap=20_000)
    selected = set(greedy_cover(conservative, catalogue, witnesses.witnesses).selected)

    proposed = asymmetric_repair.propose(tight, catalogue, selected, SINKS)
    vetoed = asymmetric_repair.veto(conservative, catalogue, selected, SINKS, proposed)
    retained = proposed - vetoed

    applied = apply_interventions(conservative, catalogue, selected)
    conservative_reachable = sink_reachable(
        conservative, SINKS, applied=applied.versions_only()
    )
    assert not (retained & conservative_reachable), (
        f"tight graph widened retention into conservative-reachable: "
        f"{sorted(retained & conservative_reachable)}"
    )


def test_maximally_permissive_tight_graph_is_still_contained(graphs) -> None:
    """The adversarial version: hand ``veto`` the entire version set as proposals.

    A tight-graph bug that proposed every version must be fully absorbed by the
    conservative veto. This is the strongest form of the one-directional claim --
    it does not depend on ``propose`` behaving at all.
    """
    conservative, _ = graphs
    catalogue = candidate_interventions(conservative, SINKS)
    everything = frozenset(conservative.versions)

    vetoed = asymmetric_repair.veto(conservative, catalogue, set(), SINKS, everything)
    survived = everything - vetoed
    reachable = sink_reachable(conservative, SINKS)
    assert not (survived & reachable), (
        f"veto let sink-reachable versions through: {sorted(survived & reachable)}"
    )
    assert "reach" in vetoed and "sink_arg" in vetoed


def test_role_swapped_tight_graph_still_cannot_retain_anything_unsafe(graphs) -> None:
    """End-to-end mutant (v4 §10.5): the conservative graph passed in the tight slot.

    The retained *set* is not comparable between the two runs, and asserting a
    subset in either direction would be wrong. ``propose`` only proposes
    contaminated versions, and contamination is graph-relative: under P1 the
    visible-input edge makes ``useful`` and ``goal`` contaminated, so they become
    retention candidates, while under P0 they are simply clean and never proposed
    at all. The swapped run therefore retains *more* -- three versions against one.

    What must hold is the safety property, not the size: whatever the tight slot
    claims, nothing retained may reach a protected sink under the conservative
    view, and the verdict must not move.
    """
    conservative, tight = graphs
    honest = asymmetric_repair.solve(
        conservative, tight, sink_versions=SINKS, witness_cap=20_000
    )
    swapped = asymmetric_repair.solve(
        conservative, conservative, sink_versions=SINKS, witness_cap=20_000
    )
    assert honest.status == swapped.status == "COVERED"
    assert honest.selected == swapped.selected, (
        "the plan is solved on the conservative graph; the tight slot must not move it"
    )

    catalogue = candidate_interventions(conservative, SINKS)
    for label, plan in (("honest", honest), ("swapped", swapped)):
        applied = apply_interventions(conservative, catalogue, set(plan.selected))
        reachable = sink_reachable(conservative, SINKS, applied=applied.versions_only())
        assert not (plan.retain & reachable), (
            f"{label}: retained sink-reachable {sorted(plan.retain & reachable)}"
        )


# ---------------------------------------------------------------------------
# ★单调否决 -- vetoes never reverse
# ---------------------------------------------------------------------------


def test_veto_is_monotone_under_added_interventions(graphs) -> None:
    """Adding interventions must never un-veto a version.

    Interventions only ever remove influence, so a version the conservative graph
    could route to a sink under a smaller intervention set must still be handled
    under a larger one -- either still vetoed, or removed outright. A veto that
    reversed as the plan grew would make retention depend on solver order, and the
    plan is built incrementally by exactly that kind of growth.
    """
    conservative, _ = graphs
    catalogue = candidate_interventions(conservative, SINKS)
    candidates = frozenset(conservative.versions)

    ordered = sorted(catalogue)
    smaller: set[str] = set()
    base_vetoed = asymmetric_repair.veto(
        conservative, catalogue, smaller, SINKS, candidates
    )
    for iid in ordered[:12]:
        smaller.add(iid)
        larger_vetoed = asymmetric_repair.veto(
            conservative, catalogue, smaller, SINKS, candidates
        )
        applied = apply_interventions(conservative, catalogue, smaller)
        escaped = base_vetoed - larger_vetoed - set(applied.removed_versions)
        assert not escaped, (
            f"adding {iid} un-vetoed {sorted(escaped)} without removing them"
        )


def test_more_interventions_never_shrink_the_safety_verdict(graphs) -> None:
    """A superset plan must not turn COVERED back into UNSAFE.

    The checker is independent of the solver, so this is a real property of the
    residual walk rather than a restatement of how the plan was built.
    """
    conservative, _ = graphs
    catalogue = candidate_interventions(conservative, SINKS)
    witnesses = enumerate_witnesses(conservative, SINKS, cap=20_000)
    selected = set(greedy_cover(conservative, catalogue, witnesses.witnesses).selected)
    checker = ResidualChecker()

    def verdict(chosen: set[str]) -> str:
        applied = apply_interventions(conservative, catalogue, chosen)
        return checker.check(
            conservative,
            sink_versions=SINKS,
            blocked_versions=set(applied.removed_versions) | set(applied.denied_sinks),
            blocked_relations=set(applied.removed_relations),
        ).status

    assert verdict(selected) == "COVERED"
    for extra in sorted(set(catalogue) - selected)[:12]:
        assert verdict(selected | {extra}) == "COVERED", (
            f"adding {extra} broke a covered plan"
        )


# ---------------------------------------------------------------------------
# ★state 无就地写 -- artifact rows are immutable
# ---------------------------------------------------------------------------


def test_state_transitions_never_rewrite_the_artifact_row(scenario) -> None:
    """State is a transition log, not a mutable column.

    Checked against the stored bytes rather than the API: the artifact row for a
    version must be byte-identical before and after a state change, and the
    ``artifact_versions`` table must carry no state column at all. Replay and every
    certificate hash depend on old versions staying exactly as they were.
    """
    conn = scenario._conn
    columns = {row[1] for row in conn.execute("PRAGMA table_info(artifact_versions)")}
    assert "state" not in columns, f"artifact_versions carries state: {sorted(columns)}"

    before = conn.execute(
        "SELECT * FROM artifact_versions WHERE version_id=?", ("stash",)
    ).fetchone()
    scenario.transition_state(StateTransition(
        "st_x", RUN, "stash", ArtifactState.ACTIVE, ArtifactState.RETAINED, 0, "test"
    ))
    after = conn.execute(
        "SELECT * FROM artifact_versions WHERE version_id=?", ("stash",)
    ).fetchone()
    assert tuple(before) == tuple(after), "artifact row mutated by a state transition"
    assert scenario.current_state("stash") is ArtifactState.RETAINED


def test_ledger_issues_no_update_against_append_only_tables(scenario) -> None:
    """No UPDATE may touch a record table -- only run counters and the metrics upsert.

    Enforced by intercepting every statement the connection executes, so it covers
    whatever the code path actually does rather than what the source appears to say.
    The two permitted targets are ``provenance_runs`` (monotonic seq counters, not
    provenance) and ``metrics`` (an aggregate counter upsert).
    """
    allowed = ("provenance_runs", "metrics")
    seen: list[str] = []

    def trace(sql: str) -> None:
        lowered = " ".join(sql.split()).lower()
        if lowered.startswith("update") or " do update" in lowered:
            seen.append(lowered)

    scenario._conn.set_trace_callback(trace)
    try:
        scenario.append_artifact(_artifact("later", "high"))
        scenario.append_derivation(Derivation("d9", RUN, "later", ("clean",), "act_9"))
        scenario.transition_state(StateTransition(
            "st_y", RUN, "later", ArtifactState.ACTIVE, ArtifactState.INVALIDATED, 0, "t"
        ))
        scenario.increment_metric(RUN, "probe", 1.0)
    finally:
        scenario._conn.set_trace_callback(None)

    offenders = [s for s in seen if not any(t in s for t in allowed)]
    assert not offenders, f"UPDATE against an append-only table: {offenders}"
    assert seen, "no UPDATE observed at all; the trace callback is not wired up"


def test_invalidated_version_is_never_reactivated(scenario) -> None:
    """A terminal state stays terminal.

    ``repair`` skips versions already in a terminal state, so re-running it must
    not walk anything back to ACTIVE. Recovery is a *new version*, never a
    resurrection of the old one.
    """
    controller = StateController(scenario, RUN)
    controller.apply_state("stash", ArtifactState.INVALIDATED, "test_setup")
    controller.repair(sink_versions=SINKS, revoked_versions=set())
    assert scenario.current_state("stash") is ArtifactState.INVALIDATED


# ---------------------------------------------------------------------------
# ★保留安全性 and ★标签强制
# ---------------------------------------------------------------------------


def test_retention_is_disjoint_from_conservative_reachability(graphs) -> None:
    """Theorem 5's precondition, on the plan the runtime would apply.

    Nothing retained may reach a protected sink under the conservative view. This
    is the invariant the ``versions_only`` fix exists to protect: crediting a
    disabled edge here would let a version be called unreachable because one path
    was cut, on the graph that is supposed to over-approximate.
    """
    conservative, tight = graphs
    plan = asymmetric_repair.solve(
        conservative, tight, sink_versions=SINKS, witness_cap=20_000
    )
    assert plan.status == "COVERED"
    assert plan.retain, "fixture should retain something; otherwise vacuous"

    catalogue = candidate_interventions(conservative, SINKS)
    applied = apply_interventions(conservative, catalogue, set(plan.selected))
    reachable = sink_reachable(conservative, SINKS, applied=applied.versions_only())
    assert not (plan.retain & reachable), (
        f"retained and sink-reachable: {sorted(plan.retain & reachable)}"
    )

    cleanliness = clean_e(conservative, set(applied.removed_versions))
    assert not any(cleanliness.get(v, False) for v in plan.retain), (
        "clean versions counted as retained; retention is for contaminated state"
    )


def test_retention_only_survives_a_covered_post_state(graphs) -> None:
    """Step 6: anything short of COVERED withdraws retention entirely.

    Forced by handing ``solve`` a checker that reports UNKNOWN. Retention must go
    to empty and ``rolled_back`` must say so -- a plan that kept contaminated state
    while admitting it could not verify the post-state would be theorem 5 applied
    outside its preconditions.
    """
    conservative, tight = graphs

    class UnknownChecker(ResidualChecker):
        def check(self, graph, **kwargs):
            result = super().check(graph, **kwargs)
            return type(result)("UNKNOWN", frozenset(), False, "BUDGET_EXHAUSTED")

    plan = asymmetric_repair.solve(
        conservative, tight, sink_versions=SINKS,
        checker=UnknownChecker(), witness_cap=20_000,
    )
    assert plan.status == "UNKNOWN"
    assert plan.retain == frozenset()
    assert plan.rolled_back, "retention was withdrawn but not recorded as rolled back"
    assert not plan.retention_certified


def test_every_retained_version_carries_a_label_enforcement_record(scenario) -> None:
    """★标签强制: retention without a label is not retention.

    A retained version is contaminated and survives only because it cannot reach a
    sink *right now*. The enforcement record is what keeps it out of effectful
    authority, and it is bound to the certificate that retained it so the reason is
    auditable after the fact.
    """
    controller = StateController(scenario, RUN)
    result = controller.certify_and_retain(
        sink_versions=SINKS,
        blocked_versions={"poison", "reach"},
        candidate_versions={"stash"},
    )
    assert result.retained, f"nothing retained; cert valid={result.certificate.valid}"
    for version_id in result.retained:
        assert scenario.has_label_enforcement(version_id), (
            f"retained {version_id} has no enforcement record"
        )
        assert scenario.current_state(version_id) is ArtifactState.RETAINED

    rows = scenario._conn.execute(
        "SELECT version_id, certificate_hash, blocked_effects FROM label_enforcements"
    ).fetchall()
    assert rows
    for _vid, cert_hash, blocked in rows:
        assert cert_hash, "enforcement record not bound to a certificate"
        assert "E2" in blocked and "E3" in blocked, (
            f"effectful classes not blocked: {blocked}"
        )


# ---------------------------------------------------------------------------
# Mutant injection -- a broken optimiser cannot self-certify
# ---------------------------------------------------------------------------


def test_dropping_one_intervention_is_caught(graphs) -> None:
    """Mutant: the optimiser leaks a witness constraint.

    Remove one intervention from an otherwise-covering plan. The checker runs its
    own residual walk, so it must find what the plan no longer breaks. If this ever
    passed, the checker would be reading the solver's conclusion instead of the
    graph.
    """
    conservative, _ = graphs
    catalogue = candidate_interventions(conservative, SINKS)
    witnesses = enumerate_witnesses(conservative, SINKS, cap=20_000)
    selected = set(greedy_cover(conservative, catalogue, witnesses.witnesses).selected)
    assert selected, "greedy returned nothing; mutant not meaningful"
    checker = ResidualChecker()

    for dropped in sorted(selected):
        mutant = selected - {dropped}
        applied = apply_interventions(conservative, catalogue, mutant)
        result = checker.check(
            conservative,
            sink_versions=SINKS,
            blocked_versions=set(applied.removed_versions) | set(applied.denied_sinks),
            blocked_relations=set(applied.removed_relations),
        )
        assert result.status == "UNSAFE", (
            f"checker accepted a plan missing {dropped}"
        )
        assert result.residual_versions


def test_empty_plan_is_reported_unsafe(graphs) -> None:
    """Mutant: a stale or uninitialised snapshot yields an empty intervention set.

    The empty set breaks nothing, so the verdict must be UNSAFE with a named
    residual. Reporting COVERED here is the worst possible failure -- a
    certificate over an unrepaired graph.
    """
    conservative, _ = graphs
    result = ResidualChecker().check(conservative, sink_versions=SINKS)
    assert result.status == "UNSAFE"
    assert "poison" in result.residual_versions
    assert result.exhaustive


def test_certificate_will_not_issue_on_the_tight_graph(scenario) -> None:
    """Mutant: the tight graph is passed where a safety certificate is issued.

    Refused outright rather than answered, because the tight graph
    under-approximates influence: a COVERED verdict computed on it would be
    meaningless in the direction that matters. v4 axiom A, enforced at the API.
    """
    checker = CertificateChecker(scenario)
    tight = build_tight(scenario, RUN)
    assert not tight.conservative
    with pytest.raises(ValueError, match="conservative"):
        checker.issue(tight, run_id=RUN, sink_versions=SINKS, blocked_versions=set())


def test_conservative_graph_never_has_fewer_witnesses_than_tight(graphs) -> None:
    """Why the role error above matters: P0 undercounts.

    The conservative graph is a super-graph of the tight one, so it can only have
    at least as many witnesses. Running the checker on P0 would therefore miss
    some, which is exactly how a role error turns into a false COVERED.
    """
    conservative, tight = graphs
    on_conservative = enumerate_witnesses(conservative, SINKS, cap=20_000)
    on_tight = enumerate_witnesses(tight, SINKS, cap=20_000)
    assert on_conservative.count >= on_tight.count, (
        f"conservative {on_conservative.count} < tight {on_tight.count}"
    )


def test_certificate_does_not_verify_after_the_snapshot_moves(scenario) -> None:
    """Mutant: a certificate is reused against a ledger that has since changed.

    The certificate is bound to a snapshot hash. Appending anything must break
    verification, whether or not the addition is dangerous -- the check is over
    identity, not a judgement about the new record.
    """
    checker = CertificateChecker(scenario)
    conservative = build_conservative(scenario, RUN)
    certificate = checker.issue(
        conservative, run_id=RUN, sink_versions=SINKS,
        blocked_versions={"poison", "reach"},
    )
    assert certificate.valid
    assert checker.verify(certificate, conservative)

    scenario.append_artifact(_artifact("newcomer", "high"))
    assert not checker.verify(certificate, build_conservative(scenario, RUN)), (
        "certificate still verified after the snapshot moved"
    )


# ---------------------------------------------------------------------------
# Retention abuse -- attack family 15
# ---------------------------------------------------------------------------


def test_new_path_to_a_sink_demotes_a_retained_version(scenario) -> None:
    """Attack family 15, on the real ledger rather than a deep-copied graph.

    The adversary parks a payload in a version that is contaminated but
    sink-unreachable, gets it retained, then appends a derivation that routes it to
    a protected sink. The offline test mutates a copied ``Hypergraph``; here the
    attack is an ordinary append, which is what an attacker actually has, and
    ``recheck_retained`` must demote at the next action boundary.
    """
    controller = StateController(scenario, RUN)
    result = controller.certify_and_retain(
        sink_versions=SINKS,
        blocked_versions={"poison", "reach"},
        candidate_versions={"stash"},
    )
    assert "stash" in result.retained
    assert scenario.current_state("stash") is ArtifactState.RETAINED

    before = build_conservative(scenario, RUN)
    assert "stash" not in sink_reachable(before, SINKS)

    scenario.append_derivation(Derivation(
        "d_attack", RUN, "sink_arg", ("stash",), "act_attack"
    ))
    after = build_conservative(scenario, RUN)
    assert "stash" in sink_reachable(after, SINKS), "attack path did not take effect"

    invalidated = controller.recheck_retained({"stash"}, SINKS)
    assert "stash" in invalidated
    assert scenario.current_state("stash") is ArtifactState.INVALIDATED


def test_retention_abuse_makes_the_post_state_unsafe(scenario) -> None:
    """The checker must condemn the attacked post-state on its own.

    Independent of the demotion above: even with the original plan's blocks still
    applied, the residual walk over the new graph has to find the payload. This is
    the property that makes the boundary re-check a safety net rather than the only
    line of defence.
    """
    checker = ResidualChecker()
    conservative = build_conservative(scenario, RUN)
    blocked = {"poison", "reach"}
    assert checker.check(
        conservative, sink_versions=SINKS, blocked_versions=blocked
    ).status == "COVERED"

    scenario.append_artifact(_artifact("payload", "low"))
    scenario.append_derivation(Derivation("d_p", RUN, "stash", ("payload",), "act_p"))
    scenario.append_derivation(Derivation(
        "d_attack", RUN, "sink_arg", ("stash",), "act_attack"
    ))

    attacked = checker.check(
        build_conservative(scenario, RUN), sink_versions=SINKS, blocked_versions=blocked
    )
    assert attacked.status == "UNSAFE"
    assert "payload" in attacked.residual_versions


def test_no_escape_on_the_unattacked_graph(graphs) -> None:
    """Baseline for the two tests above: the original scenario is genuinely safe.

    Without this, an UNSAFE result there would prove nothing -- it could just mean
    the fixture was never covered in the first place.
    """
    conservative, tight = graphs
    plan = asymmetric_repair.solve(
        conservative, tight, sink_versions=SINKS, witness_cap=20_000
    )
    assert plan.status == "COVERED"
    assert plan.exhaustive
    assert not plan.rolled_back
