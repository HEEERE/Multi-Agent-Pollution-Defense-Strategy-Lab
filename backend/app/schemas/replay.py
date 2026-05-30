from enum import StrEnum

from pydantic import BaseModel


class ReplayState(StrEnum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    STEPPING = "stepping"
    COMPLETED = "completed"


class ReplaySession(BaseModel):
    session_id: str
    trace_id: str
    state: ReplayState = ReplayState.IDLE
    current_index: int = 0
    total_events: int = 0
    speed_multiplier: float = 1.0
    current_timestamp: float | None = None
