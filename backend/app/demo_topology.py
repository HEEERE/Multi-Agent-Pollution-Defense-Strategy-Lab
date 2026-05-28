from app.agents.base import BaseAgent
from app.agents.auditor import AuditorAgent
from app.agents.honeypot import HoneypotAgent
from app.agents.red_team import RedTeamAgent
from app.detectors.factory import create_default_pipeline
from app.event_store import EventStore
from app.gateway.base import BaseGateway
from app.llm.factory import get_llm_client
from app.message_bus import message_bus
from app.schemas import AgentEvent
from app.settings_manager import init_settings_manager
from app.tools.base import BaseTool
from app.tools.fake_tool import FakeTool
from app.websocket_manager import websocket_manager


# ── Shared LLM client ──────────────────────────────────────────
llm_client = get_llm_client()

# ── Entry point ────────────────────────────────────────────────
gateway = BaseGateway("Gateway", message_bus)

# ── Blue Team: Task Agents (business logic executors) ──────────
task_agent_a = BaseAgent("Task_Agent_A", message_bus, llm_client=llm_client)
task_agent_b = BaseAgent("Task_Agent_B", message_bus, llm_client=llm_client)

# ── Blue Team: Auditor (cross-validation watchdog) ─────────────
auditor = AuditorAgent(
    "Auditor_Prime",
    message_bus,
    llm_client=llm_client,
    protected_nodes=["Task_Agent_A", "Task_Agent_B"],
)

# ── Red Team: Automated internal attacker ──────────────────────
red_agent = RedTeamAgent(
    "Red_Attacker",
    message_bus,
    llm_client=llm_client,
    attack_interval_seconds=5.0,
    max_attacks=15,
)

# ── Honeypot: Gray-zone intelligence gathering ─────────────────
honeypot = HoneypotAgent("Honeypot_Agent", message_bus, llm_client=llm_client)

# ── Real Tools ─────────────────────────────────────────────────
tool_rag = BaseTool("Tool_RAG_Vector", message_bus)
tool_kg = BaseTool("Tool_KnowledgeGraph", message_bus)

# ── Fake Tools (honeypot sandbox) ──────────────────────────────
fake_rag = FakeTool("FakeTool_RAG", message_bus, tool_type="rag")
fake_kg = FakeTool("FakeTool_KG", message_bus, tool_type="kg")

# ── Pipeline: L1 blocker + L2/L3 gray-zone → honeypot router ──
# Created lazily via rebuild_runtime_pipeline() so settings are ready.


def rebuild_runtime_pipeline() -> None:
    message_bus._monitors.clear()
    pipeline = create_default_pipeline(llm_client=llm_client, bus=message_bus)
    message_bus.attach_monitor(pipeline.inspect)


# WebSocket broadcast
message_bus.attach_broadcast_hook(websocket_manager.broadcast)


# ── Helpers ────────────────────────────────────────────────────

async def init_event_store() -> None:
    store = EventStore()
    await store._get_conn()
    message_bus.bind_event_store(store)
    await init_settings_manager()


async def run_gateway_to_agent(payload: str) -> AgentEvent | None:
    return await gateway.submit_task("Task_Agent_A", payload)


async def run_agent_to_tool(payload: str) -> AgentEvent | None:
    return await task_agent_a.call_tool("Tool_RAG_Vector", payload)
