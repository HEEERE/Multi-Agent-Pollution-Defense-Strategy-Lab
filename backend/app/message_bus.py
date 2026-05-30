from collections import deque
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from app.schemas import ActionTaken, AgentEvent, EventSeverity, EventStatus

EventHandler = Callable[[AgentEvent], Awaitable[None]]
MonitorHook = Callable[[AgentEvent], Awaitable[AgentEvent | None]]
BroadcastHook = Callable[[AgentEvent], Awaitable[None]]

_current_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_pending_events: ContextVar[list[AgentEvent] | None] = ContextVar("pending_events", default=None)


def get_current_trace_id() -> str | None:
    return _current_trace_id.get()


def set_trace_context(trace_id: str) -> None:
    _current_trace_id.set(trace_id)
    _pending_events.set([])


def clear_trace_context() -> list[AgentEvent]:
    events = _pending_events.get() or []
    _current_trace_id.set(None)
    _pending_events.set(None)
    return events


def collect_event(event: AgentEvent) -> None:
    pending = _pending_events.get()
    if pending is not None:
        pending.append(event)


class MessageBus:
    """Central async bus. Agents never call each other directly."""

    def __init__(self, max_history: int = 500) -> None:
        self._handlers: dict[str, EventHandler] = {}
        self._all_listeners: list[EventHandler] = []
        self._monitors: list[MonitorHook] = []
        self._broadcast_hooks: list[BroadcastHook] = []
        self.history: deque[AgentEvent] = deque(maxlen=max_history)
        self._event_store = None
        self._containment_registry = None

    def bind_event_store(self, event_store) -> None:
        self._event_store = event_store

    def bind_containment_registry(self, registry) -> None:
        self._containment_registry = registry

    def subscribe(self, node_id: str, handler: EventHandler) -> None:
        self._handlers[node_id] = handler

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler that receives ALL events regardless of target_node.
        Used by Auditor agents to monitor the entire bus for threat detection."""
        self._all_listeners.append(handler)

    def unsubscribe(self, node_id: str) -> None:
        self._handlers.pop(node_id, None)

    def attach_monitor(self, hook: MonitorHook) -> None:
        self._monitors.append(hook)

    def replace_monitors(self, monitors: list[MonitorHook]) -> None:
        self._monitors = list(monitors)

    def attach_broadcast_hook(self, hook: BroadcastHook) -> None:
        self._broadcast_hooks.append(hook)

    def remove_broadcast_hook(self, hook: BroadcastHook) -> None:
        try:
            self._broadcast_hooks.remove(hook)
        except ValueError:
            pass

    async def publish(self, event: AgentEvent) -> AgentEvent | None:
        trace_id = get_current_trace_id()
        if trace_id and event.trace_id != trace_id:
            event = event.model_copy(update={"trace_id": trace_id})

        inspected_event: AgentEvent | None = event

        for monitor in self._monitors:
            if inspected_event is None:
                break
            inspected_event = await monitor(inspected_event)

        if inspected_event is None:
            return None

        self.history.append(inspected_event)
        collect_event(inspected_event)

        if self._event_store is not None:
            try:
                await self._event_store.store_event(inspected_event)
            except Exception:
                pass

        await self._broadcast(inspected_event)

        # Containment check: intercept events from quarantined/blocked nodes
        if self._containment_registry is not None:
            blocked, reason = self._containment_registry.blocks_event(inspected_event)
            if blocked:
                inspected_event = inspected_event.model_copy(
                    update={
                        "status": EventStatus.QUARANTINED,
                        "action_taken": ActionTaken.BLOCK,
                        "severity": EventSeverity.CRITICAL,
                        "metadata": {
                            **inspected_event.metadata,
                            "containment_blocked": True,
                            "containment_reason": reason,
                        },
                    }
                )

        if inspected_event.action_taken in (ActionTaken.BLOCK, ActionTaken.ISOLATE):
            return inspected_event

        target_handler = self._handlers.get(inspected_event.target_node)
        if target_handler is not None:
            await target_handler(inspected_event)

        for listener in self._all_listeners:
            try:
                await listener(inspected_event)
            except Exception:
                pass

        return inspected_event

    async def emit(self, event: AgentEvent) -> AgentEvent:
        trace_id = get_current_trace_id()
        if trace_id and event.trace_id != trace_id:
            event = event.model_copy(update={"trace_id": trace_id})

        self.history.append(event)
        collect_event(event)

        if self._event_store is not None:
            try:
                await self._event_store.store_event(event)
            except Exception:
                pass

        await self._broadcast(event)
        return event

    async def _broadcast(self, event: AgentEvent) -> None:
        stale_hooks: list[BroadcastHook] = []

        for hook in self._broadcast_hooks:
            try:
                await hook(event)
            except RuntimeError:
                stale_hooks.append(hook)

        for hook in stale_hooks:
            self._broadcast_hooks.remove(hook)


message_bus = MessageBus()
