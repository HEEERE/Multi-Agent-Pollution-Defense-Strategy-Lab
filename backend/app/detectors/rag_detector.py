import re

from app.detectors.base import BaseDetector, DetectionContext, DetectionResult
from app.schemas import ActionTaken, AgentEvent, MonitorLevel


class RAGFeatureDetector(BaseDetector):
    detector_id = "rag_feature_detector"
    level = MonitorLevel.FEATURE
    action_policy = ActionTaken.QUARANTINE

    def __init__(self, custom_markers: set[str] | None = None) -> None:
        self._markers = custom_markers or self._default_markers()

    @staticmethod
    def _default_markers() -> set[str]:
        return {
            "priority override",
            "retrieval note",
            "trusted paragraph",
            "hidden appendix",
            "policy mirror",
            "injected context",
            "system note",
            "backdoor reference",
            "covert instruction",
            "shadow prompt",
        }

    async def detect(self, event: AgentEvent, context: DetectionContext) -> DetectionResult:
        paragraphs = self._chunk(event.payload_snippet)
        for para in paragraphs:
            lowered = para.lower()
            hits = sum(1 for m in self._markers if m in lowered)
            if hits >= 2:
                return DetectionResult(
                    is_threat=True,
                    confidence=min(0.6 + hits * 0.1, 0.95),
                    reason=f"Level 2 RAG feature match: {hits} poison markers in paragraph.",
                    suggested_action=self.action_policy,
                    level=self.level,
                    metadata={"hits": hits, "paragraph": para[:200]},
                )
        return DetectionResult(
            is_threat=False,
            confidence=0.1,
            reason="No RAG poison markers matched.",
            level=self.level,
        )

    def _chunk(self, payload: str) -> list[str]:
        raw = [p.strip() for p in re.split(r"\n\s*\n|(?<=\.)\s{2,}", payload) if p.strip()]
        chunks: list[str] = []
        buf = ""
        for para in raw or [payload]:
            candidate = f"{buf} {para}".strip()
            if len(candidate) < 140:
                buf = candidate
                continue
            if buf:
                chunks.append(buf)
            chunks.append(para)
            buf = ""
        if buf:
            chunks.append(buf)
        return chunks
