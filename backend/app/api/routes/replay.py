"""Replay endpoints — session management and playback control."""

from fastapi import APIRouter, HTTPException

from app.services import replay_service
from app.schemas import ReplaySession

router = APIRouter(tags=["replay"])


@router.post("/{trace_id}/start", response_model=ReplaySession)
async def start_replay(trace_id: str) -> ReplaySession:
    return await replay_service.start_replay(trace_id)


@router.post("/{session_id}/pause")
async def pause_replay(session_id: str) -> dict:
    return replay_service.pause_replay(session_id)


@router.post("/{session_id}/resume")
async def resume_replay(session_id: str) -> dict:
    return replay_service.resume_replay(session_id)


@router.post("/{session_id}/step")
async def step_replay(session_id: str) -> dict:
    return replay_service.step_replay(session_id)


@router.post("/{session_id}/seek")
async def seek_replay(session_id: str, position: int = 0) -> dict:
    return replay_service.seek_replay(session_id, position)


@router.post("/{session_id}/speed")
async def speed_replay(session_id: str, multiplier: float = 1.0) -> dict:
    return replay_service.set_speed(session_id, multiplier)


@router.get("/{session_id}/state")
async def get_replay_state(session_id: str) -> dict:
    return replay_service.get_state(session_id)
