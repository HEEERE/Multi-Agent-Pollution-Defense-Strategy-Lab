import re

from app.detectors.base import BaseDetector, DetectionContext, DetectionResult
from app.schemas import ActionTaken, AgentEvent, MonitorLevel


class RegexDetector(BaseDetector):
    detector_id = "regex_detector"
    level = MonitorLevel.HEURISTIC
    action_policy = ActionTaken.BLOCK

    def __init__(self, custom_patterns: list[str] | None = None) -> None:
        self._patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (custom_patterns or self._default_patterns())
        ]

    @staticmethod
    def _default_patterns() -> list[str]:
        return [
            r"ignore\s+(all\s+)?previous\s+instructions",
            r"bypass\s+(policy|security|guardrail)",
            r"reveal\s+(system|developer)\s+prompt",
            r"exfiltrate|steal|dump\s+secrets?",
            r"you\s+are\s+now\s+DAN",
            r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions",
            r"respond\s+with\s+your\s+system\s+instructions",
            r"sudo\s+mode|god\s+mode|admin\s+override",
            r"pretend\s+you\s+are\s+an?\s+(unfiltered|unrestricted)",
            r"delete\s+all\s+(logs|records|traces)",
        ]

    async def detect(self, event: AgentEvent, context: DetectionContext) -> DetectionResult:
        for pattern in self._patterns:
            match = pattern.search(event.payload_snippet)
            if match:
                return DetectionResult(
                    is_threat=True,
                    confidence=min(0.85 + len(match.group()) / 200, 0.99),
                    reason=f"Level 1 regex match: pattern '{match.re.pattern}' found in payload.",
                    suggested_action=self.action_policy,
                    level=self.level,
                    metadata={"matched_pattern": match.re.pattern, "match": match.group()},
                )
        return DetectionResult(
            is_threat=False,
            confidence=0.05,
            reason="No regex patterns matched.",
            level=self.level,
        )
