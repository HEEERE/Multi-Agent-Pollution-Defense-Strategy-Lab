from app.agents.base import BaseAgent
from app.agents.auditor import AuditorAgent
from app.gateway.base import BaseGateway
from app.message_bus import MessageBus
from app.schemas import (
    NodeConfig,
    TopologyConfig,
)
from app.tools.base import BaseTool
from app.actions import ActionGateway
from app.provenance import ProvenanceLedger


class TopologyBuilder:
    def __init__(self, config: TopologyConfig, bus: MessageBus, llm_client=None, *, run_id: str | None = None) -> None:
        self.config = config
        self.bus = bus
        self.llm_client = llm_client
        self.run_id = run_id or f"simulation:{config.name}"
        self.nodes: dict[str, BaseGateway | BaseAgent | BaseTool] = {}

    def build(self) -> dict[str, BaseGateway | BaseAgent | BaseTool]:
        if self.bus.action_gateway is None:
            ledger = ProvenanceLedger()
            ledger.ensure_run(self.run_id)
            self.bus.bind_provenance_ledger(ledger, self.run_id)
            self.bus.bind_action_gateway(ActionGateway(ledger))
        self.bus.bind_topology(self.config.edges, self.config.monitors)
        for node_cfg in self.config.nodes:
            node = self._create_node(node_cfg)
            if node is not None:
                self.nodes[node_cfg.node_id] = node
        return self.nodes

    def _downstream(self, node_id: str) -> list[str]:
        """Declared successors of ``node_id``, excluding passive monitors.

        Monitors observe via ``subscribe_all``; routing output to them explicitly
        would double-deliver. Returning [] lets BaseAgent fall back to its
        default target, which keeps the legacy demo topology working.
        """
        monitors = set(self.config.monitors)
        return [
            edge.target
            for edge in self.config.edges
            if edge.source == node_id
            and edge.edge_type != "monitor"
            and edge.target not in monitors
        ]

    def _create_node(self, cfg: NodeConfig) -> BaseGateway | BaseAgent | BaseTool | None:
        node_type = cfg.node_type.lower()
        node_id = cfg.node_id

        if node_type == "gateway":
            return BaseGateway(node_id, self.bus)
        elif node_type == "agent":
            return BaseAgent(
                node_id=node_id,
                bus=self.bus,
                llm_client=self.llm_client,
                system_prompt=cfg.system_prompt or None,
                tools=cfg.tools,
                downstream=self._downstream(node_id),
            )
        elif node_type == "tool":
            return BaseTool(node_id, self.bus, self.bus.action_gateway)
        elif node_type == "memory":
            return BaseTool(node_id, self.bus, self.bus.action_gateway)
        elif node_type == "monitor":
            protected = [
                node.node_id
                for node in self.config.nodes
                if node.node_type.lower() == "agent"
            ]
            return AuditorAgent(
                node_id,
                self.bus,
                self.llm_client,
                protected_nodes=protected,
            )
        return None
