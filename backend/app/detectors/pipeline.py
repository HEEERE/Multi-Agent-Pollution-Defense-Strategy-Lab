from time import perf_counter

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
        policy_engine=None,
        defense_coordinator=None,
    ) -> None:
        self.detectors = detectors
        self.short_circuit = short_circuit
        self.log_all = log_all
        self.min_severity_for_llm = min_severity_for_llm
        self._bus = bus
        self._policy_engine = policy_engine
        self._defense_coordinator = defense_coordinator
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

            started = perf_counter()
            result = await det.detect(event, context)
            latency_ms = (perf_counter() - started) * 1000

            detection_log.append({
                "detector_id": det.detector_id,
                "level": det.level.value,
                "is_threat": result.is_threat,
                "confidence": result.confidence,
                "reason": result.reason,
                "action": result.suggested_action.value,
                "latency_ms": round(latency_ms, 3),
            })

            if result.metadata.get("unknown"):
                final_event = final_event.model_copy(update={
                    "status": EventStatus.QUARANTINED,
                    "action_taken": ActionTaken.QUARANTINE,
                    "severity": EventSeverity.CRITICAL,
                    "metadata": {**final_event.metadata, "detector_unknown": True, "detection_log": detection_log},
                })
                blocked = True
                await self._emit_intervention(final_event, "detector output unknown")
                continue

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
                            "latency_ms": round(latency_ms, 3),
                            "action": ActionTaken.DECOY.value,
                            "honeypot_routed": True,
                        })
                        await self._emit_intervention(final_event,
                            f"Gray-zone (conf={result.confidence:.2f}) → routed to honeypot")
                continue

            action = result.suggested_action

            if action in (ActionTaken.BLOCK, ActionTaken.QUARANTINE):
                new_status = EventStatus.QUARANTINED
                final_event = final_event.model_copy(update={
                    "status": new_status,
                    "action_taken": action,
                    "severity": EventSeverity.CRITICAL,
                    "trust_level": "untrusted",
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

        # Detector confidence is diagnostic only. Authorization is delegated to
        # the deterministic policy/gateway path; no statistical fusion may
        # synthesize an allow or a containment decision here.

        if self._policy_engine is not None:
            final_event.metadata.setdefault("target_node_type", self._infer_policy_node_type(event.target_node))
            final_event.metadata.setdefault("source_node_type", self._infer_policy_node_type(event.source_node))
            decision = self._policy_engine.evaluate(final_event)
            updates: dict = {
                "policy_decision": decision.action,
                "policy_id": decision.policy_id,
                "metadata": {
                    **final_event.metadata,
                    "policy": decision.model_dump(),
                },
            }
            if decision.action in {"block", "deny"}:
                updates["action_taken"] = ActionTaken.BLOCK
                updates["status"] = EventStatus.QUARANTINED
            elif decision.action == "isolate":
                updates["action_taken"] = ActionTaken.ISOLATE
                updates["status"] = EventStatus.ISOLATED
            elif decision.action == "quarantine":
                updates["action_taken"] = ActionTaken.QUARANTINE
                updates["status"] = EventStatus.QUARANTINED
            elif decision.action == "alert":
                updates["action_taken"] = ActionTaken.ALERT
            elif decision.action == "human_review":
                updates["action_taken"] = ActionTaken.QUARANTINE
                updates["status"] = EventStatus.QUARANTINED
                updates["metadata"]["human_review_required"] = True
            final_event = final_event.model_copy(update=updates)

        # ── Joint Defense Coordination ─────────────────────────
        if self._defense_coordinator is not None:
            if self._should_joint_defense(final_event, detection_log):
                joint_decision = await self._defense_coordinator.evaluate(final_event)
                final_event = self._defense_coordinator.apply_decision(
                    final_event, joint_decision
                )

        return final_event

    @staticmethod
    def _infer_policy_node_type(node_id: str) -> str:
        if "KnowledgeGraph" in node_id or "Memory" in node_id:
            return "memory"
        if "RAG" in node_id or node_id.startswith("Tool_"):
            return "tool"
        if "Agent" in node_id:
            return "agent"
        if "Auditor" in node_id:
            return "monitor"
        if "Gateway" in node_id:
            return "gateway"
        return "unknown"

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
            source_node="Auditor_Prime",
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

    @staticmethod
    def _should_joint_defense(
        event: AgentEvent,
        detection_log: list[dict],
    ) -> bool:
        if event.action_taken in {
            ActionTaken.ALERT,
            ActionTaken.QUARANTINE,
            ActionTaken.BLOCK,
            ActionTaken.ISOLATE,
            ActionTaken.DECOY,
            ActionTaken.CHALLENGE,
        }:
            return True
        if event.severity in {EventSeverity.WARNING, EventSeverity.CRITICAL}:
            return True
        if event.trust_level == "untrusted":
            return True
        if event.contamination_score >= 0.35:
            return True
        if event.risk_tags:
            return True
        for item in detection_log:
            if item.get("is_threat"):
                return True
            if float(item.get("confidence", 0.0)) >= 0.45:
                return True
        return False

    def _allowed_severities(self) -> list[str]:
        levels = ["info", "warning", "critical"]
        threshold = self.min_severity_for_llm.value
        try:
            idx = levels.index(threshold)
            return levels[idx:]
        except ValueError:
            return levels
