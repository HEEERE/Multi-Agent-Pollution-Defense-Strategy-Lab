"""Honeypot Router — gray-zone threat diversion logic.

When L2/L3 detector confidence falls in the gray zone (0.50–0.75),
instead of blocking or passing through, the event is silently redirected
to a honeypot agent for intelligence gathering.

The attacker believes they successfully penetrated the system, while the
honeypot records their full interaction chain and novel payloads.
"""

from app.detectors.base import DetectionResult
from app.schemas import ActionTaken, AgentEvent, EventStatus


def _get_gray_zone_low() -> float:
    from app.settings_manager import get_settings_manager
    return float(get_settings_manager().get_value_sync("detectors", "honeypot.gray_zone_low", 0.50))


def _get_gray_zone_high() -> float:
    from app.settings_manager import get_settings_manager
    return float(get_settings_manager().get_value_sync("detectors", "honeypot.gray_zone_high", 0.75))


def _get_default_honeypot_node() -> str:
    from app.settings_manager import get_settings_manager
    return str(get_settings_manager().get_value_sync("agents", "honeypot.default_node", "Honeypot_Agent"))


class HoneyPotRouter:
    """Decides when and how to route events to the honeypot."""

    @staticmethod
    def should_decoy(result: DetectionResult) -> bool:
        """Confidence falls in gray zone → route to honeypot for intel gathering."""
        low = _get_gray_zone_low()
        high = _get_gray_zone_high()
        if result.is_threat:
            return low <= result.confidence < high
        if result.confidence >= 0.45 and not result.is_threat:
            return False
        return False

    @staticmethod
    def redirect_event(
        event: AgentEvent,
        result: DetectionResult,
        honeypot_id: str | None = None,
    ) -> AgentEvent:
        if honeypot_id is None:
            honeypot_id = _get_default_honeypot_node()
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
