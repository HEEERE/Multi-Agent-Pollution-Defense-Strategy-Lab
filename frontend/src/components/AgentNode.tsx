import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import { statusPalette } from "../graph";
import type { NodeData } from "../types";

type AgentGraphNode = Node<NodeData, "agentNode">;

function statusClass(status: string): string {
  if (status === "challenged") return "node-challenged";
  if (status === "infected") return "node-infected";
  if (status === "quarantined") return "node-quarantined";
  if (status === "recovered") return "node-recovered";
  return "";
}

export function AgentNode({ data }: NodeProps<AgentGraphNode>) {
  const status = data.status ?? "safe";
  const palette = statusPalette[status];

  return (
    <div
      className={`w-[210px] rounded-lg border bg-white px-4 py-3 shadow-signal transition-colors ${statusClass(status)}`}
      style={{ borderColor: palette.node }}
    >
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5" />
      <div className="flex items-start gap-3">
        <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ background: palette.node }} />
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-950">{data.label}</div>
          <div className="mt-1 text-xs font-medium text-slate-600">{data.role}</div>
          <div className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{data.subtitle}</div>
        </div>
      </div>
      <div className="mt-3 inline-flex h-6 items-center rounded border px-2 text-xs font-medium" style={{ color: palette.node, borderColor: palette.node }}>
        {palette.text}
      </div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5" />
    </div>
  );
}
