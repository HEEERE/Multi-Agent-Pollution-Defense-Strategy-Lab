from app.replay.engine import ReplayEngine
from app.schemas import AgentEvent, ReplayState


def make_event(event_id: str, timestamp: float) -> AgentEvent:
    return AgentEvent(
        event_id=event_id,
        trace_id="trace_replay",
        timestamp=timestamp,
        event_type="input",
        source_node="gateway",
        target_node="agent",
        payload_snippet=event_id,
    )


def test_step_keeps_playing_until_last_event():
    engine = ReplayEngine([make_event("e1", 1), make_event("e2", 2)])
    engine.play()

    assert engine.step_forward().event_id == "e1"
    assert engine.get_state().state == ReplayState.PLAYING

    assert engine.step_forward().event_id == "e2"
    assert engine.get_state().state == ReplayState.COMPLETED
