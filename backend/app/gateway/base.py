from app.message_bus import MessageBus
from app.schemas import ActionTaken, AgentEvent, EventStatus, EventType


class BaseGateway:
    def __init__(self, node_id: str, bus: MessageBus) -> None:
        self.node_id = node_id
        self.bus = bus

    async def submit_task(self, target_node: str, payload: str) -> AgentEvent | None:
        return await self.bus.publish(
            AgentEvent(
                event_type=EventType.INPUT,
                source_node=self.node_id,
                target_node=target_node,
                payload_snippet=payload,
                status=EventStatus.SAFE,
                action_taken=ActionTaken.NONE,
            )
        )
