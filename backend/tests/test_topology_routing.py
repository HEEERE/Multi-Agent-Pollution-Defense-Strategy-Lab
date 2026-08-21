"""Agents must route along declared topology edges.

The original implementation hardcoded ``target_node="Auditor_Prime"`` for every
agent reply, so a configured chain such as
``RAG -> agent_a -> agent_b -> tool`` silently stopped after one hop: the
downstream agent never received anything and the tool was never reached. A
research setup depends on that chain actually propagating, so this is checked
directly rather than assumed.
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.llm.base import LLMResponse
from app.message_bus import MessageBus
from app.schemas import (
    AgentEvent,
    EdgeConfig,
    EventType,
    NodeConfig,
    TopologyConfig,
)
from app.simulation.topology_builder import TopologyBuilder


class _StubLLM:
    """Deterministic stand-in so routing is tested without model variance."""

    def __init__(self, reply: str = "acknowledged") -> None:
        self.reply = reply
        self.calls = 0

    async def chat(self, messages, temperature=None, **kwargs) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            content=self.reply, model="stub", provider="stub", latency_ms=0
        )


def _event(target: str, source: str = "gateway") -> AgentEvent:
    return AgentEvent(
        trace_id="t",
        event_type=EventType.INPUT,
        source_node=source,
        target_node=target,
        payload_snippet="please process this task",
    )


class TestDownstreamRouting:
    async def test_reply_goes_to_declared_successor(self):
        bus = MessageBus()
        received: list[str] = []

        async def sink(e: AgentEvent) -> None:
            received.append(e.event_id)

        bus.subscribe("agent_b", sink)
        agent = BaseAgent(
            "agent_a", bus, _StubLLM(), downstream=["agent_b"]
        )

        await agent.handle_event(_event("agent_a"))

        assert received, "declared successor agent_b received nothing"
        routes = [
            (e.source_node, e.target_node)
            for e in bus.history
            if e.source_node == "agent_a"
        ]
        assert ("agent_a", "agent_b") in routes
        assert ("agent_a", "Auditor_Prime") not in routes

    async def test_fan_out_to_multiple_successors(self):
        bus = MessageBus()
        agent = BaseAgent(
            "agent_a", bus, _StubLLM(), downstream=["agent_b", "tool_x"]
        )
        await agent.handle_event(_event("agent_a"))
        targets = {
            e.target_node for e in bus.history if e.source_node == "agent_a"
        }
        assert targets == {"agent_b", "tool_x"}

    async def test_does_not_bounce_back_to_sender(self):
        """Replying to the sender would create a two-agent ping-pong."""
        bus = MessageBus()
        agent = BaseAgent(
            "agent_a", bus, _StubLLM(), downstream=["gateway", "agent_b"]
        )
        await agent.handle_event(_event("agent_a", source="gateway"))
        targets = {
            e.target_node for e in bus.history if e.source_node == "agent_a"
        }
        assert targets == {"agent_b"}, "reply was echoed back to the sender"

    async def test_falls_back_to_default_target_without_topology(self):
        """The legacy demo topology has no declared edges and must keep working."""
        bus = MessageBus()
        agent = BaseAgent("agent_a", bus, _StubLLM())
        await agent.handle_event(_event("agent_a"))
        targets = {
            e.target_node for e in bus.history if e.source_node == "agent_a"
        }
        assert targets == {BaseAgent.DEFAULT_TARGET}


class TestBuilderWiring:
    def test_builder_reads_successors_from_edges(self):
        cfg = TopologyConfig(
            name="chain",
            nodes=[
                NodeConfig(node_id="gateway", node_type="gateway"),
                NodeConfig(node_id="agent_a", node_type="agent"),
                NodeConfig(node_id="agent_b", node_type="agent"),
                NodeConfig(node_id="tool_x", node_type="tool"),
            ],
            edges=[
                EdgeConfig(source="gateway", target="agent_a"),
                EdgeConfig(source="agent_a", target="agent_b"),
                EdgeConfig(source="agent_b", target="tool_x"),
            ],
        )
        nodes = TopologyBuilder(cfg, MessageBus(), _StubLLM()).build()
        assert nodes["agent_a"].downstream == ["agent_b"]
        assert nodes["agent_b"].downstream == ["tool_x"]

    def test_monitor_edges_are_excluded_from_routing(self):
        """Monitors observe via subscribe_all; routing to them double-delivers."""
        cfg = TopologyConfig(
            name="monitored",
            nodes=[
                NodeConfig(node_id="agent_a", node_type="agent"),
                NodeConfig(node_id="agent_b", node_type="agent"),
                NodeConfig(node_id="watcher", node_type="monitor"),
            ],
            edges=[
                EdgeConfig(source="agent_a", target="agent_b"),
                EdgeConfig(source="agent_a", target="watcher",
                           edge_type="monitor"),
            ],
            monitors=["watcher"],
        )
        nodes = TopologyBuilder(cfg, MessageBus(), _StubLLM()).build()
        assert nodes["agent_a"].downstream == ["agent_b"]

    async def test_chain_propagates_past_the_first_hop(self):
        """The defect in one assertion: contamination must cross two agents."""
        cfg = TopologyConfig(
            name="chain",
            nodes=[
                NodeConfig(node_id="agent_a", node_type="agent"),
                NodeConfig(node_id="agent_b", node_type="agent"),
                NodeConfig(node_id="tool_x", node_type="tool"),
            ],
            edges=[
                EdgeConfig(source="agent_a", target="agent_b"),
                EdgeConfig(source="agent_b", target="tool_x"),
            ],
        )
        bus = MessageBus()
        nodes = TopologyBuilder(cfg, bus, _StubLLM()).build()

        await nodes["agent_a"].handle_event(_event("agent_a"))

        routes = {(e.source_node, e.target_node) for e in bus.history}
        assert ("agent_a", "agent_b") in routes
        assert ("agent_b", "tool_x") in routes, (
            "chain stopped before reaching the tool"
        )
