from app.detectors.base import BaseDetector, DetectionContext
from app.detectors.honeypot import HoneyPotRouter
from app.message_bus import MessageBus
from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventSeverity,
    EventStatus,
    EventType,
    MonitorLevel,
)


class DetectorPipeline:
    def __init__(
        self,
        detectors: list[BaseDetector],
        short_circuit: bool = True,
        log_all: bool = True,
        min_severity_for_llm: EventSeverity = EventSeverity.WARNING,
        bus: MessageBus | None = None,
        fusion_threshold: float | None = None,
    ) -> None:
        self.detectors = detectors
        self.short_circuit = short_circuit
        self.log_all = log_all
        self.min_severity_for_llm = min_severity_for_llm
        self._bus = bus
        if fusion_threshold is not None:
            self.fusion_threshold = fusion_threshold
        else:
            from app.settings_manager import get_settings_manager
            self.fusion_threshold = float(get_settings_manager().get_value_sync("detectors", "pipeline.fusion_threshold", 0.82))

    async def inspect(self, event: AgentEvent) -> AgentEvent | None:
        context = DetectionContext(event=event)
        detection_log: list[dict] = []
        final_event = event
        blocked = False

        for det in self.detectors:
            if blocked:
                if self.log_all:
                    detection_log.append({
                        "detector_id": det.detector_id,
                        "skipped": True,
                        "reason": "short_circuit",
                    })
                continue

            if det.level == MonitorLevel.LLM_INTENT:
                if event.severity.value not in self._allowed_severities():
                    detection_log.append({
                        "detector_id": det.detector_id,
                        "skipped": True,
                        "reason": f"severity {event.severity.value} below threshold {self.min_severity_for_llm.value}",
                    })
                    continue

            result = await det.detect(event, context)

            detection_log.append({
                "detector_id": det.detector_id,
                "level": det.level.value,
                "is_threat": result.is_threat,
                "confidence": result.confidence,
                "reason": result.reason,
                "action": result.suggested_action.value,
            })

            if not result.is_threat:
                # Check gray-zone: confidence in [0.50, 0.75) → honeypot
                if HoneyPotRouter.should_decoy(result):
                    final_event = HoneyPotRouter.redirect_event(final_event, result)
                    if final_event.metadata.get("honeypot"):
                        detection_log.append({
                            "detector_id": det.detector_id,
                            "level": det.level.value,
                            "is_threat": False,
                            "confidence": result.confidence,
                            "reason": result.reason,
                            "action": ActionTaken.DECOY.value,
                            "honeypot_routed": True,
                        })
                        await self._emit_intervention(final_event,
                            f"Gray-zone (conf={result.confidence:.2f}) → routed to honeypot")
                continue

            action = result.suggested_action

            if action in (ActionTaken.BLOCK, ActionTaken.QUARANTINE):
                new_status = EventStatus.QUARANTINED if action == ActionTaken.QUARANTINE else EventStatus.INFECTED
                final_event = final_event.model_copy(update={
                    "status": new_status,
                    "action_taken": action,
                    "severity": EventSeverity.CRITICAL,
                    "monitor_level": det.level,
                    "metadata": {
                        **final_event.metadata,
                        "detection": {
                            "detector_id": det.detector_id,
                            "level": det.level.value,
                            "confidence": result.confidence,
                            "reason": result.reason,
                        },
                        "detection_log": detection_log,
                    },
                })

                if action == ActionTaken.BLOCK:
                    blocked = True

                await self._emit_intervention(final_event, result.reason)

                if action == ActionTaken.ISOLATE:
                    return None

        if not blocked and detection_log:
            final_event = final_event.model_copy(update={
                "metadata": {**final_event.metadata, "detection_log": detection_log},
            })

        # ── Bayesian Confidence Fusion ──────────────────────────
        # If no single detector blocked, fuse L2+L3 confidences to catch
        # compound threats that individually don't meet thresholds.
        if not blocked and detection_log:
            active_results = [
                d for d in detection_log
                if not d.get("skipped") and d.get("confidence", 0) > 0
            ]
            confidences = [d["confidence"] for d in active_results]
            if len(confidences) >= 2:
                fused = self._fuse_confidences(confidences)
                if fused >= self.fusion_threshold:
                    final_event = final_event.model_copy(update={
                        "status": EventStatus.QUARANTINED,
                        "action_taken": ActionTaken.ALERT,
                        "severity": EventSeverity.WARNING,
                        "monitor_level": MonitorLevel.FEATURE,
                        "metadata": {
                            **final_event.metadata,
                            "detection": {
                                "detector_id": "bayesian_fusion",
                                "level": MonitorLevel.FEATURE.value,
                                "confidence": round(fused, 4),
                                "reason": f"Fused confidence {fused:.3f} ≥ {self.fusion_threshold} from {len(confidences)} detectors",
                            },
                            "fusion": {
                                "individual_confidences": confidences,
                                "fused_confidence": round(fused, 4),
                                "threshold": self.fusion_threshold,
                            },
                            "detection_log": detection_log,
                        },
                    })
                    await self._emit_intervention(final_event,
                        f"Bayesian fusion alert: compound confidence {fused:.3f}")

        return final_event

    @staticmethod
    def _fuse_confidences(confidences: list[float]) -> float:
        """Bayesian fusion: P(threat | all detectors) = 1 - ∏(1 - P_i)."""
        combined = 1.0
        for c in confidences:
            combined *= (1.0 - max(0.0, min(c, 0.99)))
        return round(1.0 - combined, 4)

    async def _emit_intervention(self, event: AgentEvent, reason: str) -> None:
        if self._bus is None:
            return
        intervention = AgentEvent(
            event_type=EventType.INTERVENTION,
            source_node="Monitor",
            target_node=event.source_node,
            payload_snippet=reason,
            status=event.status,
            action_taken=event.action_taken,
            severity=event.severity,
            monitor_level=event.monitor_level,
            metadata={
                "triggered_by": event.event_id,
                "detection": event.metadata.get("detection", {}),
            },
        )
        await self._bus.emit(intervention)

    def _allowed_severities(self) -> list[str]:
        levels = ["info", "warning", "critical"]
        threshold = self.min_severity_for_llm.value
        try:
            idx = levels.index(threshold)
            return levels[idx:]
        except ValueError:
            return levels
