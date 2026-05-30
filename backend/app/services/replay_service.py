"""Replay business logic — session management and replay orchestration."""

from fastapi import HTTPException

from app.event_store import get_event_store
from app.replay.engine import ReplayEngine


_replay_sessions: dict[str, ReplayEngine] = {}


async def start_replay(trace_id: str) -> dict:
    store = await get_event_store()
    events = await store.get_events_by_trace(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail="trace not found")
    engine = ReplayEngine(events)
    _replay_sessions[engine.session_id] = engine
    engine.play()
    return engine.get_state().model_dump()


def _get_engine(session_id: str) -> ReplayEngine:
    engine = _replay_sessions.get(session_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="session not found")
    return engine


def pause_replay(session_id: str) -> dict:
    engine = _get_engine(session_id)
    engine.pause()
    return engine.get_state().model_dump()


def resume_replay(session_id: str) -> dict:
    engine = _get_engine(session_id)
    engine.play()
    return engine.get_state().model_dump()


def step_replay(session_id: str) -> dict:
    engine = _get_engine(session_id)
    event = engine.step_forward()
    state = engine.get_state()
    result = state.model_dump()
    result["event"] = event.model_dump() if event else None
    return result


def seek_replay(session_id: str, position: int = 0) -> dict:
    engine = _get_engine(session_id)
    engine.seek(position)
    return engine.get_state().model_dump()


def set_speed(session_id: str, multiplier: float = 1.0) -> dict:
    engine = _get_engine(session_id)
    engine.set_speed(multiplier)
    return engine.get_state().model_dump()


def get_state(session_id: str) -> dict:
    engine = _get_engine(session_id)
    return engine.get_state().model_dump()
