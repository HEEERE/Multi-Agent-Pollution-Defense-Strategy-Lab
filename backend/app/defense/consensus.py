from __future__ import annotations

from app.defense.schemas import DefenderVerdict

DEFENDER_WEIGHTS = {
    "prompt_guard": 1.2,
    "rag_guard": 1.1,
    "tool_guard": 1.3,
    "memory_guard": 1.2,
    "policy_guard": 1.4,
    "propagation_guard": 1.5,
    "honeypot_guard": 0.8,
}

VETO_ACTIONS = {"block", "isolate"}
VETO_DEFENDERS = {"policy_guard", "tool_guard", "propagation_guard"}


def aggregate_votes(votes: list[DefenderVerdict]) -> tuple[str, float, str]:
    # 1. Veto: single high-confidence malicious block/isolate
    for v in votes:
        if (
            v.verdict == "malicious"
            and v.confidence >= 0.92
            and v.recommended_action in VETO_ACTIONS
            and v.defender_id in VETO_DEFENDERS
        ):
            return v.recommended_action, v.confidence, "veto"

    by_id = {v.defender_id: v for v in votes}

    # 2. Quorum: ToolGuard + PolicyGuard both malicious → block
    tg = by_id.get("tool_guard")
    pg = by_id.get("policy_guard")
    if (
        tg is not None
        and pg is not None
        and tg.verdict == "malicious"
        and pg.verdict == "malicious"
    ):
        conf = min(1.0, (tg.confidence + pg.confidence) / 2)
        return "block", conf, "quorum"

    # 3. Weighted voting
    malicious_score = sum(
        v.confidence * v.weight for v in votes if v.verdict == "malicious"
    )
    suspicious_score = sum(
        v.confidence * v.weight for v in votes if v.verdict == "suspicious"
    )

    if malicious_score >= 1.6:
        return "isolate", min(1.0, malicious_score / 3.0), "weighted"
    if malicious_score >= 1.2:
        return "quarantine", min(1.0, malicious_score / 2.5), "weighted"
    if suspicious_score >= 0.8:
        return "challenge", min(1.0, suspicious_score / 2.0), "weighted"

    # 4. Gray-zone decoy
    decoy_votes = [v for v in votes if v.recommended_action == "decoy"]
    if decoy_votes and malicious_score < 1.0:
        conf = max(v.confidence for v in decoy_votes)
        return "decoy", conf, "weighted"

    return "allow", 0.5, "fallback"
