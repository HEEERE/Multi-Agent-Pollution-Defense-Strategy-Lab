from fastapi import APIRouter

from app.schemas import RunRead
from app.services import run_service

router = APIRouter(tags=["runs"])


@router.get("/{run_id}", response_model=RunRead)
async def get_run(run_id: str) -> RunRead:
    return await run_service.get_run(run_id)


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: str, limit: int = 200, offset: int = 0
) -> list[dict]:
    return await run_service.get_run_events(run_id, limit=limit, offset=offset)


@router.get("/{run_id}/metrics")
async def get_run_metrics(run_id: str) -> dict:
    return await run_service.get_run_metrics(run_id)


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    return await run_service.cancel_run(run_id)
