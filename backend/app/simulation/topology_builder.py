from app.agents.base import BaseAgent
from app.agents.auditor import AuditorAgent
from app.gateway.base import BaseGateway
from app.message_bus import MessageBus
from app.schemas import (
    NodeConfig,
    TopologyConfig,
)
from app.tools.base import BaseTool


class TopologyBuilder:
    def __init__(self, config: TopologyConfig, bus: MessageBus, llm_client=None) -> None:
        self.config = config
        self.bus = bus
        self.llm_client = llm_client
        self.nodes: dict[str, BaseGateway | BaseAgent | BaseTool] = {}

    def build(self) -> dict[str, BaseGateway | BaseAgent | BaseTool]:
        self.bus.bind_topology(self.config.edges, self.config.monitors)
        for node_cfg in self.config.nodes:
            node = self._create_node(node_cfg)
            if node is not None:
                self.nodes[node_cfg.node_id] = node
        return self.nodes

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
            )
        elif node_type == "tool":
            return BaseTool(node_id, self.bus)
        elif node_type == "memory":
            return BaseTool(node_id, self.bus)
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
