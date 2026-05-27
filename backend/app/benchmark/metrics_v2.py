"""Benchmark v2 metrics for contamination and defense evaluation."""

from pydantic import BaseModel, Field


class BenchmarkV2Metrics(BaseModel):
    total_scenarios: int = 0
    total_events: int = 0
    attack_success_rate: float = 0.0
    detection_recall: float = 0.0
    false_positive_rate: float = 0.0
    avg_time_to_detection_ms: float = 0.0
    avg_propagation_depth: float = 0.0
    avg_blast_radius: float = 0.0
    avg_contamination_persistence: float = 0.0
    recovery_success_rate: float = 0.0
    defense_utility_loss: float = 0.0
    metadata: dict = Field(default_factory=dict)
