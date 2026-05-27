from app.policy.default_policies import DEFAULT_POLICIES
from app.policy.models import PolicyCondition, PolicyDecision, PolicyRule

_ACTION_PRIORITY: dict[str, int] = {
    "allow": 0,
    "alert": 1,
    "quarantine": 2,
    "isolate": 3,
    "block": 4,
    "human_review": 5,
}


def _action_severity(action: str) -> int:
    return _ACTION_PRIORITY.get(action, 0)


class PolicyEngine:
    def __init__(self, policies: list[dict] | None = None) -> None:
        raw = policies if policies is not None else DEFAULT_POLICIES
        self.rules: list[PolicyRule] = [
            PolicyRule(**r) for r in raw if r.get("enabled", True)
        ]
        self.rules.sort(key=lambda r: r.priority)

    def evaluate(self, event) -> PolicyDecision:
        best: PolicyDecision | None = None

        for rule in self.rules:
            if self._matches(event, rule.condition):
                decision = PolicyDecision(
                    policy_id=rule.policy_id,
                    action=rule.action,
                    severity=rule.severity,
                    reason=rule.reason,
                    matched=True,
                )
                if best is None or _action_severity(decision.action) > _action_severity(best.action):
                    best = decision

        if best is not None:
            # Never downgrade a block from detectors
            current_action = getattr(event, "action_taken", None)
            if current_action is not None:
                current_val = str(current_action)
                if _action_severity(current_val) > _action_severity(best.action):
                    return PolicyDecision(
                        policy_id=best.policy_id,
                        action=current_val,
                        severity=best.severity,
                        reason=f"{best.reason} (detector action {current_val} preserved)",
                        matched=True,
                    )
            return best

        return PolicyDecision(action="allow", reason="No policy matched.")

    def _matches(self, event, cond: PolicyCondition) -> bool:
        if cond.event_type is not None:
            evt_type = getattr(event, "event_type", None)
            if evt_type is None or str(evt_type) != cond.event_type:
                return False

        if cond.source_trust_level is not None:
            trust = getattr(event, "trust_level", "unknown")
            if trust != cond.source_trust_level:
                return False

        if cond.target_node_type is not None:
            target = getattr(event, "target_node", "")
            meta = getattr(event, "metadata", {}) or {}
            target_type = meta.get("target_node_type", "")
            if target_type != cond.target_node_type and cond.target_node_type not in target:
                return False

        if cond.risk_tags_any:
            evt_tags = getattr(event, "risk_tags", []) or []
            if not any(t in evt_tags for t in cond.risk_tags_any):
                # Also check metadata.risk_tags for backwards compat
                meta = getattr(event, "metadata", {}) or {}
                meta_tags = meta.get("risk_tags", [])
                if not isinstance(meta_tags, list):
                    meta_tags = []
                if not any(t in meta_tags for t in cond.risk_tags_any):
                    return False

        if cond.min_contamination_score is not None:
            score = getattr(event, "contamination_score", 0.0) or 0.0
            if score < cond.min_contamination_score:
                return False

        if cond.metadata_match:
            meta = getattr(event, "metadata", {}) or {}
            for k, v in cond.metadata_match.items():
                if meta.get(k) != v:
                    return False

        return True
