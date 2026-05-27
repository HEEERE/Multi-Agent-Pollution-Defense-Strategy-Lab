import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import { statusPalette } from "../graph";
import type { NodeData } from "../types";

type AgentGraphNode = Node<NodeData, "agentNode">;

function statusClass(status: string): string {
  if (status === "challenged") return "node-challenged";
  if (status === "honeypotted") return "node-honeypotted";
  if (status === "infected") return "node-infected";
  if (status === "quarantined") return "node-quarantined";
  if (status === "recovered") return "node-recovered";
  return "";
}

export function AgentNode({ data }: NodeProps<AgentGraphNode>) {
  const status = data.status ?? "safe";
  const palette = statusPalette[status];
  const score = data.contamination_score ?? 0;
  const trustLevel = data.trust_level ?? "unknown";

  return (
    <div
      className={`w-[210px] rounded-lg border bg-white px-4 py-3 shadow-signal transition-colors ${statusClass(status)}`}
      style={{ borderColor: palette.node }}
    >
      <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5" />
      <div className="flex items-start gap-3">
        <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ background: palette.node }} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-slate-950">{data.label}</span>
            {score > 0 && (
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold text-white ${
                  score >= 0.75 ? "bg-rose-600" : score >= 0.5 ? "bg-amber-500" : "bg-slate-400"
                }`}
                title={`Contamination: ${(score * 100).toFixed(0)}%`}
              >
                {(score * 100).toFixed(0)}%
              </span>
            )}
            {status === "quarantined" && (
              <span className="shrink-0 rounded bg-gray-500 px-1.5 py-0.5 text-[10px] font-bold text-white">Q</span>
            )}
            {status === "isolated" && (
              <span className="shrink-0 rounded bg-purple-600 px-1.5 py-0.5 text-[10px] font-bold text-white">I</span>
            )}
          </div>
          <div className="mt-1 text-xs font-medium text-slate-600">{data.role}</div>
          <div className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{data.subtitle}</div>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <div className="inline-flex h-6 items-center rounded border px-2 text-xs font-medium" style={{ color: palette.node, borderColor: palette.node }}>
          {palette.text}
        </div>
        {trustLevel !== "unknown" && (
          <span className="text-[10px] text-slate-400">{trustLevel}</span>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5" />
    </div>
  );
}
