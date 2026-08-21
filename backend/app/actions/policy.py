from __future__ import annotations

from dataclasses import dataclass

from app.actions.models import ActionContract, ActionRequest, EffectClass, SecurityDecision
from app.provenance.ledger import ProvenanceLedger
from app.provenance.models import ArtifactState


@dataclass(frozen=True)
class PolicyDecision:
    decision: SecurityDecision
    reason_code: str
    authority_eligible: bool = True


class DeterministicPolicy:
    """The only component allowed to produce an allow decision."""

    def __init__(self, *, capabilities: dict[str, set[str]] | None = None,
                 scopes: dict[str, set[str]] | None = None,
                 contracts: dict[tuple[str, str], ActionContract] | None = None) -> None:
        self.capabilities = capabilities or {}
        self.scopes = scopes or {}
        self.contracts = contracts or {}

    def register_contract(self, contract: ActionContract) -> None:
        self.contracts[(contract.tool_id, contract.operation)] = contract

    def evaluate(self, request: ActionRequest, ledger: ProvenanceLedger) -> PolicyDecision:
        if request.deadline is not None:
            import time
            if time.time() > request.deadline:
                return PolicyDecision(SecurityDecision.DENY, "deadline_expired")
        contract = self.contracts.get((request.tool_id, request.operation))
        if contract is not None:
            if request.effect_class is not contract.effect_class:
                return PolicyDecision(SecurityDecision.DENY, "effect_contract_mismatch")
            if request.resource_scope not in contract.allowed_resource_scopes:
                return PolicyDecision(SecurityDecision.DENY, "contract_resource_out_of_scope")
            if not contract.required_capabilities.issubset(request.capability_requested):
                return PolicyDecision(SecurityDecision.DENY, "required_capability_missing")

        allowed_caps = self.capabilities.get(request.actor_agent_id, set())
        if not request.capability_requested.issubset(allowed_caps):
            return PolicyDecision(SecurityDecision.DENY, "capability_out_of_scope")
        allowed_scopes = self.scopes.get(request.actor_agent_id)
        if allowed_scopes is not None and request.resource_scope not in allowed_scopes:
            return PolicyDecision(SecurityDecision.DENY, "resource_out_of_scope")
        for argument in request.arguments:
            argument_contract = None
            if contract is not None:
                argument_contract = next((item for item in contract.arguments if item.name == argument.name), None)
                if argument_contract is None:
                    return PolicyDecision(SecurityDecision.DENY, "argument_not_in_contract")
                if argument.semantic_role != argument_contract.semantic_role:
                    return PolicyDecision(SecurityDecision.DENY, "argument_role_mismatch")
            if request.effect_class is EffectClass.E3 and argument.integrity != "high":
                return PolicyDecision(SecurityDecision.DENY, "low_integrity_e3_argument")
            if _effect_rank(request.effect_class) >= _effect_rank(EffectClass.E1) and not argument.artifact_refs:
                return PolicyDecision(SecurityDecision.QUARANTINE, "unknown_provenance")
            for ref in argument.artifact_refs:
                state = ledger.current_state(ref)
                if state in {ArtifactState.QUARANTINED, ArtifactState.INVALIDATED}:
                    return PolicyDecision(SecurityDecision.DENY, "artifact_unavailable")
                if state is None and _effect_rank(request.effect_class) >= _effect_rank(EffectClass.E1):
                    return PolicyDecision(SecurityDecision.QUARANTINE, "unknown_provenance")
                if _effect_rank(request.effect_class) >= _effect_rank(EffectClass.E1) and ledger.has_low_integrity_ancestor(ref):
                    return PolicyDecision(SecurityDecision.DENY, "contaminated_provenance")
                artifact = ledger.get_artifact(ref)
                if artifact is None:
                    continue
                if artifact.expiry is not None:
                    import time
                    if time.time() > artifact.expiry:
                        return PolicyDecision(SecurityDecision.DENY, "expired_provenance")
                if state is ArtifactState.RETAINED and request.effect_class in {EffectClass.E2, EffectClass.E3}:
                    return PolicyDecision(SecurityDecision.DENY, "retained_authority_forbidden")
                if argument_contract and argument_contract.allowed_origins:
                    if not artifact.origin_principals.issubset(argument_contract.allowed_origins):
                        return PolicyDecision(SecurityDecision.DENY, "origin_not_allowed")
                if argument_contract and argument_contract.required_integrity == "high" and artifact.integrity != "high":
                    return PolicyDecision(SecurityDecision.DENY, "integrity_contract_failed")
        if contract is not None:
            supplied = {argument.name for argument in request.arguments}
            if any(item.required and item.name not in supplied for item in contract.arguments):
                return PolicyDecision(SecurityDecision.DENY, "required_argument_missing")
        if request.effect_class in {EffectClass.E2, EffectClass.E3} and not request.reversible and request.effect_class is EffectClass.E2:
            return PolicyDecision(SecurityDecision.REQUIRE_APPROVAL, "irreversible_e2")
        if request.scope_level.value == "platform" and request.approval_id is None:
            return PolicyDecision(SecurityDecision.REQUIRE_APPROVAL, "platform_scope_requires_approval")
        if any(evidence.vetoes for evidence in request.model_evidence):
            return PolicyDecision(SecurityDecision.DENY, "model_evidence_veto")
        unknown_e0 = request.effect_class is EffectClass.E0 and any(
            ledger.current_state(ref) is None
            for argument in request.arguments for ref in argument.artifact_refs
        )
        return PolicyDecision(
            SecurityDecision.ALLOW,
            "deterministic_policy_pass",
            authority_eligible=not unknown_e0,
        )


def _effect_rank(effect: EffectClass) -> int:
    return {EffectClass.E0: 0, EffectClass.E1: 1, EffectClass.E2: 2, EffectClass.E3: 3}[effect]
