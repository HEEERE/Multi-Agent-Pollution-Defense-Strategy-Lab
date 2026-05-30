from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import (
    ActionPolicy,
    EventSeverity,
    MonitorLevel,
    new_id,
)


# ── Topology & injection configs ─────────────────────────────

class NodeConfig(BaseModel):
    node_id: str
    node_type: str  # gateway | agent | tool | monitor
    system_prompt: str = ""
    tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EdgeConfig(BaseModel):
    source: str
    target: str
    edge_type: str = "direct"  # direct | monitor


class InjectionType(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    RAG_POISONING = "rag_poisoning"
    TOOL_POLLUTION = "tool_pollution"
    COGNITIVE_DECEPTION = "cognitive_deception"


class InjectionConfig(BaseModel):
    injection_type: InjectionType
    source_node: str
    target_node: str
    payload: str
    turn: int = 0  # which turn to inject
    metadata: dict[str, Any] = Field(default_factory=dict)


class TopologyConfig(BaseModel):
    name: str = "default"
    nodes: list[NodeConfig] = Field(default_factory=list)
    edges: list[EdgeConfig] = Field(default_factory=list)
    monitors: list[str] = Field(default_factory=list)
    injections: list[InjectionConfig] = Field(default_factory=list)
    max_turns: int = 5
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Detector configs ─────────────────────────────────────────

class DetectorType(StrEnum):
    REGEX = "regex"
    RAG_FEATURE = "rag_feature"
    SEMANTIC = "semantic"
    LLM_INTENT = "llm_intent"


class DetectorConfig(BaseModel):
    detector_id: str
    detector_type: DetectorType
    enabled: bool = True
    action_policy: ActionPolicy = ActionPolicy.ALERT
    level: MonitorLevel = MonitorLevel.NONE
    params: dict[str, Any] = Field(default_factory=dict)


class DetectorPipelineConfig(BaseModel):
    detectors: list[DetectorConfig] = Field(default_factory=list)
    short_circuit: bool = True
    log_all_detections: bool = True
    min_severity_for_llm: EventSeverity = EventSeverity.WARNING


# ── Experiment configs ───────────────────────────────────────

class ExperimentConfig(BaseModel):
    name: str
    description: str = ""
    topology: TopologyConfig = Field(default_factory=TopologyConfig)
    detector_pipeline: DetectorPipelineConfig = Field(default_factory=DetectorPipelineConfig)
    num_runs: int = 1
    ground_truth: dict[str, bool] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ExperimentMetrics(BaseModel):
    propagation_depth: int = 0
    time_to_detection_ms: float = 0.0
    false_positive_rate: float = 0.0
    intervention_effectiveness: float = 0.0
    detection_latency_ms: float = 0.0
    contamination_spread_rate: float = 0.0
    total_events: int = 0
    threats_detected: int = 0
    threats_blocked: int = 0
    cascade_depth: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentRun(BaseModel):
    experiment_id: str = Field(default_factory=new_id)
    name: str
    config_json: str = ""
    status: ExperimentStatus = ExperimentStatus.PENDING
    trace_id: str | None = None
    metrics: ExperimentMetrics | None = None
    started_at: float | None = None
    completed_at: float | None = None
    error_message: str | None = None
