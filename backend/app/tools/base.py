from app.message_bus import MessageBus
from app.schemas import ActionTaken, AgentEvent, EventStatus, EventType


class BaseTool:
    def __init__(self, node_id: str, bus: MessageBus) -> None:
        self.node_id = node_id
        self.bus = bus
        self.bus.subscribe(self.node_id, self.handle_event)

    async def handle_event(self, event: AgentEvent) -> None:
        await self.return_result(
            target_node=event.source_node,
            payload=f"{self.node_id} processed: {event.payload_snippet}",
            status=event.status,
        )

    async def return_result(
        self,
        target_node: str,
        payload: str,
        status: EventStatus = EventStatus.SAFE,
    ) -> AgentEvent | None:
        return await self.bus.publish(
            AgentEvent(
                event_type=EventType.TOOL_CALL,
                source_node=self.node_id,
                target_node=target_node,
                payload_snippet=payload,
                status=status,
                action_taken=ActionTaken.NONE,
            )
        )
