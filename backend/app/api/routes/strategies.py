from fastapi import APIRouter

from app.schemas import (
    StrategyCreate,
    StrategyRead,
    StrategyUpdate,
    StrategyValidateRequest,
    StrategyValidationResult,
)
from app.services import strategy_service

router = APIRouter(tags=["strategies"])


@router.post("/validate", response_model=StrategyValidationResult)
async def validate_strategy(
    payload: StrategyValidateRequest,
) -> StrategyValidationResult:
    return await strategy_service.validate_strategy_content(payload.content)


@router.post("", response_model=StrategyRead, status_code=201)
async def create_strategy(data: StrategyCreate) -> StrategyRead:
    return await strategy_service.create_strategy(data)


@router.get("", response_model=list[StrategyRead])
async def list_strategies(
    limit: int = 50, offset: int = 0
) -> list[StrategyRead]:
    return await strategy_service.list_strategies(limit=limit, offset=offset)


@router.get("/{strategy_id}", response_model=StrategyRead)
async def get_strategy(strategy_id: str) -> StrategyRead:
    return await strategy_service.get_strategy(strategy_id)


@router.put("/{strategy_id}", response_model=StrategyRead)
async def update_strategy(
    strategy_id: str, data: StrategyUpdate
) -> StrategyRead:
    return await strategy_service.update_strategy(strategy_id, data)


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: str) -> dict:
    return await strategy_service.delete_strategy(strategy_id)


@router.post("/{strategy_id}/run")
async def run_strategy(strategy_id: str) -> dict:
    return await strategy_service.run_strategy(strategy_id)
