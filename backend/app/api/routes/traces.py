"""Trace endpoints — CRUD, graph, and contamination analysis."""

from fastapi import APIRouter, HTTPException

from app.schemas import AgentEvent
from app.services import trace_service

router = APIRouter(tags=["traces"])


@router.get("")
async def list_traces(limit: int = 50, offset: int = 0) -> list[dict]:
    return await trace_service.list_traces(limit=limit, offset=offset)


@router.get("/{trace_id}")
async def get_trace(trace_id: str) -> list[AgentEvent]:
    return await trace_service.get_trace(trace_id)


@router.get("/{trace_id}/summary")
async def get_trace_summary(trace_id: str) -> dict:
    return await trace_service.get_trace_summary(trace_id)


@router.delete("/{trace_id}")
async def delete_trace(trace_id: str) -> dict:
    return await trace_service.delete_trace(trace_id)


@router.get("/{trace_id}/graph")
async def get_trace_graph(trace_id: str) -> dict:
    return await trace_service.get_trace_graph(trace_id)


@router.get("/{trace_id}/contamination")
async def get_trace_contamination(trace_id: str) -> dict:
    return await trace_service.get_trace_contamination(trace_id)
