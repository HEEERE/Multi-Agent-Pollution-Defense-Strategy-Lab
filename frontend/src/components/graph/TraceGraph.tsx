import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import { useMemo } from "react";
import type { AgentEvent, TraceGraphData, TraceNode } from "../../lib/types";

const colors = {
  safe: "#38d989",
  warning: "#f8b825",
  danger: "#ff4f45",
  isolated: "#a86bff",
  recovered: "#43a6ff",
  unknown: "#71869a",
};

function nodeTone(node: TraceNode) {
  if (node.contamination_score >= 0.75) return colors.danger;
  if (node.contamination_score >= 0.5) return colors.isolated;
  if (node.contamination_score >= 0.2) return colors.warning;
  if (node.trust_level === "trusted") return colors.safe;
  return colors.recovered;
}

function inferType(id: string) {
  const normalized = id.toLowerCase();
  if (normalized.includes("gateway")) return "gateway";
  if (normalized.includes("tool")) return "tool";
  if (normalized.includes("monitor") || normalized.includes("auditor")) return "monitor";
  if (normalized.includes("memory") || normalized.includes("mem")) return "memory";
  return "agent";
}

function fromEvents(events: AgentEvent[]): TraceGraphData {
  const nodes = new Map<string, TraceNode>();
  events.forEach((event) => {
    [event.source_node, event.target_node].forEach((id) => {
      const existing = nodes.get(id);
      nodes.set(id, {
        node_id: id,
        node_type: inferType(id),
        label: id,
        contamination_score: Math.max(
          existing?.contamination_score ?? 0,
          event.contamination_score || (event.status === "infected" ? 0.8 : 0),
        ),
        trust_level: event.trust_level,
        metadata: {},
      });
    });
  });
  return {
    trace_id: events[0]?.trace_id ?? "",
    nodes: [...nodes.values()],
    edges: events.map((event) => ({
      edge_id: event.event_id,
      trace_id: event.trace_id,
      source: event.source_node,
      target: event.target_node,
      event_id: event.event_id,
      edge_kind: event.edge_kind ?? event.event_type,
      timestamp: event.timestamp,
      risk_tags: event.risk_tags,
      contamination_delta: event.contamination_score,
      metadata: { status: event.status },
    })),
    metrics: {},
  };
}

export function TraceGraph({
  graph,
  events = [],
  onNodeClick,
}: {
  graph?: TraceGraphData;
  events?: AgentEvent[];
  onNodeClick?: (nodeId: string) => void;
}) {
  const data = graph?.nodes?.length ? graph : fromEvents(events);
  const { nodes, edges } = useMemo(() => {
    const groups = new Map<string, TraceNode[]>();
    data.nodes.forEach((node) => {
      const inferred = inferType(node.node_id);
      const type = inferred !== "agent" ? inferred : node.node_type || inferred;
      groups.set(type, [...(groups.get(type) ?? []), node]);
    });
    const order = ["gateway", "agent", "tool", "monitor", "memory"];
    const flowNodes: Node[] = [];
    const activeTypes = order.filter((type) => (groups.get(type)?.length ?? 0) > 0);
    activeTypes.forEach((type, rowIndex) => {
      const row = groups.get(type) ?? [];
      row.forEach((item, colIndex) => {
        const tone = nodeTone(item);
        flowNodes.push({
          id: item.node_id,
          position: {
            x: 90 + colIndex * 210 + (rowIndex % 2) * 70,
            y: 50 + rowIndex * 145,
          },
          data: {
            label: (
              <div className="min-w-28 text-left">
                <div className="text-[10px] uppercase tracking-wider text-slate-500">
                  {type}
                </div>
                <div className="mt-1 truncate text-xs font-semibold text-white">
                  {item.label || item.node_id}
                </div>
                <div className="mt-1 text-[10px]" style={{ color: tone }}>
                  污染分数 {(item.contamination_score ?? 0).toFixed(2)}
                </div>
              </div>
            ),
          },
          style: {
            width: 150,
            border: `1px solid ${tone}`,
            borderRadius: 12,
            background: "#0a1b27",
            color: "#dceaf2",
            padding: 12,
            boxShadow: `0 0 18px ${tone}20`,
          },
        });
      });
    });

    const flowEdges: Edge[] = data.edges.map((edge) => {
      const dangerous =
        edge.contamination_delta >= 0.5 ||
        edge.metadata?.status === "infected";
      const intervention = edge.edge_kind === "intervention";
      const color = dangerous
        ? colors.danger
        : intervention
          ? colors.isolated
          : colors.safe;
      return {
        id: edge.edge_id,
        source: edge.source,
        target: edge.target,
        label: edge.edge_kind,
        animated: dangerous,
        markerEnd: { type: MarkerType.ArrowClosed, color },
        style: { stroke: color, strokeWidth: dangerous ? 2.2 : 1.4 },
        labelStyle: { fill: "#7890a2", fontSize: 9 },
        labelBgStyle: { fill: "#06111b", fillOpacity: 0.9 },
      };
    });
    return { nodes: flowNodes, edges: flowEdges };
  }, [data]);

  return (
    <div className="h-full min-h-[520px] overflow-hidden rounded-xl border border-slate-700/60 bg-[#04101a]">
      <ReactFlow
        key={`${graph?.nodes?.length ? "server" : "events"}-${data.trace_id}`}
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.18, maxZoom: 1.2 }}
        minZoom={0.3}
        maxZoom={1.3}
        onNodeClick={(_, node) => onNodeClick?.(node.id)}
      >
        <Background color="#153042" gap={24} size={1} />
        <Controls position="top-left" />
        <MiniMap
          pannable
          zoomable
          bgColor="#06111b"
          maskColor="rgba(3, 10, 17, 0.72)"
          nodeColor={(node) => String(node.style?.borderColor ?? colors.unknown)}
        />
      </ReactFlow>
    </div>
  );
}
