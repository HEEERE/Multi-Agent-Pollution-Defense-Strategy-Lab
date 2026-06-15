"""L2 Semantic Detector with adaptive threshold calibration.

Uses ChromaDB embedding similarity to detect semantic variants of known attacks.
Automatically tunes per-category thresholds based on observed precision/recall
in a sliding window.
"""

import asyncio
from collections import defaultdict, deque
from statistics import mean

from app.detectors.base import BaseDetector, DetectionContext, DetectionResult
from app.schemas import ActionTaken, MonitorLevel


class CategoryStats:
    """Per-injection-type sliding-window statistics for auto-tuning."""

    def __init__(self, window_size: int = 50) -> None:
        self.window: deque[tuple[float, float]] = deque(maxlen=window_size)
        self.threshold: float = 0.65
        self.min_matches: int = 1

    def record(self, similarity: float, is_threat: bool, flagged: bool) -> None:
        """Record a detection result for this category."""
        self.window.append((similarity, 1.0 if is_threat else 0.0, 1.0 if flagged else 0.0))

    def calibrate(self) -> None:
        """Adjust threshold and min_matches based on recent precision/recall."""
        if len(self.window) < 10:
            return
        fp = sum(1 for _, gt, flag in self.window if flag and not gt)
        fn = sum(1 for _, gt, flag in self.window if not flag and gt)
        total = len(self.window)

        fpr = fp / max(total - sum(1 for _, gt, _ in self.window if gt), 1)
        fnr = fn / max(sum(1 for _, gt, _ in self.window if gt), 1)

        if fpr > 0.30:
            self.threshold = min(0.90, self.threshold + 0.03)
            self.min_matches = min(3, self.min_matches + 1)
        elif fnr > 0.30:
            self.threshold = max(0.45, self.threshold - 0.03)
            self.min_matches = max(1, self.min_matches - 1)

        self.threshold = round(self.threshold, 3)


class SemanticDetector(BaseDetector):
    detector_id: str = "semantic_detector"
    level: MonitorLevel = MonitorLevel.FEATURE
    action_policy: ActionTaken = ActionTaken.QUARANTINE

    def __init__(
        self,
        threshold: float | None = None,
        top_k: int | None = None,
        min_matches: int | None = None,
        auto_calibrate: bool | None = None,
    ) -> None:
        from app.settings_manager import get_settings_manager
        mgr = get_settings_manager()
        self.threshold = threshold if threshold is not None else float(mgr.get_value_sync("detectors", "semantic.threshold", 0.65))
        self.top_k = top_k if top_k is not None else int(mgr.get_value_sync("detectors", "semantic.top_k", 5))
        self.min_matches = min_matches if min_matches is not None else int(mgr.get_value_sync("detectors", "semantic.min_matches", 1))
        self.auto_calibrate = auto_calibrate if auto_calibrate is not None else bool(mgr.get_value_sync("detectors", "semantic.auto_calibrate", True))
        self._category_stats: dict[str, CategoryStats] = defaultdict(CategoryStats)
        self._store = None

    def _get_store(self) -> "ChromaVectorStore":
        if self._store is None:
            from app.vector_store import get_vector_store
            self._store = get_vector_store()
        return self._store

    def _get_category_threshold(self, injection_type: str) -> float:
        if not self.auto_calibrate:
            return self.threshold
        stats = self._category_stats.get(injection_type)
        return stats.threshold if stats else self.threshold

    def _get_category_min_matches(self, injection_type: str) -> int:
        if not self.auto_calibrate:
            return self.min_matches
        stats = self._category_stats.get(injection_type)
        return stats.min_matches if stats else self.min_matches

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
            matches = await asyncio.to_thread(
                store.query_similar,
                payload,
                self.top_k,
            )
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
        pred_injection_type = top_match["metadata"].get("injection_type", "unknown")

        cat_threshold = self._get_category_threshold(pred_injection_type)
        min_m = self._get_category_min_matches(pred_injection_type)

        matches_above = [m for m in matches if m["similarity_score"] >= cat_threshold]
        enough_matches = len(matches_above) >= min_m

        if best_score >= cat_threshold and enough_matches:
            matched_samples = [
                {"text": m["text"][:200], "score": m["similarity_score"],
                 "type": m["metadata"].get("injection_type", "unknown")}
                for m in matches_above
            ]
            result = DetectionResult(
                is_threat=True,
                confidence=min(best_score, 0.95),
                reason=(
                    f"Semantic match to {pred_injection_type}: "
                    f"similarity {best_score:.2f} > threshold {cat_threshold}, "
                    f"{len(matches_above)} matches ≥ min_matches {min_m}"
                ),
                suggested_action=self.action_policy,
                level=self.level,
                metadata={
                    "matched_samples": matched_samples,
                    "similarity_scores": [m["similarity_score"] for m in matches],
                    "threshold": cat_threshold,
                    "min_matches": min_m,
                    "top_k": self.top_k,
                    "auto_calibrated": self.auto_calibrate,
                },
            )
            if self.auto_calibrate:
                self._category_stats[pred_injection_type].record(best_score, True, True)
            return result

        if self.auto_calibrate:
            self._category_stats[pred_injection_type].record(best_score, False, False)
            self._category_stats[pred_injection_type].calibrate()

        return DetectionResult(
            is_threat=False,
            confidence=round(best_score * 0.5, 3),
            reason=(
                f"Closest match ({pred_injection_type}) similarity {best_score:.2f} "
                f"below threshold {cat_threshold} or only {len(matches_above)} matches (need {min_m})"
            ),
            suggested_action=ActionTaken.NONE,
            level=self.level,
            metadata={
                "best_match_score": best_score,
                "threshold": cat_threshold,
                "min_matches": min_m,
                "matches_above": len(matches_above),
            },
        )

    def get_category_status(self) -> dict:
        """Return per-category threshold state for monitoring."""
        return {
            cat: {
                "threshold": s.threshold,
                "min_matches": s.min_matches,
                "window_size": len(s.window),
            }
            for cat, s in self._category_stats.items()
        }
