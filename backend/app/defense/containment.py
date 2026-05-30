from __future__ import annotations

from app.defense.schemas import ContainmentPlan
from app.schemas import EventType


class ContainmentRegistry:
    def __init__(self) -> None:
        self.quarantined_nodes: set[str] = set()
        self.isolated_tools: set[str] = set()
        self.blocked_edges: set[tuple[str, str]] = set()
        self.revoked_memory_keys: set[str] = set()

    def apply_plan(self, plan: ContainmentPlan) -> None:
        self.quarantined_nodes.update(plan.quarantine_nodes)
        self.isolated_tools.update(plan.isolate_tools)
        self.blocked_edges.update(tuple(e) for e in plan.block_edges)
        self.revoked_memory_keys.update(plan.revoke_memory_keys)

    def blocks_event(self, event) -> tuple[bool, str]:
        if event.source_node in self.quarantined_nodes:
            return True, f"source node {event.source_node} is quarantined"
        if event.target_node in self.quarantined_nodes:
            return True, f"target node {event.target_node} is quarantined"
        if event.target_node in self.isolated_tools:
            return True, f"tool {event.target_node} is isolated"
        if (event.source_node, event.target_node) in self.blocked_edges:
            return True, f"edge {event.source_node}->{event.target_node} is blocked"
        memory_key = event.metadata.get("memory_key")
        if memory_key and memory_key in self.revoked_memory_keys:
            return True, f"memory key {memory_key} was revoked"
        return False, ""

    def release_node(self, node_id: str) -> None:
        self.quarantined_nodes.discard(node_id)
        self.blocked_edges = {
            edge for edge in self.blocked_edges
            if edge[0] != node_id and edge[1] != node_id
        }

    def release_tool(self, tool_id: str) -> None:
        self.isolated_tools.discard(tool_id)

    def release_edge(self, source: str, target: str) -> None:
        self.blocked_edges.discard((source, target))

    def release_memory_key(self, key: str) -> None:
        self.revoked_memory_keys.discard(key)


class ContainmentPlanner:
    def __init__(self, threat_memory=None) -> None:
        self._threat_memory = threat_memory

    def plan(self, event, votes, final_action: str, context) -> ContainmentPlan:
        quarantine_nodes: list[str] = []
        isolate_tools: list[str] = []
        block_edges: list[tuple[str, str]] = [(event.source_node, event.target_node)]
        revoke_memory_keys: list[str] = []
        infected_nodes: list[str] = []
        notify_agents: list[str] = []

        if final_action in {"quarantine", "isolate"}:
            quarantine_nodes.append(event.source_node)

        if final_action == "isolate":
            infected_nodes.append(event.source_node)
            if event.event_type == EventType.TOOL_CALL:
                isolate_tools.append(event.target_node)
            for edge in self._outgoing_edges(event.source_node, context.trace_graph):
                block_edges.append((edge["source"], edge["target"]))

        if event.metadata.get("memory_op") == "write":
            key = event.metadata.get("memory_key")
            if key:
                revoke_memory_keys.append(key)

        notify_agents = self._neighbors(event.source_node, context.trace_graph)

        return ContainmentPlan(
            infected_nodes=infected_nodes,
            quarantine_nodes=quarantine_nodes,
            isolate_tools=isolate_tools,
            block_edges=block_edges,
            revoke_memory_keys=revoke_memory_keys,
            notify_agents=notify_agents,
            recovery_required=final_action in {"quarantine", "isolate"},
            rationale=f"{final_action} triggered by joint defense consensus",
        )

    @staticmethod
    def _outgoing_edges(source_node: str, trace_graph: dict | None) -> list[dict]:
        if not trace_graph:
            return []
        edges = trace_graph.get("edges", [])
        return [e for e in edges if e.get("source") == source_node]

    @staticmethod
    def _neighbors(source_node: str, trace_graph: dict | None) -> list[str]:
        if not trace_graph:
            return []
        nodes = trace_graph.get("nodes", [])
        neighbor_ids = set()
        edges = trace_graph.get("edges", [])
        for e in edges:
            if e.get("source") == source_node:
                neighbor_ids.add(e.get("target", ""))
            elif e.get("target") == source_node:
                neighbor_ids.add(e.get("source", ""))
        return [n for n in neighbor_ids if n]
