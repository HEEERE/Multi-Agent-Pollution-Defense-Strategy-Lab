import asyncio
import uuid

from app.agents.base import BaseAgent
from app.agents.auditor import AuditorAgent
from app.gateway.base import BaseGateway
from app.llm.base import ChatMessage, LLMClient
from app.message_bus import MessageBus, clear_trace_context, set_trace_context
from app.schemas import (
    ActionTaken,
    AgentEvent,
    EventSeverity,
    EventStatus,
    EventType,
    InjectionConfig,
    TopologyConfig,
)
from app.simulation.topology_builder import TopologyBuilder


class SimulationRunner:
    def __init__(
        self,
        config: TopologyConfig,
        bus: MessageBus,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.config = config
        self.bus = bus
        self.llm_client = llm_client
        self.trace_id = uuid.uuid4().hex[:16]
        self._events: list[AgentEvent] = []
        self._agent_events: dict[str, asyncio.Event] = {}

    async def run(self) -> list[AgentEvent]:
        set_trace_context(self.trace_id)

        try:
            builder = TopologyBuilder(self.config, self.bus, self.llm_client)
            nodes = builder.build()

            injection_map: dict[int, list[InjectionConfig]] = {}
            for inj in self.config.injections:
                injection_map.setdefault(inj.turn, []).append(inj)

            for turn in range(self.config.max_turns):
                if turn in injection_map:
                    for inj in injection_map[turn]:
                        await self._inject(nodes, inj)
                else:
                    await self._run_turn(nodes, turn)

                await asyncio.sleep(0.3)

            events = clear_trace_context() or []
            self._events = events
            return events
        finally:
            clear_trace_context()

    async def _inject(
        self,
        nodes: dict,
        injection: InjectionConfig,
    ) -> None:
        event = AgentEvent(
            trace_id=self.trace_id,
            event_type=EventType.INPUT,
            source_node=injection.source_node,
            target_node=injection.target_node,
            payload_snippet=injection.payload,
            status=EventStatus.SAFE,
            action_taken=ActionTaken.NONE,
            severity=EventSeverity.WARNING,
            metadata={
                **injection.metadata,
                "injection_type": injection.injection_type.value,
                "ground_truth_threat": True,
            },
        )
        await self.bus.publish(event)

    async def _run_turn(self, nodes: dict, turn: int) -> None:
        gateway = next(
            (node for node in nodes.values() if isinstance(node, BaseGateway)),
            None,
        )
        if gateway is None:
            return

        monitor_ids = set(self.config.monitors)
        agent_nodes = [
            nid for nid, n in nodes.items()
            if isinstance(n, BaseAgent)
            and not isinstance(n, AuditorAgent)
            and nid not in monitor_ids
        ]

        routed_targets = [
            edge.target
            for edge in self.config.edges
            if edge.source == gateway.node_id and edge.target in agent_nodes
        ]
        if routed_targets:
            agent_nodes = routed_targets

        if not agent_nodes:
            return

        target = agent_nodes[turn % len(agent_nodes)]
        payload = f"Process task {turn + 1} of {self.config.max_turns}."

        await gateway.submit_task(target, payload)
