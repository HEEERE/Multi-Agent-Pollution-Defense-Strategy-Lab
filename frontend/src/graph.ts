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
  challenged: {
    node: "#f97316",
    edge: "#fb923c",
    text: "Challenged",
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
  // ── Entry ──
  {
    id: "Gateway",
    type: "agentNode",
    position: { x: 60, y: 250 },
    data: { label: "Gateway", role: "Entry Point", subtitle: "External task submission", status: "safe" },
  },
  // ── Blue Team: Task Agents ──
  {
    id: "Task_Agent_A",
    type: "agentNode",
    position: { x: 340, y: 100 },
    data: { label: "Task_Agent_A", role: "Blue Executor", subtitle: "Business logic & reasoning", status: "safe" },
  },
  {
    id: "Task_Agent_B",
    type: "agentNode",
    position: { x: 340, y: 400 },
    data: { label: "Task_Agent_B", role: "Blue Executor", subtitle: "Cascade collaboration node", status: "safe" },
  },
  // ── Blue Team: Auditor ──
  {
    id: "Auditor_Prime",
    type: "agentNode",
    position: { x: 620, y: 250 },
    data: { label: "Auditor_Prime", role: "Blue Auditor", subtitle: "Cross-validation watchdog", status: "safe" },
  },
  // ── Red Team ──
  {
    id: "Red_Attacker",
    type: "agentNode",
    position: { x: 60, y: 480 },
    data: { label: "Red_Attacker", role: "Red Team", subtitle: "Continuous internal attack testing", status: "safe" },
  },
  // ── Tools ──
  {
    id: "Tool_RAG_Vector",
    type: "agentNode",
    position: { x: 820, y: 100 },
    data: { label: "Tool_RAG", role: "Tool", subtitle: "Vector search & retrieval", status: "safe" },
  },
  {
    id: "Tool_KnowledgeGraph",
    type: "agentNode",
    position: { x: 820, y: 400 },
    data: { label: "Tool_KG", role: "Tool", subtitle: "Knowledge graph query", status: "safe" },
  },
];

export const initialEdges: Edge[] = [
  // Gateway → Task Agents
  edge("gw-task_a", "Gateway", "Task_Agent_A"),
  edge("gw-task_b", "Gateway", "Task_Agent_B"),

  // Task Agents ↔ each other
  edge("ta-tb", "Task_Agent_A", "Task_Agent_B"),

  // Task Agents → Tools
  edge("ta-rag", "Task_Agent_A", "Tool_RAG_Vector"),
  edge("tb-kg", "Task_Agent_B", "Tool_KnowledgeGraph"),

  // Task Agents → Auditor (all communications monitored, dashed)
  edge("ta-audit", "Task_Agent_A", "Auditor_Prime", true),
  edge("tb-audit", "Task_Agent_B", "Auditor_Prime", true),

  // Red Team → Task Agents (attack injection)
  edge("red-ta", "Red_Attacker", "Task_Agent_A", true),
  edge("red-tb", "Red_Attacker", "Task_Agent_B", true),
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
