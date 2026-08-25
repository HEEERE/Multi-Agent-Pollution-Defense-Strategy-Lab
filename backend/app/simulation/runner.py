import asyncio
import uuid

from app.agents.base import BaseAgent
from app.agents.auditor import AuditorAgent
from app.gateway.base import BaseGateway
from app.llm.base import ChatMessage, LLMClient
from app.message_bus import MessageBus, clear_trace_context, set_trace_context, set_run_context, clear_run_context
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
from app.runtime import RunContext, RunEngine, RunManifest


class SimulationRunner:
    def __init__(
        self,
        config: TopologyConfig,
        bus: MessageBus,
        llm_client: LLMClient | None = None,
        label_sink=None,
    ) -> None:
        self.config = config
        self.bus = bus
        self.llm_client = llm_client
        # Write-only callback supplied by the harness. The runner records which
        # events it injected without knowing where labels are kept, so the
        # runtime holds no handle it could read ground truth back through.
        self.label_sink = label_sink
        self.trace_id = uuid.uuid4().hex[:16]
        self._events: list[AgentEvent] = []
        self._agent_events: dict[str, asyncio.Event] = {}
        self.run_id = str((config.metadata or {}).get("run_id") or self.trace_id)
        self.runtime: RunEngine | None = None
        self.runtime_context: RunContext | None = None

    def _ensure_runtime_authority(self) -> None:
        """Bind standalone simulations through the same RunEngine path.

        Formal experiments arrive with an already-bound bus and reuse that
        context.  API/demo simulations still work, but their authority is now
        created here by RunEngine instead of being hidden inside TopologyBuilder.
        """
        if self.bus.action_gateway is not None:
            bound_run_id = self.bus.provenance_run_id
            if bound_run_id is not None and bound_run_id != self.run_id:
                raise ValueError(
                    f"simulation run_id {self.run_id!r} disagrees with bound "
                    f"runtime {bound_run_id!r}"
                )
            return

        metadata = dict(self.config.metadata or {})
        manifest = RunManifest(
            run_id=self.run_id,
            topology=self.config.model_dump(mode="json"),
            effect_mode=str(metadata.get("effect_mode", "live")),
            horizon_closure=str(metadata.get("horizon_closure", "closed")),
        )
        self.runtime = RunEngine()
        self.runtime_context = self.runtime.create_run(manifest)
        self.bus.bind_provenance_ledger(
            self.runtime_context.ledger, self.runtime_context.manifest.run_id
        )
        self.bus.bind_action_gateway(self.runtime_context.gateway)
        self.bus.bind_effect_sandbox(self.runtime_context.effect_sandbox)

    async def run(self) -> list[AgentEvent]:
        set_trace_context(self.trace_id)
        # Give each simulation an isolated provenance run even when the global
        # process-wide bus is reused by successive experiments.
        set_run_context(self.run_id)

        try:
            self._ensure_runtime_authority()
            builder = TopologyBuilder(self.config, self.bus, self.llm_client, run_id=self.run_id)
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
            clear_run_context()

    async def _inject(
        self,
        nodes: dict,
        injection: InjectionConfig,
    ) -> None:
        # No ground-truth label in metadata. The label goes to the write-only
        # sink the harness supplied, so no online component can read it: a
        # detector that sees the label can tune itself on it, which invalidates
        # every metric it produces.
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
            },
            trust_level=str(injection.metadata.get("trust_level", "untrusted")),
        )
        published = await self.bus.publish(event)
        if self.label_sink is not None:
            self.label_sink(
                (published or event).event_id,
                True,
                injection.injection_type.value,
            )

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
