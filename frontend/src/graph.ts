import type { Edge, Node } from "@xyflow/react";

import type { EventStatus, NodeData } from "./types";

export const statusPalette: Record<EventStatus, { node: string; edge: string; text: string }> = {
  safe: {
    node: "#16a34a",
    edge: "#22c55e",
    text: "Safe",
  },
  exposed: {
    node: "#f59e0b",
    edge: "#fbbf24",
    text: "Exposed",
  },
  infected: {
    node: "#dc2626",
    edge: "#ef4444",
    text: "Infected",
  },
  quarantined: {
    node: "#6b7280",
    edge: "#9ca3af",
    text: "Quarantined",
  },
  recovered: {
    node: "#0891b2",
    edge: "#06b6d4",
    text: "Recovered",
  },
};

export const initialNodes: Node<NodeData>[] = [
  {
    id: "Gateway",
    type: "agentNode",
    position: { x: 60, y: 180 },
    data: { label: "Gateway", role: "Gateway", subtitle: "Single system entry point", status: "safe" },
  },
  {
    id: "Agent_A",
    type: "agentNode",
    position: { x: 360, y: 80 },
    data: { label: "Agent_A", role: "Agent", subtitle: "Reasoning and context handling", status: "safe" },
  },
  {
    id: "Agent_B",
    type: "agentNode",
    position: { x: 360, y: 280 },
    data: { label: "Agent_B", role: "Agent", subtitle: "Cascade collaboration node", status: "safe" },
  },
  {
    id: "Tool_Search",
    type: "agentNode",
    position: { x: 680, y: 70 },
    data: { label: "Tool_Search", role: "Tool", subtitle: "Search and evidence extraction", status: "safe" },
  },
  {
    id: "Tool_Memory",
    type: "agentNode",
    position: { x: 680, y: 300 },
    data: { label: "Tool_Memory", role: "Tool", subtitle: "Shared memory read/write", status: "safe" },
  },
  {
    id: "Monitor_Node",
    type: "agentNode",
    position: { x: 360, y: 470 },
    data: { label: "Monitor_Node", role: "Monitor", subtitle: "Bus security interception", status: "safe" },
  },
];

export const initialEdges: Edge[] = [
  edge("Gateway-Agent_A", "Gateway", "Agent_A"),
  edge("Gateway-Agent_B", "Gateway", "Agent_B"),
  edge("Agent_A-Agent_B", "Agent_A", "Agent_B"),
  edge("Agent_A-Tool_Search", "Agent_A", "Tool_Search"),
  edge("Agent_B-Tool_Memory", "Agent_B", "Tool_Memory"),
  edge("MessageBus-Monitor_A", "Agent_A", "Monitor_Node", true),
  edge("MessageBus-Monitor_B", "Agent_B", "Monitor_Node", true),
];

function edge(id: string, source: string, target: string, dashed = false): Edge {
  return {
    id,
    source,
    target,
    type: "smoothstep",
    animated: false,
    style: {
      stroke: dashed ? "#94a3b8" : "#64748b",
      strokeDasharray: dashed ? "6 6" : undefined,
      strokeWidth: dashed ? 1.5 : 2,
    },
  };
}
