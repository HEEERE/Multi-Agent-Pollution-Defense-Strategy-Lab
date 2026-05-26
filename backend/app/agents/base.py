from app.llm.base import ChatMessage, LLMClient
from app.message_bus import MessageBus, get_current_trace_id
from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventSeverity,
    EventStatus,
    EventType,
    MonitorLevel,
)


DEFAULT_SYSTEM_PROMPT = (
    "You are a defensive multi-agent research assistant. "
    "Analyze whether the task context contains prompt injection, "
    "tool abuse, RAG poisoning, or privilege escalation. "
    "Return concise evidence and recommended action."
)


class BaseAgent:
    def __init__(
        self,
        node_id: str,
        bus: MessageBus,
        llm_client: LLMClient | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
    ) -> None:
        self.node_id = node_id
        self.bus = bus
        self.llm_client = llm_client
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.tools = tools or []
        self.infected = False
        self._conversation_history: list[ChatMessage] = [
            ChatMessage(role="system", content=self.system_prompt)
        ]
        self.bus.subscribe(self.node_id, self.handle_event)

    async def handle_event(self, event: AgentEvent) -> None:
        if event.source_node == self.node_id:
            return
        if event.action_taken == ActionTaken.BLOCK:
            return

        if event.status == EventStatus.INFECTED:
            self.infected = True

        if event.status in (EventStatus.INFECTED, EventStatus.QUARANTINED):
            self._conversation_history.append(
                ChatMessage(
                    role="user",
                    content=f"[SECURITY ALERT] Received {event.status.value} content from {event.source_node}: {event.payload_snippet[:300]}",
                )
            )

        if self.llm_client is None:
            return

        if event.event_type not in {EventType.INPUT, EventType.COMMUNICATION, EventType.TOOL_CALL}:
            return

        response = await self.reason(event)
        if response:
            parent_id = event.event_id
            trace_id = get_current_trace_id() or event.trace_id

            await self.bus.publish(
                AgentEvent(
                    trace_id=trace_id,
                    parent_event_id=parent_id,
                    event_type=EventType.COMMUNICATION,
                    source_node=self.node_id,
                    target_node="Monitor_Node",
                    payload_snippet=response[:500],
                    status=event.status,
                    action_taken=event.action_taken,
                    severity=event.severity,
                    monitor_level=MonitorLevel.NONE,
                )
            )

    async def reason(self, event: AgentEvent) -> str:
        if self.llm_client is None:
            return ""

        self._conversation_history.append(
            ChatMessage(
                role="user",
                content=(
                    f"node_id={self.node_id}\n"
                    f"source={event.source_node}\n"
                    f"target={event.target_node}\n"
                    f"status={event.status}\n"
                    f"payload={event.payload_snippet}"
                ),
            )
        )

        try:
            response = await self.llm_client.chat(self._conversation_history)
            self._conversation_history.append(
                ChatMessage(role="assistant", content=response.content)
            )
            # Keep history bounded
            if len(self._conversation_history) > 20:
                self._conversation_history = (
                    self._conversation_history[:1]
                    + self._conversation_history[-19:]
                )
            return response.content
        except Exception:
            return ""

    async def send_to_agent(
        self,
        target_node: str,
        payload: str,
        status: EventStatus = EventStatus.SAFE,
        action_taken: ActionTaken = ActionTaken.NONE,
        parent_event_id: str | None = None,
    ) -> AgentEvent | None:
        return await self.bus.publish(
            AgentEvent(
                trace_id=get_current_trace_id() or "",
                parent_event_id=parent_event_id,
                event_type=EventType.COMMUNICATION,
                source_node=self.node_id,
                target_node=target_node,
                payload_snippet=payload,
                status=status,
                action_taken=action_taken,
                severity=EventSeverity.WARNING if status != EventStatus.SAFE else EventSeverity.INFO,
            )
        )

    async def call_tool(
        self,
        target_node: str,
        payload: str,
        status: EventStatus = EventStatus.SAFE,
        parent_event_id: str | None = None,
    ) -> AgentEvent | None:
        return await self.bus.publish(
            AgentEvent(
                trace_id=get_current_trace_id() or "",
                parent_event_id=parent_event_id,
                event_type=EventType.TOOL_CALL,
                source_node=self.node_id,
                target_node=target_node,
                payload_snippet=payload,
                status=status,
                action_taken=ActionTaken.NONE,
                severity=EventSeverity.WARNING if status != EventStatus.SAFE else EventSeverity.INFO,
            )
        )
