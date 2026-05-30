from typing import Any

from pydantic import BaseModel, Field


class TraceSummary(BaseModel):
    trace_id: str
    event_count: int
    start_time: float
    end_time: float
    status_counts: dict[str, int] = Field(default_factory=dict)
    severity_counts: dict[str, int] = Field(default_factory=dict)
    nodes_involved: list[str] = Field(default_factory=list)
