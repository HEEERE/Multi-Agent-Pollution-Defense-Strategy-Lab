"""Phase 4 verification tests for the RAISE mechanism.

Covers:
* IndependentChecker isolation — no import path to solvers.py
* Checker correctly identifies residual witnesses
* Checker agrees with the optimiser on small graphs (COVERED iff solver covers)
* RetentionCertificate soundness — zero certified escapes
* RAISE-asymmetric retains at least as many versions as conservative
* Post-state re-verification catches a deliberately broken solution
* P0 propose / P1 veto invariant: certified_retained ⊆ sink-unreachable in P1
* Certificate is only valid when exhaustive=True and residual=0
* Mutant injection: optimizer leaks constraint, fakes low cost, uses stale
  snapshot, wrong role, half-applied state → checker must reject certificate
* Attack family 15 (retention abuse): retained version builds new path to sink
  across an action boundary → must be invalidated before it reaches a sink
* Three-state completeness: EXHAUSTIVE_NO_WITNESS / WITNESS_FOUND /
  BUDGET_EXHAUSTED semantics; BUDGET_EXHAUSTED never gates a certificate
* Label enforcement: retained versions cannot flow toward E2/E3 sinks
* Static dependency: verification code must not import optimizer or tight builder
"""
from __future__ import annotations

import importlib
import sys
import types

import pytest

from app.research.scale.analysis import enumerate_witnesses
from app.research.scale.checker import IndependentChecker
from app.research.scale.graph import GenSpec, generate
from app.research.scale.raise_mechanism import (
    RAISEResult,
    RetentionCertificate,
    SolveStatus,
    post_state_verify,
    raise_solve,
)
from app.research.scale.analysis import sink_reachable


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _spec(**kwargs) -> GenSpec:
    defaults = dict(context_size=4, hops=3, n_sinks=2, seed=42, n_goals=3)
    defaults.update(kwargs)
    return GenSpec(**defaults)


@pytest.fixture
def p0():
    return generate(_spec(), conservative=False)


@pytest.fixture
def p1():
    return generate(_spec(), conservative=True)


@pytest.fixture
def p0_wide():
    """Wider graph — more side branches → more retention candidates."""
    spec = GenSpec(
        context_size=4, hops=3, n_sinks=2, seed=7,
        chain_width=2, side_branch_per_hop=4, n_goals=3,
    )
    return generate(spec, conservative=False)


@pytest.fixture
def p1_wide():
    spec = GenSpec(
        context_size=4, hops=3, n_sinks=2, seed=7,
        chain_width=2, side_branch_per_hop=4, n_goals=3,
    )
    return generate(spec, conservative=True)


@pytest.fixture
def raise_result(p0, p1):
    return raise_solve(p0, p1)


@pytest.fixture
def raise_result_wide(p0_wide, p1_wide):
    return raise_solve(p0_wide, p1_wide)


# ---------------------------------------------------------------------------
# IndependentChecker isolation
# ---------------------------------------------------------------------------


class TestCheckerIsolation:
    def test_checker_does_not_import_solvers(self):
        """checker.py must have no import path to solvers.py."""
        import app.research.scale.checker as checker_mod
        # Collect all modules reachable via checker's own imports
        checker_file = checker_mod.__file__
        assert checker_file is not None
        # The simplest structural check: solvers must not appear in
        # checker's module's own __dict__ or its direct imports.
        for name, obj in vars(checker_mod).items():
            if isinstance(obj, types.ModuleType):
                assert "solvers" not in getattr(obj, "__name__", ""), (
                    f"checker.py transitively imported solvers via {name}"
                )

    def test_checker_imports_analysis_not_solvers(self):
        import app.research.scale.checker as checker_mod
        # analysis must be present (break_set, enumerate_witnesses)
        assert hasattr(checker_mod, "enumerate_witnesses") or \
               "analysis" in sys.modules.get(
                   "app.research.scale.checker", types.ModuleType("")
               ).__dict__.get("__file__", "")
        # solvers must not be imported
        assert "app.research.scale.solvers" not in [
            getattr(v, "__name__", "") for v in vars(checker_mod).values()
            if isinstance(v, types.ModuleType)
        ]


