from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SettingsCategory(StrEnum):
    DETECTORS = "detectors"
    LLM = "llm"
    AGENTS = "agents"
    SYSTEM = "system"


class SettingsPayload(BaseModel):
    category: str
    values: dict[str, Any] = Field(default_factory=dict)


class SettingsResetRequest(BaseModel):
    category: str
