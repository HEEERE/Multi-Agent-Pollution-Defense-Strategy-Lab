from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import MonitorLevel


class LevelStats(BaseModel):
    level: MonitorLevel
    total_tested: int = 0
    threats_detected: int = 0
    false_positives: int = 0
    true_negatives: int = 0
    recall: float = 0.0
    fpr: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0


class BenchmarkReport(BaseModel):
    report_id: str
    timestamp: float
    pipeline_config: dict[str, Any] = Field(default_factory=dict)
    total_payloads: int = 0
    ground_truth_threats: int = 0
    per_level: list[LevelStats] = Field(default_factory=list)
    overall_recall: float = 0.0
    overall_fpr: float = 0.0