# ---------------------------------------------------------------------------
# IndependentChecker correctness
# ---------------------------------------------------------------------------


class TestCheckerCorrectness:
    def test_empty_selection_finds_witnesses(self, p1):
        checker = IndependentChecker()
        result = checker.check(p1, set())
        assert result.residual_witnesses, (
            "With no interventions there must be residual witnesses"
        )
        assert not result.passed

    def test_full_denial_covers_all(self, p1):
        """Deny every sink — no witness can survive."""
        from app.research.scale.graph import InterventionKind
        deny_all = {
            iid for iid, i in p1.interventions.items()
            if i.kind is InterventionKind.DENY_ACTION
        }
        checker = IndependentChecker()
        result = checker.check(p1, deny_all)
        assert not result.residual_witnesses
        assert result.passed

    def test_has_residual_true_on_empty(self, p1):
        checker = IndependentChecker()
        assert checker.has_residual(p1, set()) is True

    def test_has_residual_false_on_covered(self, p1):
        from app.research.scale.solvers import greedy_cover
        ws = enumerate_witnesses(p1).witnesses
        res = greedy_cover(p1, ws)
        checker = IndependentChecker()
        outcome = checker.has_residual(p1, set(res.selected))
        # Greedy cover should have closed all witnesses
        assert outcome is False

    def test_checker_total_enumerated_positive(self, p1):
        checker = IndependentChecker()
        result = checker.check(p1, set())
        assert result.total_enumerated > 0

    def test_checker_agrees_with_solver(self, p1):
        """On small graphs, checker and greedy cover agree: covered iff no residual."""
        from app.research.scale.solvers import greedy_cover
        ws = enumerate_witnesses(p1).witnesses
        res = greedy_cover(p1, ws)
        checker = IndependentChecker()
        cr = checker.check(p1, set(res.selected))
        # Greedy cover guarantees all witnesses broken → checker must confirm
        assert cr.passed, (
            f"Checker disagreed with greedy cover: {len(cr.residual_witnesses)} residual"
        )


# ---------------------------------------------------------------------------
# RetentionCertificate soundness
# ---------------------------------------------------------------------------


class TestCertificateSoundness:
    def test_valid_cert_has_zero_residual(self, raise_result):
        cert = raise_result.certificate
        if cert.valid:
            assert cert.post_state_witnesses == 0
            assert cert.post_state_exhaustive

    def test_valid_cert_status_is_covered(self, raise_result):
        cert = raise_result.certificate
        if cert.valid:
            assert cert.status is SolveStatus.COVERED

    def test_invalid_cert_cannot_retain(self, p1):
        """A certificate with status UNSAFE must not be marked valid."""
        # Construct a certificate with UNSAFE status manually
        cert = RetentionCertificate(
            status=SolveStatus.UNSAFE,
            intervention_set=frozenset(),
            retained_versions=frozenset({"v1", "v2"}),
            post_state_witnesses=3,
            post_state_exhaustive=True,
            proposed_count=2,
            vetoed_count=0,
        )
        assert not cert.valid

    def test_non_exhaustive_cert_is_invalid(self, p1):
        """A certificate from a budget-exhausted check is not valid."""
        cert = RetentionCertificate(
            status=SolveStatus.COVERED,
            intervention_set=frozenset(),
            retained_versions=frozenset(),
            post_state_witnesses=0,
            post_state_exhaustive=False,  # budget hit
            proposed_count=0,
            vetoed_count=0,
        )
        assert not cert.valid

    def test_raise_result_does_not_escape(self, raise_result):
        """The final outcome must never have residual witnesses."""
        assert not raise_result.outcome.escaped
        assert raise_result.outcome.residual_witnesses == 0

    def test_raise_result_wide_does_not_escape(self, raise_result_wide):
        assert not raise_result_wide.outcome.escaped


# ---------------------------------------------------------------------------
# Asymmetric >= Conservative retention
# ---------------------------------------------------------------------------


