"""Security monitor node -- backward-compatible wrapper around the detector pipeline.

For new code, prefer using detectors.factory.create_default_pipeline()
and attaching it directly to the MessageBus as a monitor hook.
"""

import re

from app.detectors.pipeline import DetectorPipeline
from app.detectors.factory import create_default_pipeline
from app.message_bus import MessageBus
from app.monitoring.base import BaseMonitorNode
from app.schemas import ActionTaken, AgentEvent, EventStatus, EventType


class SecurityMonitorNode(BaseMonitorNode):
    """Monitor that inspects events through a 3-level detection pipeline.

    Deprecated approach: this subclass embeds detection logic directly.
    New code should use DetectorPipeline attached as a monitor hook instead.
    """

    def __init__(self, node_id: str, bus: MessageBus, pipeline: DetectorPipeline | None = None) -> None:
        super().__init__(node_id, bus)
        if pipeline is not None:
            self._pipeline = pipeline
            self.bus._monitors.remove(self.inspect)
            self.bus.attach_monitor(self._pipeline.inspect)
        else:
            self._pipeline = None
            # Legacy direct inspection patterns (kept for backward compat)
            self._explicit_attack_patterns = [
                re.compile(pattern, re.IGNORECASE)
                for pattern in [
                    r"ignore\s+(all\s+)?previous\s+instructions",
                    r"bypass\s+(policy|security|guardrail)",
                    r"reveal\s+(system|developer)\s+prompt",
                    r"exfiltrate|steal|dump\s+secrets?",
                ]
            ]
            self._rag_poison_markers = {
                "priority override",
                "retrieval note",
                "trusted paragraph",
                "hidden appendix",
                "policy mirror",
            }
            self._intent_markers = {
                "simulate consent",
                "operator approved",
                "roleplay as compliance",
                "cognitive bypass",
            }

    async def inspect(self, event: AgentEvent) -> AgentEvent | None:
        if self._pipeline is not None:
            return await self._pipeline.inspect(event)
        return await self._legacy_inspect(event)

    async def _legacy_inspect(self, event: AgentEvent) -> AgentEvent | None:
        level_1 = self._level_1_heuristic_filter(event.payload_snippet)
        if level_1:
            blocked_event = event.model_copy(
                update={
                    "status": EventStatus.QUARANTINED,
                    "action_taken": ActionTaken.BLOCK,
                }
            )
            await self._emit_monitor_alert(blocked_event, "Level 1 regex block: explicit malicious instruction.")
            return blocked_event

        level_2 = self._level_2_rag_feature_match(event.payload_snippet)
        if level_2:
            suspicious_event = event.model_copy(
                update={
                    "status": EventStatus.INFECTED,
                    "action_taken": ActionTaken.ALERT,
                }
            )
            await self._emit_monitor_alert(suspicious_event, "Level 2 RAG feature match: contextual poisoning suspected.")
            return suspicious_event

        level_3 = await self._level_3_llm_intent_judgement(event.payload_snippet)
        if level_3:
            quarantined_event = event.model_copy(
                update={
                    "status": EventStatus.QUARANTINED,
                    "action_taken": ActionTaken.ALERT,
                }
            )
            await self._emit_monitor_alert(quarantined_event, "Level 3 LLM intent judgement: cognitive deception detected.")
            return quarantined_event

        return event

    def _level_1_heuristic_filter(self, payload: str) -> bool:
        return any(pattern.search(payload) for pattern in self._explicit_attack_patterns)

    def _level_2_rag_feature_match(self, payload: str) -> bool:
        paragraphs = self._dynamic_paragraph_level_chunks(payload)
        return any(self._paragraph_matches_poison_signature(chunk) for chunk in paragraphs)

    def _dynamic_paragraph_level_chunks(self, payload: str) -> list[str]:
        raw_paragraphs = [part.strip() for part in re.split(r"\n\s*\n|(?<=\.)\s{2,}", payload) if part.strip()]
        chunks: list[str] = []
        buffer = ""
        for paragraph in raw_paragraphs or [payload]:
            candidate = f"{buffer} {paragraph}".strip()
            if len(candidate) < 140:
                buffer = candidate
                continue
            if buffer:
                chunks.append(buffer)
            chunks.append(paragraph)
            buffer = ""
        if buffer:
            chunks.append(buffer)
        return chunks

    def _paragraph_matches_poison_signature(self, paragraph: str) -> bool:
        lowered = paragraph.lower()
        marker_hits = sum(1 for marker in self._rag_poison_markers if marker in lowered)
        return marker_hits >= 2

    async def _level_3_llm_intent_judgement(self, payload: str) -> bool:
        lowered = payload.lower()
        return any(marker in lowered for marker in self._intent_markers)

    async def _emit_monitor_alert(self, original_event: AgentEvent, reason: str) -> None:
        await self.bus.emit(
            AgentEvent(
                event_type=EventType.INTERVENTION,
                source_node=self.node_id,
                target_node=original_event.target_node,
                payload_snippet=reason,
                status=original_event.status,
                action_taken=original_event.action_taken,
            )
        )
