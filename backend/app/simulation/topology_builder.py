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
    def __init__(self, config: TopologyConfig, bus: MessageBus, llm_client=None, *, run_id: str | None = None) -> None:
        self.config = config
        self.bus = bus
        self.llm_client = llm_client
        self.run_id = run_id or f"simulation:{config.name}"
        self.nodes: dict[str, BaseGateway | BaseAgent | BaseTool] = {}
        self._node_configs = {node.node_id: node for node in config.nodes}

    def build(self) -> dict[str, BaseGateway | BaseAgent | BaseTool]:
        if self.bus.action_gateway is None:
            raise RuntimeError(
                "TopologyBuilder requires a MessageBus bound by RunEngine; "
                "topology construction is not a runtime authority"
            )
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
            return BaseGateway(node_id, self.bus, metadata=cfg.metadata)
        elif node_type == "agent":
            metadata = dict(cfg.metadata)
            downstream_effects = dict(metadata.get("downstream_effects", {}) or {})
            downstream_operations = dict(metadata.get("downstream_operations", {}) or {})
            tool_targets = set(metadata.get("tool_targets", ()) or ())
            for target in self._downstream(node_id):
                target_cfg = self._node_configs.get(target)
                if target_cfg is not None and target_cfg.node_type.lower() in {"tool", "memory"}:
                    tool_targets.add(target)
                    downstream_effects.setdefault(
                        target, str(target_cfg.metadata.get("effect_class", "E1"))
                    )
                    downstream_operations.setdefault(
                        target, str(target_cfg.metadata.get("operation", "tool_call"))
                    )
            metadata["downstream_effects"] = downstream_effects
            metadata["downstream_operations"] = downstream_operations
            metadata["tool_targets"] = sorted(tool_targets)
            return BaseAgent(
                node_id=node_id,
                bus=self.bus,
                llm_client=self.llm_client,
                system_prompt=cfg.system_prompt or None,
                tools=cfg.tools,
                downstream=self._downstream(node_id),
                metadata=metadata,
            )
        elif node_type == "tool":
            self._register_sandbox_tool(cfg)
            return BaseTool(node_id, self.bus, self.bus.action_gateway, metadata=cfg.metadata)
        elif node_type == "memory":
            self._register_sandbox_tool(cfg)
            return BaseTool(node_id, self.bus, self.bus.action_gateway, metadata=cfg.metadata)
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

    def _register_sandbox_tool(self, cfg: NodeConfig) -> None:
        sandbox = self.bus.effect_sandbox
        if sandbox is None:
            return
        raw_effect = str(cfg.metadata.get("effect_class", "E1"))
        sandbox.register_tool(
            self.bus.action_gateway,
            tool_id=cfg.node_id,
            operation=str(cfg.metadata.get("operation", "tool_call")),
            effect_class=raw_effect,
            resource_scopes=set(cfg.metadata.get("resource_scopes", ["default"]) or ["default"]),
            required_capabilities=set(cfg.metadata.get("required_capabilities", ()) or ()),
            reversible=cfg.metadata.get("reversible"),
            required_integrity=cfg.metadata.get("required_integrity"),
        )