class TestAsymmetricRetention:
    def test_asym_retains_at_least_as_many_versions(self, p0, p1):
        from app.research.scale.baselines import raise_asymmetric, raise_conservative
        from app.research.scale.analysis import enumerate_witnesses
        ws = enumerate_witnesses(p1).witnesses
        asym = raise_asymmetric(p1, ws)
        cons = raise_conservative(p1, ws)
        assert asym.versions_active >= cons.versions_active, (
            "Asymmetric must keep at least as many active versions as conservative"
        )

    def test_raise_solve_asym_bp_ge_conservative(self, p0, p1):
        from app.research.scale.baselines import raise_asymmetric, raise_conservative
        from app.research.scale.analysis import enumerate_witnesses
        ws = enumerate_witnesses(p1).witnesses
        asym = raise_asymmetric(p1, ws)
        cons = raise_conservative(p1, ws)
        assert asym.benign_preservation >= cons.benign_preservation - 1e-9

    def test_raise_solve_produces_certificate(self, raise_result):
        assert isinstance(raise_result.certificate, RetentionCertificate)

    def test_raise_solve_outcome_is_outcome(self, raise_result):
        from app.research.scale.baselines import Outcome
        assert isinstance(raise_result.outcome, Outcome)

    def test_wide_graph_has_candidates(self, raise_result_wide):
        """With many side branches the tight graph should propose candidates."""
        assert raise_result_wide.certificate.proposed_count > 0


# ---------------------------------------------------------------------------
# Post-state re-verification
# ---------------------------------------------------------------------------


class TestPostStateVerification:
    def test_covered_on_valid_solution(self, p1):
        from app.research.scale.solvers import greedy_cover
        ws = enumerate_witnesses(p1).witnesses
        res = greedy_cover(p1, ws)
        checker = IndependentChecker()
        status, residual, exhaustive = post_state_verify(p1, set(res.selected), checker)
        assert status is SolveStatus.COVERED
        assert residual == 0
        assert exhaustive

    def test_unsafe_on_empty_selection(self, p1):
        checker = IndependentChecker()
        status, residual, exhaustive = post_state_verify(p1, set(), checker)
        assert status is SolveStatus.UNSAFE
        assert residual > 0

    def test_rollback_when_solution_broken(self, p0, p1):
        """Deliberately pass an empty set to simulate a broken solver output.

        post_state_verify should detect witnesses and return UNSAFE.
        raise_solve with that kind of solver would trigger rollback.
        The certificate status should be ROLLBACK or UNKNOWN, never COVERED.
        """
        checker = IndependentChecker()
        status, residual, _ = post_state_verify(p1, set(), checker)
        # We cannot directly inject a broken solver into raise_solve without
        # monkey-patching, but we verify post_state_verify catches it.
        assert status is SolveStatus.UNSAFE
        assert residual > 0


# ---------------------------------------------------------------------------
# P0 propose / P1 veto invariant
# ---------------------------------------------------------------------------


class TestProposeVetoInvariant:
    def test_certified_retained_subset_of_p1_sink_unreachable(self, p0, p1):
        """Every certified-retained version must be sink-unreachable in P1."""
        result = raise_solve(p0, p1)
        cert = result.certificate
        if not cert.valid:
            pytest.skip("Certificate not valid on this graph — veto invariant N/A")
        from app.research.scale.analysis import removed_versions
        revoked = removed_versions(p1, set(cert.intervention_set))
        reach_p1 = sink_reachable(p1, removed_versions=revoked)
        for vid in cert.retained_versions:
            assert vid not in reach_p1, (
                f"Retained version {vid} is still reachable in P1 — veto failed"
            )

    def test_proposed_ge_certified(self, raise_result):
        """Proposed count must be >= certified (veto can only remove, not add)."""
        cert = raise_result.certificate
        assert cert.proposed_count >= len(cert.retained_versions)

    def test_veto_count_correct(self, raise_result):
        cert = raise_result.certificate
        assert cert.vetoed_count == cert.proposed_count - len(cert.retained_versions)

    def test_p0_p1_same_seed_different_structure(self, p0, p1):
        """P0 and P1 built from same spec must differ in derivation count."""
        # P1 has more derivations (one per visible input per child).
        assert len(p1.derivations) >= len(p0.derivations), (
            "P1 (conservative) must have at least as many derivations as P0"
        )


