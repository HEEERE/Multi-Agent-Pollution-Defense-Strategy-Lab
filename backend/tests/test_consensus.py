import pytest

from app.defense.consensus import aggregate_votes
from app.defense.schemas import DefenderVerdict


def _make_vote(
    defender_id: str = "test_guard",
    role: str = "test",
    verdict: str = "safe",
    confidence: float = 0.5,
    recommended_action: str = "allow",
    weight: float = 1.0,
    evidence: list[str] | None = None,
) -> DefenderVerdict:
    return DefenderVerdict(
        defender_id=defender_id,
        role=role,
        verdict=verdict,
        confidence=confidence,
        evidence=evidence or [],
        recommended_action=recommended_action,
        weight=weight,
    )


class TestConsensus:
    def test_veto_high_confidence_malicious_block(self):
        votes = [
            _make_vote("prompt_guard", verdict="safe", confidence=0.9),
            _make_vote(
                "policy_guard",
                verdict="malicious",
                confidence=0.95,
                recommended_action="block",
                weight=1.4,
            ),
            _make_vote("honeypot_guard", verdict="safe", confidence=0.5),
        ]
        action, conf, ctype = aggregate_votes(votes)
        assert action == "block"
        assert ctype == "veto"

    def test_veto_propagation_guard_isolates(self):
        votes = [
            _make_vote("prompt_guard", verdict="safe", confidence=0.9),
            _make_vote(
                "propagation_guard",
                verdict="malicious",
                confidence=0.93,
                recommended_action="isolate",
                weight=1.5,
            ),
        ]
        action, conf, ctype = aggregate_votes(votes)
        assert action == "isolate"
        assert ctype == "veto"

    def test_tool_policy_quorum_blocks_tool_call(self):
        votes = [
            _make_vote(
                "tool_guard",
                verdict="malicious",
                confidence=0.88,
                recommended_action="block",
                weight=1.3,
            ),
            _make_vote(
                "policy_guard",
                verdict="malicious",
                confidence=0.82,
                recommended_action="block",
                weight=1.4,
            ),
            _make_vote("prompt_guard", verdict="safe", confidence=0.9),
        ]
        action, conf, ctype = aggregate_votes(votes)
        assert action == "block"
        assert ctype == "quorum"

    def test_quorum_not_triggered_with_only_one(self):
        votes = [
            _make_vote(
                "tool_guard",
                verdict="malicious",
                confidence=0.9,
                recommended_action="block",
                weight=1.3,
            ),
            _make_vote(
                "policy_guard",
                verdict="suspicious",
                confidence=0.5,
            ),
        ]
        action, _, ctype = aggregate_votes(votes)
        assert ctype != "quorum"

    def test_weighted_malicious_score_isolates(self):
        votes = [
            _make_vote(
                "propagation_guard",
                verdict="malicious",
                confidence=0.85,
                weight=1.5,
            ),
            _make_vote(
                "tool_guard",
                verdict="malicious",
                confidence=0.7,
                weight=1.3,
            ),
            _make_vote("honeypot_guard", verdict="safe", confidence=0.5),
        ]
        action, conf, ctype = aggregate_votes(votes)
        # malicious_score = 0.85*1.5 + 0.7*1.3 = 1.275 + 0.91 = 2.185 >= 1.6 → isolate
        assert action == "isolate"
        assert ctype == "weighted"

    def test_weighted_malicious_score_quarantines(self):
        votes = [
            _make_vote(
                "memory_guard",
                verdict="malicious",
                confidence=0.7,
                weight=1.2,
            ),
            _make_vote(
                "prompt_guard",
                verdict="malicious",
                confidence=0.5,
                weight=1.2,
            ),
            _make_vote("honeypot_guard", verdict="safe", confidence=0.5),
        ]
        action, _, ctype = aggregate_votes(votes)
        # malicious_score = 0.7*1.2 + 0.5*1.2 = 0.84 + 0.6 = 1.44 >= 1.2 → quarantine
        assert action == "quarantine"
        assert ctype == "weighted"

    def test_suspicious_score_challenges(self):
        votes = [
            _make_vote(
                "rag_guard",
                verdict="suspicious",
                confidence=0.6,
                weight=1.1,
            ),
            _make_vote(
                "prompt_guard",
                verdict="suspicious",
                confidence=0.5,
                weight=1.2,
            ),
            _make_vote("honeypot_guard", verdict="safe", confidence=0.5),
        ]
        action, _, ctype = aggregate_votes(votes)
        # suspicious_score = 0.6*1.1 + 0.5*1.2 = 0.66 + 0.6 = 1.26 >= 0.8 → challenge
        assert action == "challenge"
        assert ctype == "weighted"

    def test_decoy_selected_for_gray_zone(self):
        votes = [
            _make_vote(
                "honeypot_guard",
                verdict="suspicious",
                confidence=0.6,
                recommended_action="decoy",
                weight=0.8,
            ),
            _make_vote("prompt_guard", verdict="safe", confidence=0.9),
            _make_vote("rag_guard", verdict="safe", confidence=0.85),
        ]
        action, _, ctype = aggregate_votes(votes)
        assert action == "decoy"
        assert ctype == "weighted"

    def test_decoy_not_selected_when_malicious_present(self):
        votes = [
            _make_vote(
                "honeypot_guard",
                verdict="suspicious",
                confidence=0.6,
                recommended_action="decoy",
                weight=0.8,
            ),
            _make_vote(
                "tool_guard",
                verdict="malicious",
                confidence=0.8,
                weight=1.3,
            ),
        ]
        action, _, ctype = aggregate_votes(votes)
        # malicious_score = 0.8*1.3 = 1.04 >= 1.0, so decoy shouldn't trigger
        assert action != "decoy"

    def test_fallback_allow(self):
        votes = [
            _make_vote("prompt_guard", verdict="safe", confidence=0.9),
            _make_vote("rag_guard", verdict="safe", confidence=0.85),
            _make_vote("honeypot_guard", verdict="safe", confidence=0.5),
        ]
        action, conf, ctype = aggregate_votes(votes)
        assert action == "allow"
        assert ctype == "fallback"
