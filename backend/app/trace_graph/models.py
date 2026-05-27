from typing import Any

from pydantic import BaseModel, Field


class TraceNode(BaseModel):
    node_id: str
    node_type: str  # agent | tool | memory | rag_doc | user | monitor | gateway
    label: str = ""
    contamination_score: float = 0.0
    trust_level: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceEdge(BaseModel):
    edge_id: str
    trace_id: str
    source: str
    target: str
    event_id: str
    edge_kind: str  # message | tool_call | memory_write | memory_read | rag_retrieval | intervention
    timestamp: float
    risk_tags: list[str] = Field(default_factory=list)
    contamination_delta: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceGraph(BaseModel):
    trace_id: str
    nodes: list[TraceNode] = Field(default_factory=list)
    edges: list[TraceEdge] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