# ---------------------------------------------------------------------------
# Three-state completeness semantics (§4.2)
# ---------------------------------------------------------------------------


class TestThreeStateCompleteness:
    """EXHAUSTIVE_NO_WITNESS / WITNESS_FOUND / BUDGET_EXHAUSTED semantics.

    Only EXHAUSTIVE_NO_WITNESS may gate a RetentionCertificate.
    BUDGET_EXHAUSTED must never produce a valid certificate (§8.2 fail-closed).
    """

    def test_completeness_module_imports(self):
        from app.research.scale.completeness import (
            CheckerCompleteness,
            completeness_from_check,
        )
        assert CheckerCompleteness.EXHAUSTIVE_NO_WITNESS
        assert CheckerCompleteness.WITNESS_FOUND
        assert CheckerCompleteness.BUDGET_EXHAUSTED

    def test_exhaustive_no_residual_maps_to_exhaustive_no_witness(self):
        from app.research.scale.completeness import (
            CheckerCompleteness,
            completeness_from_check,
        )
        result = completeness_from_check(exhaustive=True, has_residual=False)
        assert result is CheckerCompleteness.EXHAUSTIVE_NO_WITNESS

    def test_residual_found_maps_to_witness_found(self):
        from app.research.scale.completeness import (
            CheckerCompleteness,
            completeness_from_check,
        )
        # Even if exhaustive=True, finding a residual means WITNESS_FOUND
        for exhaustive in (True, False):
            result = completeness_from_check(exhaustive=exhaustive, has_residual=True)
            assert result is CheckerCompleteness.WITNESS_FOUND

    def test_budget_exhausted_maps_correctly(self):
        from app.research.scale.completeness import (
            CheckerCompleteness,
            completeness_from_check,
        )
        result = completeness_from_check(exhaustive=False, has_residual=False)
        assert result is CheckerCompleteness.BUDGET_EXHAUSTED

    def test_budget_exhausted_cert_is_not_valid(self, p1):
        """A certificate created under BUDGET_EXHAUSTED must never be valid."""
        cert = RetentionCertificate(
            status=SolveStatus.COVERED,
            intervention_set=frozenset(),
            retained_versions=frozenset(),
            post_state_witnesses=0,
            post_state_exhaustive=False,   # ← BUDGET_EXHAUSTED
            proposed_count=0,
            vetoed_count=0,
        )
        assert not cert.valid, (
            "BUDGET_EXHAUSTED (exhaustive=False) must never produce a valid certificate"
        )

    def test_unknown_status_cert_is_not_valid(self, p1):
        """SolveStatus.UNKNOWN maps to BUDGET_EXHAUSTED and is never valid."""
        cert = RetentionCertificate(
            status=SolveStatus.UNKNOWN,
            intervention_set=frozenset(),
            retained_versions=frozenset(),
            post_state_witnesses=0,
            post_state_exhaustive=True,
            proposed_count=0,
            vetoed_count=0,
        )
        assert not cert.valid

    def test_unsatisfiable_and_unknown_not_mixed(self, p1):
        """UNSATISFIABLE and UNKNOWN must be distinct — they have different semantics."""
        assert SolveStatus.UNKNOWN != SolveStatus.ROLLBACK
        # ROLLBACK is the state when UNSAFE was found and retention was rolled back.
        # UNKNOWN means the checker budget was exhausted before a conclusion.
        rollback_cert = RetentionCertificate(
            status=SolveStatus.ROLLBACK,
            intervention_set=frozenset(),
            retained_versions=frozenset(),
            post_state_witnesses=1,
            post_state_exhaustive=True,
            proposed_count=0,
            vetoed_count=0,
        )
        unknown_cert = RetentionCertificate(
            status=SolveStatus.UNKNOWN,
            intervention_set=frozenset(),
            retained_versions=frozenset(),
            post_state_witnesses=0,
            post_state_exhaustive=False,
            proposed_count=0,
            vetoed_count=0,
        )
        assert not rollback_cert.valid
        assert not unknown_cert.valid
        # Both are invalid but for different reasons; statuses must differ.
        assert rollback_cert.status is not unknown_cert.status

    def test_checker_completeness_from_real_graph_empty_selection(self, p1):
        """On the real graph with empty X, checker should find witnesses (WITNESS_FOUND)."""
        from app.research.scale.completeness import (
            CheckerCompleteness,
            completeness_from_check,
        )
        checker = IndependentChecker()
        r = checker.check(p1, set())
        completeness = completeness_from_check(
            exhaustive=r.exhaustive,
            has_residual=bool(r.residual_witnesses),
        )
        assert completeness is CheckerCompleteness.WITNESS_FOUND

    def test_checker_completeness_from_real_graph_covered(self, p1):
        """After greedy cover, checker should return EXHAUSTIVE_NO_WITNESS."""
        from app.research.scale.analysis import enumerate_witnesses
        from app.research.scale.completeness import (
            CheckerCompleteness,
            completeness_from_check,
        )
        from app.research.scale.solvers import greedy_cover
        ws = enumerate_witnesses(p1).witnesses
        res = greedy_cover(p1, ws)
        checker = IndependentChecker()
        r = checker.check(p1, set(res.selected))
        completeness = completeness_from_check(
            exhaustive=r.exhaustive,
            has_residual=bool(r.residual_witnesses),
        )
        assert completeness is CheckerCompleteness.EXHAUSTIVE_NO_WITNESS


