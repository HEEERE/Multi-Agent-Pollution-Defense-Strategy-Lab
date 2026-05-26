from app.detectors.base import BaseDetector, DetectionContext, DetectionResult
from app.schemas import ActionTaken, MonitorLevel


class SemanticDetector(BaseDetector):
    detector_id: str = "semantic_detector"
    level: MonitorLevel = MonitorLevel.FEATURE
    action_policy: ActionTaken = ActionTaken.QUARANTINE

    def __init__(
        self,
        threshold: float = 0.65,
        top_k: int = 5,
    ) -> None:
        self.threshold = threshold
        self.top_k = top_k
        self._store = None

    def _get_store(self) -> "ChromaVectorStore":
        if self._store is None:
            from app.vector_store import get_vector_store
            self._store = get_vector_store()
        return self._store

    async def detect(self, event: "AgentEvent", context: DetectionContext) -> DetectionResult:
        payload = event.payload_snippet
        if not payload or len(payload.strip()) < 10:
            return DetectionResult(
                is_threat=False,
                confidence=0.05,
                reason="Payload too short for semantic analysis",
                suggested_action=ActionTaken.NONE,
                level=self.level,
            )

        try:
            store = self._get_store()
            matches = store.query_similar(payload, top_k=self.top_k)
        except ImportError:
            return DetectionResult(
                is_threat=False,
                confidence=0.0,
                reason="chromadb not installed — semantic detection unavailable",
                suggested_action=ActionTaken.NONE,
                level=self.level,
            )

        if not matches:
            return DetectionResult(
                is_threat=False,
                confidence=0.1,
                reason="No similar attack patterns found in vector store",
                suggested_action=ActionTaken.NONE,
                level=self.level,
            )

        top_match = matches[0]
        best_score = top_match["similarity_score"]

        if best_score >= self.threshold:
            matched_samples = [
                {"text": m["text"][:200], "score": m["similarity_score"],
                 "type": m["metadata"].get("injection_type", "unknown")}
                for m in matches if m["similarity_score"] >= self.threshold
            ]
            return DetectionResult(
                is_threat=True,
                confidence=min(best_score, 0.95),
                reason=f"Semantic match to known attack pattern ({top_match['metadata'].get('injection_type', 'unknown')}): "
                       f"similarity {best_score:.2f} > threshold {self.threshold}",
                suggested_action=self.action_policy,
                level=self.level,
                metadata={
                    "matched_samples": matched_samples,
                    "similarity_scores": [m["similarity_score"] for m in matches],
                    "threshold": self.threshold,
                    "top_k": self.top_k,
                },
            )

        return DetectionResult(
            is_threat=False,
            confidence=round(best_score * 0.5, 3),
            reason=f"Closest match similarity {best_score:.2f} below threshold {self.threshold}",
            suggested_action=ActionTaken.NONE,
            level=self.level,
            metadata={
                "best_match_score": best_score,
                "threshold": self.threshold,
            },
        )
