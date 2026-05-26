"""Honeypot Router — gray-zone threat diversion logic.

When L2/L3 detector confidence falls in the gray zone (0.50–0.75),
instead of blocking or passing through, the event is silently redirected
to a honeypot agent for intelligence gathering.

The attacker believes they successfully penetrated the system, while the
honeypot records their full interaction chain and novel payloads.
"""

from app.detectors.base import DetectionResult
from app.schemas import ActionTaken, AgentEvent, EventStatus


GRAY_ZONE_LOW = 0.50
GRAY_ZONE_HIGH = 0.75
DEFAULT_HONEYPOT_NODE = "Honeypot_Agent"


class HoneyPotRouter:
    """Decides when and how to route events to the honeypot."""

    @staticmethod
    def should_decoy(result: DetectionResult) -> bool:
        """Confidence falls in gray zone → route to honeypot for intel gathering."""
        if result.is_threat:
            return GRAY_ZONE_LOW <= result.confidence < GRAY_ZONE_HIGH
        # Also decoy if confidence is high enough to be suspicious but not flagged
        if result.confidence >= 0.45 and not result.is_threat:
            return False  # Don't decoy false positives — let them through
        return False

    @staticmethod
    def redirect_event(
        event: AgentEvent,
        result: DetectionResult,
        honeypot_id: str = DEFAULT_HONEYPOT_NODE,
    ) -> AgentEvent:
        """Rewrite the event to target the honeypot agent instead of the original target."""
        return event.model_copy(update={
            "target_node": honeypot_id,
            "status": EventStatus.HONEYPOTTED,
            "action_taken": ActionTaken.DECOY,
            "metadata": {
                **event.metadata,
                "honeypot": {
                    "original_target": event.target_node,
                    "confidence": result.confidence,
                    "reason": result.reason,
                    "detector_id": getattr(result, "metadata", {}).get("detector_id", "unknown"),
                },
            },
        })