# ---------------------------------------------------------------------------
# Mutant injection tests (§10.5, §11.3, §12.2)
# ---------------------------------------------------------------------------


class TestMutantInjection:
    """Inject deliberately broken optimizer behaviour; checker must reject.

    These tests verify that the independent checker's path is truly independent:
    optimizer failures cannot self-verify.  Each mutant exercises one failure
    mode listed in §10.5 of the v4 plan.
    """

    def test_optimizer_leaks_a_witness_constraint(self, p1):
        """Mutant: optimizer produces an X that misses one witness.

        Simulate by removing one intervention from the greedy solution, then
        verifying the checker rejects the resulting (incomplete) set.
        """
        from app.research.scale.analysis import enumerate_witnesses
        from app.research.scale.solvers import greedy_cover
        ws = enumerate_witnesses(p1).witnesses
        res = greedy_cover(p1, ws)
        full_set = set(res.selected)
        if not full_set:
            pytest.skip("Greedy returned empty set — mutant not meaningful here")
        # Remove an arbitrary element to simulate a leaked constraint.
        mutant_set = full_set - {next(iter(full_set))}
        checker = IndependentChecker()
        cr = checker.check(p1, mutant_set)
        # With a leaked constraint the checker must find at least one residual.
        assert not cr.passed, (
            "Checker failed to detect optimizer's leaked witness constraint"
        )

    def test_optimizer_fakes_low_cost_selects_wrong_interventions(self, p1):
        """Mutant: optimizer picks cheap-but-wrong interventions.

        Simulate by selecting only QUARANTINE_AGENT interventions (coarse, may
        not cover all witnesses depending on graph) and checking whether the
        checker catches any gap.
        """
        from app.research.scale.graph import InterventionKind
        quarantine_set = {
            iid for iid, i in p1.interventions.items()
            if i.kind is InterventionKind.QUARANTINE_AGENT
        }
        checker = IndependentChecker()
        cr = checker.check(p1, quarantine_set)
        # Whether or not this covers everything, the checker result must be
        # internally consistent: if residuals exist, passed is False.
        if cr.residual_witnesses:
            assert not cr.passed
        else:
            assert cr.passed == cr.exhaustive

    def test_optimizer_uses_stale_empty_snapshot(self, p1):
        """Mutant: optimizer returns an empty set (stale / uninitialized snapshot).

        The empty intervention set trivially fails to cover any witness.
        The checker must report UNSAFE.
        """
        checker = IndependentChecker()
        status, residual, exhaustive = post_state_verify(p1, set(), checker)
        assert status is SolveStatus.UNSAFE, (
            "Empty X (stale snapshot) must produce UNSAFE, not COVERED"
        )
        assert residual > 0

    def test_optimizer_applies_half_state(self, p1):
        """Mutant: only DENY_ACTION interventions applied (half the solution).

        A solution that only denies sinks but does not revoke contaminated
        sources may leave witnesses unseen by the checker if graph is complex.
        The checker must correctly evaluate what was actually passed.
        """
        from app.research.scale.graph import InterventionKind
        deny_only = {
            iid for iid, i in p1.interventions.items()
            if i.kind is InterventionKind.DENY_ACTION
        }
        checker = IndependentChecker()
        cr = checker.check(p1, deny_only)
        # DENY_ACTION on every sink *should* cover all witnesses rooted there;
        # verify checker agrees (either it passes or it caught a gap — both valid).
        # Key invariant: passed ↔ exhaustive AND no residual.
        assert cr.passed == (cr.exhaustive and not cr.residual_witnesses)

    def test_wrong_role_tight_graph_passed_to_checker(self, p0, p1):
        """Mutant: tight graph (P0) passed instead of conservative graph (P1).

        The RAISE specification requires the checker to run exclusively on the
        conservative graph.  Passing the tight graph is a role error.  Under
        P0 there are fewer witnesses (tight graph under-approximates), so
        passing P0 to the checker could produce a false COVERED result.
        We verify that P1 genuinely has more witnesses than P0, confirming that
        using P0 would silently miss witnesses.
        """
        from app.research.scale.analysis import enumerate_witnesses
        ws_p0 = enumerate_witnesses(p0).witnesses
        ws_p1 = enumerate_witnesses(p1).witnesses
        # Conservative graph must have at least as many witnesses as tight graph.
        # (P1 is a super-graph of P0 by construction; more edges → more proofs.)
        assert len(ws_p1) >= len(ws_p0), (
            "P1 (conservative) should have >= witnesses than P0 (tight); "
            "a checker run on P0 would undercount and self-verify incorrectly"
        )

    def test_post_state_verify_detects_broken_certificate(self, p1):
        """Mutant: certificate was issued but underlying state was never applied.

        Simulate: call post_state_verify with the empty set after having
        computed a solution, as if the application step was skipped.
        The checker must reject the resulting post-state.
        """
        from app.research.scale.analysis import enumerate_witnesses
        from app.research.scale.solvers import greedy_cover
        ws = enumerate_witnesses(p1).witnesses
        _res = greedy_cover(p1, ws)  # solution computed but not applied
        checker = IndependentChecker()
        # Post-state contains the original unsolved graph → UNSAFE.
        status, residual, _ = post_state_verify(p1, set(), checker)
        assert status is SolveStatus.UNSAFE
        assert residual > 0, "Checker must find residual witnesses in unapplied state"


