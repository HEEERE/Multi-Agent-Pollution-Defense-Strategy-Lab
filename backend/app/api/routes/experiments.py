"""Experiment endpoints — CRUD, metrics, and trace retrieval."""

from fastapi import APIRouter, HTTPException

from app.schemas import AgentEvent, ExperimentConfig, ExperimentRun
from app.services import experiment_service

router = APIRouter(tags=["experiments"])


@router.post("", response_model=ExperimentRun)
async def create_experiment(config: ExperimentConfig) -> ExperimentRun:
    return await experiment_service.create_experiment(config)


@router.get("")
async def list_experiments(limit: int = 50, offset: int = 0) -> list[dict]:
    return await experiment_service.list_experiments(limit=limit, offset=offset)


@router.get("/{experiment_id}")
async def get_experiment(experiment_id: str) -> dict:
    return await experiment_service.get_experiment(experiment_id)


@router.get("/{experiment_id}/trace")
async def get_experiment_trace(experiment_id: str) -> list[AgentEvent]:
    return await experiment_service.get_experiment_trace(experiment_id)


@router.get("/{experiment_id}/metrics")
async def get_experiment_metrics(experiment_id: str) -> dict:
    return await experiment_service.get_experiment_metrics(experiment_id)


@router.delete("/{experiment_id}")
async def delete_experiment(experiment_id: str) -> dict:
    return await experiment_service.delete_experiment(experiment_id)
