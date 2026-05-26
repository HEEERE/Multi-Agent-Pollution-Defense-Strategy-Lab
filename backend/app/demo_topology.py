from app.agents.base import BaseAgent
from app.detectors.factory import create_default_pipeline
from app.event_store import EventStore
from app.gateway.base import BaseGateway
from app.llm.factory import get_llm_client
from app.message_bus import message_bus
from app.schemas import AgentEvent
from app.tools.base import BaseTool
from app.websocket_manager import websocket_manager


# Topology nodes
gateway = BaseGateway("Gateway", message_bus)
llm_client = get_llm_client()
agent_a = BaseAgent("Agent_A", message_bus, llm_client=llm_client)
agent_b = BaseAgent("Agent_B", message_bus, llm_client=llm_client)
tool_search = BaseTool("Tool_Search", message_bus)
tool_memory = BaseTool("Tool_Memory", message_bus)

# Monitor: pluggable 3-level detector pipeline attached to the message bus
pipeline = create_default_pipeline(llm_client=llm_client, bus=message_bus)
message_bus.attach_monitor(pipeline.inspect)

# Subscribe a lightweight monitor node for topology visualization
async def _monitor_handler(event: AgentEvent) -> None:
    pass  # events are already inspected by the pipeline hook

message_bus.subscribe("Monitor_Node", _monitor_handler)

# WebSocket broadcast
message_bus.attach_broadcast_hook(websocket_manager.broadcast)


async def init_event_store() -> None:
    store = EventStore()
    await store._get_conn()
    message_bus.bind_event_store(store)


async def run_gateway_to_agent(payload: str) -> AgentEvent | None:
    return await gateway.submit_task("Agent_A", payload)


async def run_agent_to_tool(payload: str) -> AgentEvent | None:
    return await agent_a.call_tool("Tool_Search", payload)