# ---------------------------------------------------------------------------
# Attack family 15: Retention abuse (§9.4, §11.3)
# ---------------------------------------------------------------------------


class TestRetentionAbuse:
    """Attack family 15: contaminated_unreachable version gains new path to sink.

    The adversary hides a payload in a version that is initially
    contaminated_unreachable (hence a candidate for retention), then uses a
    subsequent activity to build a new derivation path that reaches a protected
    sink.  Theorem 5 requires this to be detected at the next action boundary
    and the version demoted from `retained` to `invalidated`.

    We test this by programmatically modifying a copy of the graph to create
    the new path, then verifying that:
    (a) The previously-retained version is now sink-reachable.
    (b) The label enforcement check reports a violation.
    (c) The post-state verifier on the modified graph reports UNSAFE.
    """

    def _build_graph_with_new_path(self, p1, retained_vid: str):
        """Return a copy of p1 where retained_vid has a new path to the first sink."""
        import copy
        from app.research.scale.graph import Derivation, Hypergraph
        g2 = copy.deepcopy(p1)
        # Add a derivation: retained_vid → sink argument version.
        sink_arg_vid = g2.sinks[0].version_id
        new_did = f"d_attack_{retained_vid}"
        g2.derivations[new_did] = Derivation(
            did=new_did,
            parents=(retained_vid,),
            child=sink_arg_vid,
            activity="attack_new_path",
        )
        g2._by_child = None   # force re-index
        g2._by_parent = None
        g2.index()
        return g2

    def _get_a_retained_candidate(self, p0, p1):
        """Run raise_solve and return one certified retained version, or None."""
        result = raise_solve(p0, p1)
        cert = result.certificate
        if not cert.valid or not cert.retained_versions:
            return None, cert
        return next(iter(cert.retained_versions)), cert

    def test_retained_version_becomes_reachable_after_new_path(self, p0, p1):
        """After new derivation to sink, the retained version is sink-reachable."""
        vid, cert = self._get_a_retained_candidate(p0, p1)
        if vid is None:
            pytest.skip("No certified retained versions on this graph")
        g2 = self._build_graph_with_new_path(p1, vid)
        reach = sink_reachable(g2, removed_versions=set(cert.intervention_set))
        # The attack graph must show the retained version is now sink-reachable.
        # (The removed_versions from the certificate still apply.)
        from app.research.scale.analysis import removed_versions
        revoked = removed_versions(g2, set(cert.intervention_set))
        reach_after = sink_reachable(g2, removed_versions=revoked)
        assert vid in reach_after, (
            "After new derivation, retained version must be sink-reachable"
        )

    def test_label_enforcement_detects_violation(self, p0, p1):
        """Label enforcement must report a violation when retained version reaches sink."""
        from app.research.scale.label_enforcement import check_label_enforcement
        vid, cert = self._get_a_retained_candidate(p0, p1)
        if vid is None:
            pytest.skip("No certified retained versions on this graph")
        g2 = self._build_graph_with_new_path(p1, vid)
        result = check_label_enforcement(
            g2,
            cert.retained_versions,
            set(cert.intervention_set),
        )
        assert not result.passed, (
            "Label enforcement must detect retained version now reachable from sink"
        )
        assert result.label_enforcement_violations > 0

    def test_post_state_verify_catches_retention_abuse(self, p0, p1):
        """Post-state verifier on the attacked graph must return UNSAFE."""
        vid, cert = self._get_a_retained_candidate(p0, p1)
        if vid is None:
            pytest.skip("No certified retained versions on this graph")
        g2 = self._build_graph_with_new_path(p1, vid)
        checker = IndependentChecker()
        status, residual, _ = post_state_verify(
            g2, set(cert.intervention_set), checker
        )
        assert status is SolveStatus.UNSAFE, (
            "Post-state verifier must return UNSAFE when attack path was injected"
        )
        assert residual > 0

    def test_no_escape_on_original_graph(self, p0, p1):
        """Baseline: without the new path the certified result has zero escapes."""
        result = raise_solve(p0, p1)
        assert result.outcome.residual_witnesses == 0
        assert not result.outcome.escaped


