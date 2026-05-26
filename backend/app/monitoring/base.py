from app.message_bus import MessageBus
from app.schemas import AgentEvent


class BaseMonitorNode:
    def __init__(self, node_id: str, bus: MessageBus) -> None:
        self.node_id = node_id
        self.bus = bus
        self.bus.attach_monitor(self.inspect)

    async def inspect(self, event: AgentEvent) -> AgentEvent | None:
        return event
