from typing import Any

from pydantic import BaseModel, Field


class StrategyValidateRequest(BaseModel):
    content: dict[str, Any]


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    format: str = "json"
    content: dict[str, Any]
    tags: list[str] = Field(default_factory=list)


class StrategyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: dict[str, Any] | None = None
    tags: list[str] | None = None


class StrategyRead(BaseModel):
    strategy_id: str
    name: str
    description: str
    format: str
    content: dict[str, Any]
    tags: list[str]
    version: int = 1
    created_at: float
    updated_at: float


class StrategyValidationIssue(BaseModel):
    path: str
    message: str
    level: str = "error"


class StrategyValidationResult(BaseModel):
    valid: bool
    issues: list[StrategyValidationIssue] = Field(default_factory=list)