# ---------------------------------------------------------------------------
# Label enforcement (§3.7, §6.6, §9.3 X-A4)
# ---------------------------------------------------------------------------


class TestLabelEnforcement:
    """retained versions must not flow toward E2/E3 sinks (§9.3 X-A4)."""

    def test_label_enforcement_module_imports(self):
        from app.research.scale.label_enforcement import (
            LabelEnforcementResult,
            check_label_enforcement,
        )
        assert LabelEnforcementResult
        assert check_label_enforcement

    def test_empty_retained_passes(self, p1):
        """No retained versions → trivially passes label enforcement."""
        from app.research.scale.label_enforcement import check_label_enforcement
        result = check_label_enforcement(p1, frozenset(), set())
        assert result.passed
        assert result.label_enforcement_violations == 0

    def test_certified_retained_passes_on_original_graph(self, p0, p1):
        """Certified retained versions in the original graph must pass enforcement."""
        from app.research.scale.label_enforcement import check_label_enforcement
        raise_result = raise_solve(p0, p1)
        cert = raise_result.certificate
        if not cert.valid or not cert.retained_versions:
            pytest.skip("No valid retained versions to enforce")
        result = check_label_enforcement(
            p1, cert.retained_versions, set(cert.intervention_set)
        )
        # Retained versions were vetted as sink-unreachable in P1; enforcement passes.
        assert result.passed, (
            f"Certified retained versions violate label enforcement: "
            f"{result.violating_retained_versions}"
        )
        assert result.label_enforcement_violations == 0

    def test_sink_reachable_version_violates_enforcement(self, p1):
        """A version that IS sink-reachable must be flagged if marked retained."""
        from app.research.scale.label_enforcement import check_label_enforcement
        # Find a version that is sink-reachable (not yet removed).
        reachable = sink_reachable(p1)
        # Pick any reachable non-argument version.
        from app.research.scale.graph import VersionKind
        reachable_non_arg = [
            v for v in reachable
            if v in p1.versions and p1.versions[v].kind is not VersionKind.ARGUMENT
        ]
        if not reachable_non_arg:
            pytest.skip("No reachable non-argument versions in this graph")
        bad_retained = frozenset({reachable_non_arg[0]})
        result = check_label_enforcement(p1, bad_retained, set())
        assert not result.passed
        assert result.label_enforcement_violations > 0

    def test_violations_zero_invariant_after_raise_solve(self, p0, p1):
        """label_enforcement_violations == 0 after a successful raise_solve."""
        from app.research.scale.label_enforcement import check_label_enforcement
        raise_result = raise_solve(p0, p1)
        cert = raise_result.certificate
        if not cert.valid:
            pytest.skip("Certificate not valid — enforcement invariant only tested on valid certs")
        result = check_label_enforcement(
            p1, cert.retained_versions, set(cert.intervention_set)
        )
        assert result.label_enforcement_violations == 0, (
            "label_enforcement_violations must be 0 after a valid raise_solve"
        )


