import { X } from "lucide-react";
import { useStore } from "../store";
import { useT } from "../i18n/context";
import { statusPalette } from "../graph";

export function NodeDetailPanel() {
  const { t } = useT();
  const selectedNodeId = useStore((s) => s.selectedNodeId);
  const selectNode = useStore((s) => s.selectNode);
  const nodes = useStore((s) => s.nodes);
  const events = useStore((s) => s.events);

  if (!selectedNodeId) return null;

  const node = nodes.find((n) => n.id === selectedNodeId);
  if (!node) return null;

  const nodeEvents = events.filter(
    (e) => e.source_node === selectedNodeId || e.target_node === selectedNodeId,
  );
  const palette = statusPalette[node.data.status] ?? statusPalette.safe;

  return (
    <div className="absolute right-2 top-2 z-20 w-[340px] rounded-lg border border-slate-200 bg-white shadow-lg">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{node.data.label}</h3>
          <p className="text-xs text-slate-500">{node.data.role} · {palette.text}</p>
        </div>
        <button
          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          onClick={() => selectNode(null)}
        >
          <X size={16} />
        </button>
      </div>

      {/* Node metadata (v2) */}
      <div className="border-b border-slate-100 px-4 py-2">
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <span className="text-slate-400">Trust:</span>{" "}
            <span className="font-medium text-slate-700">{node.data.trust_level ?? "unknown"}</span>
          </div>
          <div>
            <span className="text-slate-400">Contamination:</span>{" "}
            <span className={`font-medium ${(node.data.contamination_score ?? 0) > 0.5 ? "text-rose-600" : "text-slate-700"}`}>
              {((node.data.contamination_score ?? 0) * 100).toFixed(0)}%
            </span>
          </div>
          {node.data.risk_tags && (node.data.risk_tags as string[]).length > 0 && (
            <div className="col-span-2">
              <span className="text-slate-400">Risk Tags:</span>{" "}
              <span className="font-medium text-amber-700">{(node.data.risk_tags as string[]).join(", ")}</span>
            </div>
          )}
        </div>
      </div>

      <div className="max-h-[380px] space-y-1 overflow-y-auto p-3">
        <div className="mb-2 flex items-center gap-3 text-xs">
          <span className="font-medium text-slate-600">{t("nodeDetail.history")} ({nodeEvents.length})</span>
        </div>
        {nodeEvents.slice(0, 25).map((evt, i) => (
          <div
            key={`${evt.event_id ?? i}`}
            className="flex items-start gap-2 rounded border border-slate-100 bg-slate-50 px-2 py-1.5 text-xs"
          >
            <span
              className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full"
              style={{ background: statusPalette[evt.status]?.node ?? "#16a34a" }}
            />
            <div className="min-w-0">
              <span className="font-medium">
                {evt.source_node === selectedNodeId ? "→" : "←"} {evt.source_node === selectedNodeId ? evt.target_node : evt.source_node}
              </span>
              <span className="ml-2 text-slate-400">{evt.event_type}</span>
              <div className="text-slate-600 truncate">{evt.payload_snippet.slice(0, 100)}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
