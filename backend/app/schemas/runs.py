from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import new_id


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunRead(BaseModel):
    run_id: str = Field(default_factory=new_id)
    strategy_id: str | None = None
    strategy_version: int | None = None
    experiment_id: str | None = None
    trace_id: str | None = None
    status: RunStatus = RunStatus.QUEUED
    error: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
