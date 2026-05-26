import uuid

from app.schemas import AgentEvent, ReplaySession, ReplayState


class ReplayEngine:
    def __init__(self, events: list[AgentEvent]) -> None:
        self._events = sorted(events, key=lambda e: e.timestamp)
        self._index = 0
        self._state = ReplayState.IDLE
        self._speed = 1.0
        self.session_id = uuid.uuid4().hex[:12]

    @property
    def total_events(self) -> int:
        return len(self._events)

    def play(self) -> None:
        self._state = ReplayState.PLAYING

    def pause(self) -> None:
        self._state = ReplayState.PAUSED

    def step_forward(self) -> AgentEvent | None:
        self._state = ReplayState.STEPPING
        if self._index < len(self._events):
            event = self._events[self._index]
            self._index += 1
            if self._index >= len(self._events):
                self._state = ReplayState.COMPLETED
            return event
        self._state = ReplayState.COMPLETED
        return None

    def step_backward(self) -> AgentEvent | None:
        if self._index > 0:
            self._index -= 1
            return self._events[self._index]
        return None

    def seek(self, index: int) -> None:
        self._index = max(0, min(index, len(self._events)))
        if self._state == ReplayState.COMPLETED and self._index < len(self._events):
            self._state = ReplayState.PAUSED

    def set_speed(self, multiplier: float) -> None:
        self._speed = max(0.1, min(multiplier, 16.0))

    def current_event(self) -> AgentEvent | None:
        if 0 <= self._index < len(self._events):
            return self._events[self._index]
        return None

    def get_state(self) -> ReplaySession:
        current_ts = None
        evt = self.current_event()
        if evt is not None:
            current_ts = evt.timestamp
        elif self._events:
            current_ts = self._events[-1].timestamp

        return ReplaySession(
            session_id=self.session_id,
            trace_id=self._events[0].trace_id if self._events else "",
            state=self._state,
            current_index=self._index,
            total_events=len(self._events),
            speed_multiplier=self._speed,
            current_timestamp=current_ts,
        )