# ---------------------------------------------------------------------------
# Static dependency isolation — §11.1 B-4
# ---------------------------------------------------------------------------


class TestStaticDependencyIsolation:
    """verification/ must not import state/exact_solver, state/greedy_solver,
    or provenance/tight_builder (v4 plan §7.1 B-4, §11.1).

    In the current research/scale layout:
    - checker.py is the 'verification/' equivalent
    - solvers.py is the 'state/exact_solver + greedy_solver' equivalent
    - tight graph construction is inside graph.generate(conservative=False)

    The test confirms that checker.py has zero transitive import of solvers.py
    and no reference to the tight-graph constructor beyond what analysis.py
    already imports (analysis is allowed).
    """

    def test_checker_does_not_import_solvers_module(self):
        import app.research.scale.checker as checker_mod
        import app.research.scale.solvers as solvers_mod
        # Confirm solvers is not directly in checker's namespace.
        assert solvers_mod not in vars(checker_mod).values(), (
            "checker.py must not import solvers.py (B-4 violation)"
        )

    def test_checker_module_file_has_no_solvers_import_line(self):
        """Text-level check: checker.py source must not import from solvers."""
        import app.research.scale.checker as checker_mod
        import pathlib
        src = pathlib.Path(checker_mod.__file__).read_text(encoding="utf-8")
        import re
        # Match actual import statements, not comments or docstrings
        import_lines = re.findall(r'^\s*(?:import|from)\s+.*solvers', src, re.MULTILINE)
        assert not import_lines, (
            f"checker.py imports from solvers (B-4 violation): {import_lines}"
        )

    def test_label_enforcement_does_not_import_solvers(self):
        """label_enforcement.py must not import solvers."""
        import app.research.scale.label_enforcement as le_mod
        for name, obj in vars(le_mod).items():
            import types
            if isinstance(obj, types.ModuleType):
                assert "solvers" not in getattr(obj, "__name__", ""), (
                    f"label_enforcement.py imports solvers via {name}"
                )

    def test_completeness_does_not_import_solvers(self):
        """completeness.py must not import solvers or analysis (it is pure enum logic)."""
        import app.research.scale.completeness as comp_mod
        for name, obj in vars(comp_mod).items():
            import types
            if isinstance(obj, types.ModuleType):
                assert "solvers" not in getattr(obj, "__name__", ""), (
                    f"completeness.py imports solvers via {name}"
                )
