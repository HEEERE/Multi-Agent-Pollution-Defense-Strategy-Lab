"""Policy endpoints."""

from fastapi import APIRouter

from app.policy.default_policies import DEFAULT_POLICIES
from app.policy.engine import PolicyEngine
from app.schemas import AgentEvent

router = APIRouter(tags=["policies"])


@router.get("")
async def get_policies() -> list[dict]:
    return DEFAULT_POLICIES


@router.post("/evaluate")
async def evaluate_policy(event: AgentEvent) -> dict:
    engine = PolicyEngine()
    decision = engine.evaluate(event)
    return decision.model_dump(mode="json")
