from app.message_bus import MessageBus
from app.schemas import ActionTaken, AgentEvent, EventStatus, EventType


class BaseGateway:
    def __init__(self, node_id: str, bus: MessageBus, *, metadata: dict | None = None) -> None:
        self.node_id = node_id
        self.bus = bus
        self.metadata = dict(metadata or {})

    async def submit_task(self, target_node: str, payload: str) -> AgentEvent | None:
        return await self.bus.publish(
            AgentEvent(
                event_type=EventType.INPUT,
                source_node=self.node_id,
                target_node=target_node,
                payload_snippet=payload,
                status=EventStatus.SAFE,
                action_taken=ActionTaken.NONE,
                trust_level=str(self.metadata.get("trust_level", "trusted")),
            )
        )
