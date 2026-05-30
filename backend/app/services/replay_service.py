"""Replay business logic — session management and replay orchestration.

Sessions are stored in-memory (process-local dict). Not suitable for multi-worker
deployment without an external session store (Redis, SQLite, etc.).
"""

import time

from fastapi import HTTPException

from app.event_store import get_event_store
from app.replay.engine import ReplayEngine


MAX_REPLAY_SESSIONS = 100
REPLAY_SESSION_TTL_SECONDS = 3600

_replay_sessions: dict[str, ReplayEngine] = {}
_session_created_at: dict[str, float] = {}


def _evict_expired_sessions() -> None:
    now = time.time()
    expired = [
        sid for sid, created in _session_created_at.items()
        if now - created > REPLAY_SESSION_TTL_SECONDS
    ]
    for sid in expired:
        _replay_sessions.pop(sid, None)
        _session_created_at.pop(sid, None)


def _enforce_max_sessions() -> None:
    if len(_replay_sessions) >= MAX_REPLAY_SESSIONS:
        oldest = min(_session_created_at, key=_session_created_at.get)
        _replay_sessions.pop(oldest, None)
        _session_created_at.pop(oldest, None)


async def start_replay(trace_id: str) -> dict:
    store = await get_event_store()
    events = await store.get_events_by_trace(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail="trace not found")
    _evict_expired_sessions()
    _enforce_max_sessions()
    engine = ReplayEngine(events)
    _replay_sessions[engine.session_id] = engine
    _session_created_at[engine.session_id] = time.time()
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
